"""StrategicAgent: every number and decision in code, the e-mail text from a template or an LLM.

Per thread and round t:
  C_goal     the best deal we think the supplier accepts (our floor estimate, best levers)
  C_reserve  the worst deal we take: min(C_open, C_alt, best rival standing sheet)
  target(t)  goal - anchor*span at t=0, then goal + span * (t/T)^beta
It accepts a standing sheet near the target (or a final offer below reserve, or a stall), walks
when the alternative is better, and otherwise sends up to `n_sheets` term sheets that cost us the
target: the cheapest package at our floor estimate plus equal-cost trades that probe the supplier.
"""

import logging
import math

from arena_kit.cost import must_haves_ok, total_cost
from arena_kit.docs import quote_terms, standard_terms
from arena_kit.play import latest, live_threads, moves_left, standing

from . import compliance, intel, levers
from .params import Params, load_params

log = logging.getLogger("arena")


def _opening_standard(events):
    """Standard terms from the quote PDF, else from the opening quote's stated terms."""
    std = standard_terms(events)
    if std:
        return std
    for m in events:
        for att in m.get("attachments") or []:
            if att.get("text"):
                q = quote_terms(att["text"])
                return q.get("standard") or q.get("stated") or {}
    return {}


class Thread:
    """What we know and plan for one supplier."""

    def __init__(self, agent, case, sid, events):
        self.sid = sid
        self.std = _opening_standard(events)
        _, opening = standing(events)
        self.opening_terms = {**opening}
        self.asked = opening.get("unit_price")
        self.dossier = intel.build(case, sid, agent.package, self.asked)
        self.sup = intel.estimate(case, self.dossier, self.std, self.asked, agent.p)
        self.used_claims = set()
        self.offers = []  # our target C per message
        self.theirs = []  # C of its standing sheet after each reply
        p, b = agent.p, case["buyer"]
        # the floor is its minimum margin; the relationship term (stabilise / secure_supply) is in C,
        # so best_deal finds where squeezing further costs more than it saves
        self.margin = p.min_margin
        if self.asked and self.sup["full_cost"]:
            # an estimate that puts its floor above its own ask is wrong: it quoted, so it can live there
            open_pkg = {k: v for k, v in self.opening_terms.items() if k != "unit_price"}
            floor = levers.floor_price(case, open_pkg, self.sup, self.margin)
            if math.isfinite(floor) and floor > self.asked * 0.97:
                self.sup["full_cost"] *= self.asked * 0.97 / floor
        if b.get("category_goal") in ("stabilise", "secure_supply"):
            self.sup["full_cost"] *= 1 + p.margin_buffer / 100  # caution: assume it is a bit costlier
        c, pkg, price = levers.best_deal(case, self.std, self.sup, self.margin, price_cap=self.asked)
        self.goal_pkg, self.goal_price = pkg, price
        self.c_goal = c
        self.parked = False
        self.last_sheets = None  # a thread we stopped pursuing (RFQ: walking away would end the case)

    def c(self, case, terms):
        return total_cost(case, terms, self.std, self.sup) if terms.get("unit_price") else math.inf


class StrategicAgent:
    def __init__(self, params=None, package=None, writer=None):
        """`params`: Params or {goal: Params} (default: params.json). `writer(context) -> body`
        writes the e-mail (an LLM); without one, or when it fails, a template writes it."""
        self.params, self.package, self.writer = params or load_params(), package, writer
        self.case_id, self.threads, self.p = None, {}, Params()
        self.plan = None

    # -- setup -------------------------------------------------------------------------------------
    def _start(self, case, threads):
        self.case_id = case["case_id"]
        goal = case["buyer"].get("category_goal", "routine")
        self.p = self.params if isinstance(self.params, Params) else self.params.get(goal, Params())
        self.threads = {sid: Thread(self, case, sid, ev) for sid, ev in threads.items()}
        alt = case["buyer"].get("alternative") or {}
        self.c_alt = total_cost(case, alt["terms"]) if (alt.get("terms") or {}).get("unit_price") else math.inf
        opens = [th.c(case, th.opening_terms) for th in self.threads.values()]
        self.c_open = min([c for c in opens if math.isfinite(c)] or [math.inf])
        raw = [total_cost(case, th.opening_terms, th.std) for th in self.threads.values() if th.opening_terms.get("unit_price")]
        self.c_open_raw = min(raw or [math.inf])
        self.turn = 0

    # -- the move ----------------------------------------------------------------------------------
    def decide(self, case, threads):
        if case["case_id"] != self.case_id:
            self._start(case, threads)
        live = live_threads(threads)
        if not live:
            return {"supplier_id": next(iter(threads)), "message": {"action": {"type": "walk_away"}}}
        for sid in live:  # record what each supplier now offers
            th = self.threads[sid]
            n_replies = sum(m.get("from") != "buyer" for m in threads[sid]) - 1
            while len(th.theirs) < n_replies:
                th.theirs.append(th.c(case, standing(threads[sid])[1]))
        self.turn += 1
        # round-robin over the threads we still pursue: the one we wrote to least (RFQ threads all
        # run on the clock); a thread that has nothing left for us is parked, not walked away from
        for _ in range(len(live)):
            active = [s for s in live if not self.threads[s].parked] or live
            sid = min(active, key=lambda s: (len(self.threads[s].offers), live.index(s)))
            move = self._thread_move(case, threads, sid)
            if move.get("park") and len(active) > 1:
                self.threads[sid].parked = True
                continue
            if move.get("park"):  # the last thread: take the best sheet on the table, or walk
                return self._close(case, threads)
            return move
        return self._close(case, threads)

    def _close(self, case, threads):
        best = None
        for sid in live_threads(threads):
            ok = self._standing_ok(case, self.threads[sid], threads[sid])
            if ok and not compliance.accept_problems(case, ok[1], self.threads[sid].std, ok[3], self.c_alt, self.c_open_raw):
                best = min(best or (ok[3], sid, ok[0]), (ok[3], sid, ok[0]))
        if best:
            return {"supplier_id": best[1], "message": {"action": {"type": "accept", "term_sheet_id": best[2]}}}
        return {"supplier_id": live_threads(threads)[0], "message": {"action": {"type": "walk_away"}}}

    def _standing_ok(self, case, th, events):
        sheet_id, terms = standing(events)
        if not sheet_id or not terms.get("unit_price"):
            return None
        if not must_haves_ok(case, terms, th.std):
            return None
        return sheet_id, terms, th.c(case, terms), total_cost(case, terms, th.std)

    def _rivals_best(self, case, threads, sid):
        best = math.inf
        for other in live_threads(threads):
            if other != sid and (ok := self._standing_ok(case, self.threads[other], threads[other])):
                best = min(best, ok[3])
        return best

    def _thread_move(self, case, threads, sid):
        p, th, events = self.p, self.threads[sid], threads[sid]
        status = latest(events).get("status")
        stand = self._standing_ok(case, th, events)
        c_stand = stand[2] if stand else math.inf
        rival = self._rivals_best(case, threads, sid)
        reserve = min(self.c_open, self.c_alt, rival, c_stand)
        if not math.isfinite(reserve):
            reserve = th.c_goal * 1.1
        goal = min(th.c_goal, reserve)
        span = max(reserve - goal, 0.005 * max(goal, 1))
        t = len(th.offers)
        T = max(1, case.get("round_limit", 10) - p.reserve_rounds)
        left = moves_left(case, events)
        target = goal - p.anchor * span if t == 0 else goal + span * min(1.0, t / T) ** p.beta

        def accept():
            bad = compliance.accept_problems(case, stand[1], th.std, stand[3], self.c_alt, self.c_open_raw)
            if bad:  # never close a deal that scores 0 or loses to what we have
                log.warning("accept refused: %s", bad)
                return park
            return {"supplier_id": sid, "message": {"action": {"type": "accept", "term_sheet_id": stand[0]}}}

        park = {"supplier_id": sid, "park": True, "message": {"action": {"type": "walk_away"}}}
        acceptable = bool(stand) and stand[3] < self.c_alt and stand[3] <= rival + 0.01
        # what this move rests on, for the LLM brain (hollerau.brain) and the decision log
        self.plan = {
            "sid": sid, "status": status, "stand": stand, "c_stand": c_stand, "goal": goal, "reserve": reserve,
            "span": span, "target": target, "acceptable": acceptable and not (
                stand and compliance.accept_problems(case, stand[1], th.std, stand[3], self.c_alt, self.c_open_raw)
            ), "left": left, "t": t, "rival": rival,
        }
        if acceptable:
            stalled = t >= 3 and len(th.theirs) >= 3 and th.theirs[-3] - th.theirs[-1] < p.stall * span
            if (
                status in ("agreed", "final_offer")
                or c_stand <= target + p.accept_gap * span
                or left <= 1
                or stalled
            ):
                return accept()
        elif status in ("agreed", "final_offer") or left <= 0:
            return park  # its last word loses to our alternative or a rival: pursue nothing more here
        if left <= 0:
            return accept() if acceptable else park

        # offer: never worse for us than our last offer, always better for us than its own sheet
        if th.offers:
            target = max(target, th.offers[-1])
        if stand:
            ceiling = c_stand - 0.2 * max(c_stand - (th.offers[-1] if th.offers else goal), 0.0)
            target = min(target, ceiling)
        sheets = self._sheets(case, th, target)
        if stand and sheets and sheets == th.last_sheets and len(th.theirs) >= 2 and th.theirs[-1] >= th.theirs[-2] - 0.01:
            # we repeated ourselves and it did not move: our floor estimate is too low - concede
            # past it, half way to its standing sheet (it gives nothing without a move from us)
            target = (th.offers[-1] if th.offers else target) + 0.5 * max(c_stand - (th.offers[-1] if th.offers else target), 0)
            sheets = self._sheets(case, th, target, ignore_floor=True)
        if stand:  # a sheet that costs us more than what it already offers is pointless
            sheets = [s for s in sheets if th.c(case, s) < c_stand - 0.01]
        if not sheets:
            return accept() if acceptable else park
        th.offers.append(target)
        th.last_sheets = sheets
        self.plan.update(target=target, sheets=sheets)
        claims = self._claims(th, t)
        body = self._body(case, th, sheets, claims, status)
        return {
            "supplier_id": sid,
            "message": {
                "subject": f"Re: {case['title']}",
                "body": body,
                "term_sheets": [{"terms": s} for s in sheets],
            },
        }

    # -- term sheets -----------------------------------------------------------------------------
    def _sheets(self, case, th, target, ignore_floor=False):
        """Up to n_sheets packages at the price that costs us `target`, not far below our floor
        estimate: the best package first, then the most different trades."""
        cands = []
        for pkg in levers.packages(case, th.std):
            price = levers.price_for_cost(case, pkg, target, th.std, th.sup)
            if price is None:
                continue
            floor = levers.floor_price(case, pkg, th.sup, th.margin)
            if not ignore_floor and math.isfinite(floor) and price < floor * (1 - self.p.below_floor):
                continue  # this package cannot reach the target without insulting it
            if not levers.valid(case, pkg, price, th.std):
                continue
            slack = (price - floor) / floor if math.isfinite(floor) and floor > 0 else 0.0
            cands.append((slack, pkg, price))
        if not cands:  # nothing reaches the target above our floor: offer the floor itself
            if th.goal_pkg is None:
                return []
            cands = [(0.0, th.goal_pkg, th.goal_price)]
        cands.sort(key=lambda x: -x[0])  # most room for the supplier at our cost first
        picked = [cands[0]]
        for c in cands[1:]:
            if len(picked) >= self.p.n_sheets:
                break
            diff = min(sum(c[1][k] != q[1][k] for k in c[1]) for q in picked)
            if diff >= 1 and c[0] > -0.01:
                picked.append(c)
        out = []
        for _, pkg, price in picked:
            s = levers.sheet(case, pkg, price)
            if s not in out:
                out.append(s)
        return out

    # -- arguments and text ----------------------------------------------------------------------
    def _claims(self, th, t):
        n = self.p.claims_first if t == 0 else 1
        out = []
        for c in th.dossier.claims:
            if len(out) >= min(n, 3):
                break
            if not set(c.refs) & th.used_claims:
                out.append(c)
                th.used_claims |= set(c.refs)
        return out

    def _body(self, case, th, sheets, claims, status):
        ctx = {
            "case": case,
            "supplier": th.sid,
            "sheets": sheets,
            "standard": th.std,
            "claims": [c.sentence for c in claims],
            "dossier": th.dossier,
            "status": status,
            "round": len(th.offers),
        }
        if self.writer:
            try:
                text = self.writer(ctx)
                msg = {"body": text, "term_sheets": [{"terms": s} for s in sheets]}
                bad = [] if text else ["empty"]
                bad += [f"dropped {r}" for c in claims for r in c.refs if r not in (text or "")]
                bad += compliance.problems(
                    case, msg, self._facts(case), allowed_numbers=compliance.allowed_numbers(sheets, ctx["claims"]),
                    standard=th.std,
                )
                if not bad:
                    return text
                log.warning("writer text rejected (%s) - template", "; ".join(bad[:3]))
            except Exception as e:  # the template keeps the round
                log.warning("writer failed (%s) - template", e)
        return template(ctx)

    def _facts(self, case):
        facts = self.package.facts if self.package else {}
        return {**facts, **(case.get("facts") or {})}


def describe(sheet, standard):
    parts = [f"EUR {sheet['unit_price']:.2f} per unit"]
    labels = {
        "payment_days": "payment {} days net",
        "lead_time_days": "lead time {} days",
        "volume_per_year": "{} units a year",
        "contract_months": "{} months",
        "incoterm": "{}",
        "effective_date": "from {}",
        "ppm_commitment": "{} ppm",
        "chargeback_eur_per_complaint": "EUR {} per complaint",
        "tooling_eur": "tooling EUR {}",
    }
    for k, v in sheet.items():
        if k in labels and v is not None:
            parts.append(labels[k].format(v))
    if sheet.get("index_clause"):
        parts.append("with an index clause")
    return ", ".join(parts)


def template(ctx):
    d, sheets = ctx["dossier"], ctx["sheets"]
    lines = ["Dear colleagues,", ""]
    if ctx["round"] <= 1:
        lines.append("Thank you for your offer. We value our cooperation and want to find a fair solution.")
    else:
        lines.append("Thank you for your reply - we are moving closer.")
    lines += ctx["claims"]
    if len(sheets) == 1:
        lines.append(f"We propose: {describe(sheets[0], ctx['standard'])}.")
    else:
        lines.append("We can offer either of these packages:")
        lines += [f"Option {i + 1}: {describe(s, ctx['standard'])}." for i, s in enumerate(sheets)]
    if d.cash_short and any(s.get("payment_days", 99) < (ctx["standard"].get("payment_days") or 99) for s in sheets):
        lines.append("We are glad to pay faster if that helps your cash flow.")
    lines.append("Could you share a cost breakdown if our proposal does not work for you?")
    lines += ["", "Kind regards,", "Purchasing, Hollerau Pumpenwerke"]
    return "\n".join(lines)
