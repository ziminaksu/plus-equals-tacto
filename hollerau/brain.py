"""BrainAgent: the LLM (GPT-6, or Qwen when QWEN_API_KEY is set) runs the negotiation.

Every move, code prepares a MENU - each option with its exact cost C for us, what it leaves the
supplier, and the arguments that will check out - and the model chooses: accept, which offer, which
arguments, and writes the e-mail; it also says why (logged for the replay walk-through). Code then
checks the choice against the rules (must-haves, alternative, 3 arguments, known IDs, no figures of
its own, no leaks). Anything off, a timeout or an error -> the code's own move (StrategicAgent), so
a round is never lost.

    MENU = {accept?} + offers {hold, step (the code's plan), big step, trades} + {walk/park?}
"""

import json
import logging
import math
import re
import time
from pathlib import Path

from arena_kit.play import latest

from . import compliance
from .agent import StrategicAgent, describe, template

log = logging.getLogger("arena")
LOG_DIR = Path(__file__).with_name("logs")

SYSTEM = """You are the lead buyer of Hollerau Pumpenwerke (German pump maker) negotiating by e-mail
with an industrial supplier. Your score: the lower our total cost C of the deal, the better; a deal
that breaks a must-have, or costs more than our alternative, scores zero. Code computed every
number for you - never invent one.

Each turn you get the case, the supplier's dossier (notes, letters, signals), the thread so far and
a MENU of moves with their exact C. Choose like an experienced buyer:
- Read the supplier: short of cash -> it values faster payment; capacity idle -> volume; stale
  costing -> index data disarms it; family/partnership -> respect and fairness; approval ladder ->
  small steps. In stabilise / secure_supply cases do not squeeze its margin below sustainable.
- Do not take the first offer. Concede in small steps and only against a move from the supplier.
  status final_offer means: push further and it may walk. "agreed" means it accepts our terms.
- Use at most 3 arguments per e-mail, spend strong ones when they matter, never repeat one.
- Never reveal urgency, a budget, or that we lack alternatives. Polite, factual, no threats.

Reply with ONE JSON object only:
{"move": "<menu key>",               e.g. "accept", "offer_step", "offer_hold", "offer_big", "trade_1", "park"
 "claims": ["<claim key>", ...],     0-3 keys from CLAIMS (only with an offer)
 "body": "<the e-mail, max 140 words, ends 'Kind regards, Purchasing, Hollerau Pumpenwerke'>",
 "why": "<one or two sentences: why this move now>"}
In the body: state the option(s) of your move exactly as given, keep each chosen claim sentence's
data IDs and figures exactly, add no other numbers or IDs."""


class BrainAgent(StrategicAgent):
    def __init__(self, params=None, package=None, complete=None, log_name=None):
        super().__init__(params, package, writer=None)
        self.complete = complete
        self.log_path = LOG_DIR / (log_name or f"decisions-{time.strftime('%Y%m%d')}.jsonl")

    def decide(self, case, threads):
        snap = self._snapshot()
        move = super().decide(case, threads)  # the code's move: also the fallback
        plan = self.plan
        if not self.complete or not plan or plan["sid"] != move["supplier_id"] or move.get("park"):
            return self._strip(move)
        try:
            t0 = time.monotonic()
            menu, claims = self._menu(case, threads, plan, snap)
            if len(menu) <= 1:
                return self._strip(move)
            user = self._prompt(case, threads, plan, menu, claims)
            raw = self.complete(SYSTEM, user)
            choice = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            out, why = self._apply(case, plan, menu, claims, choice, snap)
            self._log(case, plan, menu, choice, out is not None, time.monotonic() - t0)
            if out is not None:
                return out
            log.warning("brain choice rejected (%s) - code move", why)
        except Exception as e:  # timeout, bad JSON, anything: the code's move keeps the round
            log.warning("brain failed (%s) - code move", e)
        return self._strip(move)

    # -- state ---------------------------------------------------------------------------------
    def _snapshot(self):
        return {sid: (len(th.offers), set(th.used_claims), th.last_sheets) for sid, th in self.threads.items()}

    def _restore(self, sid, snap):
        th = self.threads[sid]
        n, used, last = snap.get(sid, (len(th.offers), set(th.used_claims), th.last_sheets))
        del th.offers[n:]
        th.used_claims, th.last_sheets = set(used), last

    @staticmethod
    def _strip(move):
        return {k: v for k, v in move.items() if k != "park"}

    # -- the menu --------------------------------------------------------------------------------
    def _menu(self, case, threads, plan, snap):
        sid, th = plan["sid"], self.threads[plan["sid"]]
        menu = {}
        stand = plan["stand"]
        if stand and plan["acceptable"]:
            menu["accept"] = {"what": f"accept its standing sheet {stand[0]}: {describe(stand[1], th.std)}",
                              "C": round(stand[2])}
        if plan["left"] > 0 and plan["status"] != "agreed":
            n_before = snap.get(sid, (len(th.offers),))[0]
            last = th.offers[n_before - 1] if n_before else None
            c_stand = plan["c_stand"]
            base = plan.get("target", plan["target"])
            levels = {"offer_step": base}
            if last is not None:
                levels["offer_hold"] = last
            if math.isfinite(c_stand):
                levels["offer_big"] = base + 0.5 * max(c_stand - base, 0)
            for key, tgt in levels.items():
                sheets = self._sheets(case, th, tgt, ignore_floor=(key == "offer_big"))
                if math.isfinite(c_stand):
                    sheets = [s for s in sheets if th.c(case, s) < c_stand - 0.01]
                if sheets:
                    menu[key] = {"sheets": sheets, "C_each": [round(th.c(case, s)) for s in sheets],
                                 "what": " | ".join(describe(s, th.std) for s in sheets)}
            # single-lever trades at the step's cost: show the supplier other ways to the same C
            seen = [m["sheets"] for m in menu.values() if "sheets" in m]
            flat = [s for ss in seen for s in ss]
            k = 1
            for s in self._sheets(case, th, base)[1:] + self._trade_sheets(case, th, base):
                if s not in flat and k <= 2 and (not math.isfinite(c_stand) or th.c(case, s) < c_stand - 0.01):
                    menu[f"trade_{k}"] = {"sheets": [s], "C_each": [round(th.c(case, s))], "what": describe(s, th.std)}
                    flat.append(s)
                    k += 1
        if not plan["acceptable"] and plan["status"] in ("final_offer", "agreed"):
            menu["park"] = {"what": "stop pursuing this supplier (its last word loses to our alternative/rival)"}
        claims = {f"c{i}": c for i, c in enumerate(th.dossier.claims) if not set(c.refs) & th.used_claims}
        claims = dict(list(claims.items())[:6])
        return menu, claims

    def _trade_sheets(self, case, th, target):
        from . import levers

        out = []
        for pkg in levers.packages(case, th.std)[:60]:
            price = levers.price_for_cost(case, pkg, target, th.std, th.sup)
            if price:
                out.append(levers.sheet(case, pkg, price))
        return out

    def _prompt(self, case, threads, plan, menu, claims):
        sid, th = plan["sid"], self.threads[plan["sid"]]
        events = threads[sid]
        b = case["buyer"]
        recent = []
        for m in events[-6:]:
            sheets = [ts.get("terms") for ts in m.get("term_sheets") or []]
            recent.append({"from": "us" if m.get("from") == "buyer" else "supplier", "status": m.get("status"),
                           "sheets": sheets, "claim_results": m.get("claim_results"), "body": (m.get("body") or "")[:900]})
        d = th.dossier
        return json.dumps({
            "case": {"title": case["title"], "type": case["type"], "briefing": case.get("briefing", "")[:600],
                     "category_goal": b.get("category_goal"), "need_per_year": b["need_per_year"],
                     "horizon_years": b["horizon_years"], "must_haves": b.get("must_haves")},
            "numbers": {"C_best_opening": round(self.c_open_raw), "C_alternative": None if math.isinf(self.c_alt) else round(self.c_alt),
                        "C_its_standing_sheet": None if math.isinf(plan["c_stand"]) else round(plan["c_stand"]),
                        "C_goal_estimate": round(plan["goal"]), "our_messages_left": plan["left"],
                        "supplier_status": plan["status"], "best_rival_C": None if math.isinf(plan["rival"]) else round(plan["rival"])},
            "supplier_dossier": {"notes": d.notes[-6:], "short_of_cash": d.cash_short, "spare_capacity": d.spare_capacity,
                                 "stale_costing": d.stale_costing, "approval_ladder": d.approval_ladder,
                                 "wants_partnership": d.wants_partnership, "asked_increase_pct": d.asked_pct,
                                 "index_change_pct_weighted": d.index_change_pct},
            "thread": recent,
            "MENU": {k: {kk: vv for kk, vv in v.items() if kk != "sheets"} for k, v in menu.items()},
            "CLAIMS": {k: c.sentence for k, c in claims.items()},
        }, ensure_ascii=False, default=str)

    # -- check and apply the choice ------------------------------------------------------------
    def _apply(self, case, plan, menu, claims, choice, snap):
        sid, th = plan["sid"], self.threads[plan["sid"]]
        key = choice.get("move")
        if key not in menu:
            return None, f"move {key!r} not in menu"
        if key == "accept":
            stand = plan["stand"]
            if compliance.accept_problems(case, stand[1], th.std, stand[3], self.c_alt, self.c_open_raw):
                return None, "accept breaks a guard"
            self._restore(sid, snap)
            return {"supplier_id": sid, "message": {"action": {"type": "accept", "term_sheet_id": stand[0]}}}, ""
        if key == "park":
            self._restore(sid, snap)
            th.parked = True
            return None, "park: let the code pick the next thread"
        sheets = menu[key]["sheets"]
        chosen = [claims[c] for c in (choice.get("claims") or [])[:3] if c in claims]
        body = (choice.get("body") or "").strip()
        msg = {"body": body, "term_sheets": [{"terms": s} for s in sheets]}
        bad = [f"dropped {r}" for c in chosen for r in c.refs if r not in body]
        bad += compliance.problems(case, msg, self._facts(case),
                                   allowed_numbers=compliance.allowed_numbers(sheets, [c.sentence for c in chosen]),
                                   standard=th.std)
        self._restore(sid, snap)
        th.offers.append(max(th.c(case, s) for s in sheets))
        th.last_sheets = sheets
        for c in chosen:
            th.used_claims |= set(c.refs)
        if bad:  # keep the model's move and arguments, but let the template write it
            log.warning("brain text rejected (%s) - template text", "; ".join(bad[:3]))
            body = template({"case": case, "supplier": sid, "sheets": sheets, "standard": th.std,
                             "claims": [c.sentence for c in chosen], "dossier": th.dossier,
                             "status": plan["status"], "round": len(th.offers)})
        return {"supplier_id": sid, "message": {"subject": f"Re: {case['title']}", "body": body,
                                                "term_sheets": [{"terms": s} for s in sheets]}}, ""

    def _log(self, case, plan, menu, choice, used, secs):
        try:
            LOG_DIR.mkdir(exist_ok=True)
            row = {"time": time.strftime("%H:%M:%S"), "case": case["case_id"], "supplier": plan["sid"],
                   "round": plan["t"], "status": plan["status"], "menu": {k: v.get("what") for k, v in menu.items()},
                   "move": choice.get("move"), "claims": choice.get("claims"), "why": choice.get("why"),
                   "used": used, "secs": round(secs, 1)}
            with self.log_path.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass


def latest_status(events):
    return latest(events).get("status")
