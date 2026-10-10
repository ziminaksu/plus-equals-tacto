"""Python selects full deals; Qwen interprets evidence and supplies bounded prose."""

import hashlib
import json
import math
import re
import time
from dataclasses import asdict
from types import SimpleNamespace

from arena_kit.cost import closing_terms, complete_offer, must_haves_ok, total_cost
from arena_kit.play import latest, live_threads, moves_left, standing

from .. import compliance, intel, levers
from ..agent import _opening_standard, describe
from ..params import Params
from .beliefs import Beliefs
from .router import Router
from .storage import Store

POLICY_VERSION = "bayes-v1.1"


class AnalyticalAgent:
    def __init__(self, package=None, store=None, router=None, run_id="local", risk_aversion=0.25):
        self.package = package
        self.store = store or Store()
        self.router = router or Router(enabled=False)
        self.run_id = run_id
        self.risk_aversion = risk_aversion
        self.threads = {}
        self.case_id = None
        self.session_id = None
        self.turn = 0

    def log(self, kind, payload, sid=None):
        self.store.log(self.run_id, kind, payload, self.case_id, sid, self.session_id)

    def start(self, case, threads):
        self.case_id = case["case_id"]
        self.log("case", {"case": case, "policy_version": POLICY_VERSION, "risk_aversion": self.risk_aversion})
        for sid, events in threads.items():
            _, terms = standing(events)
            std = _opening_standard(events)
            reference = closing_terms(case, terms, std)
            # If no price is stated, use current/fallback as a labelled prior, not a supplier quote.
            reference["unit_price"] = (
                reference.get("unit_price")
                or case["buyer"].get("current_unit_price")
                or case["buyer"]["fallback_unit_price"]
            )
            dossier = intel.build(case, sid, self.package, reference["unit_price"])
            sup = intel.estimate(case, dossier, {**reference, **std}, reference["unit_price"], Params())
            seed = int(hashlib.sha256(sid.encode()).hexdigest()[:8], 16)
            beliefs = Beliefs(
                case, reference, sup, seed=seed,
                signals={
                    "cash_short": dossier.cash_short,
                    "spare_capacity": dossier.spare_capacity,
                    "approval_ladder": dossier.approval_ladder,
                    "wants_partnership": dossier.wants_partnership,
                },
            )
            self.threads[sid] = SimpleNamespace(
                std=std,
                reference=reference,
                dossier=dossier,
                sup=sup,
                beliefs=beliefs,
                pending=None,
                used=set(),
                repeats=0,
                last_price=None,
                last_terms=None,
            )
            self.log("evidence", asdict(dossier), sid)
            self.log("coefficients", beliefs.snapshot(), sid)

    def observe(self, case, threads):
        for sid, events in threads.items():
            th = self.threads[sid]
            pending = th.pending
            if not pending or len(events) <= pending["event_count"]:
                continue
            reply = latest(events)
            offered = standing(events)[1]
            status = reply.get("status")
            outcome = "accept" if status == "agreed" else "walk" if status in ("walked_away", "no_bid") else "counter"
            event_id = hashlib.sha256(json.dumps(reply, sort_keys=True, default=str).encode()).hexdigest()
            if th.beliefs.update(event_id, [pending["terms"]], outcome, pending["quote"], pending["repeats"]):
                observed = [float(outcome == x) for x in ("accept", "counter", "walk")]
                pred = pending["probabilities"]
                self.log(
                    "observation",
                    {
                        "response": reply,
                        "outcome": outcome,
                        "prediction": pred,
                        "brier": sum(
                            (pred[x] - o) ** 2 for x, o in zip(("accept", "counter", "walk"), observed, strict=True)
                        ),
                    },
                    sid,
                )
                if case.get("type") == "capacity" and offered.get("volume_per_year"):
                    th.beliefs.capacity_reference = offered["volume_per_year"]
                self.log("coefficients", th.beliefs.snapshot(), sid)
            th.pending = None

    def cost_samples(self, case, th, terms):
        return [total_cost(case, terms, th.std, {**th.sup, "full_cost": p.full_cost}) for p in th.beliefs.particles]

    def weighted(self, th, values):
        return sum(p.weight * v for p, v in zip(th.beliefs.particles, values, strict=True))

    def valid(self, case, th, terms):
        if (
            not isinstance(terms.get("unit_price"), (int, float))
            or not math.isfinite(terms["unit_price"])
            or terms["unit_price"] <= 0
        ):
            return False
        if not must_haves_ok(case, terms, th.std):
            return False
        for field, value in terms.items():
            options = case.get("term_options", {}).get(field)
            if field != "unit_price" and options and value not in options and value != th.std.get(field):
                return False
        return True

    def alternatives(self, case):
        alt = case["buyer"].get("alternative") or {}
        terms = alt.get("terms") or {}
        if terms.get("unit_price") and must_haves_ok(case, terms):
            return total_cost(case, terms)
        # Forecast cost of uncovered demand is a risk proxy, NOT an assertion of a feasible alternative.
        b = case["buyer"]
        return (
            b["need_per_year"]
            * b["horizon_years"]
            * b["fallback_unit_price"]
            * (1 + b.get("fallback_risk_pct", 0) / 100)
        )

    def candidates(self, case, th, current):
        # Cover each one-lever change first so the 600-package limit cannot hide a whole lever.
        baseline = complete_offer(case, current or th.reference)
        packages = [{k: v for k, v in baseline.items() if k != "unit_price"}]
        for field in levers.lever_fields(case):
            for value in levers.field_options(case, field, th.std):
                packages.append({**packages[0], field: value})
        all_packages = levers.packages(case, th.std)
        if all_packages:
            packages.extend(all_packages)
        quote = (current or {}).get("unit_price") or th.reference["unit_price"]
        candidates = []
        seen = set()
        for pkg in packages:
            for gap in (0, 0.02, 0.05, 0.08):
                terms = complete_offer(case, {**pkg, "unit_price": round(quote * (1 - gap), 2)})
                key = json.dumps(terms, sort_keys=True)
                if key in seen or not self.valid(case, th, terms):
                    continue
                # Do not respond to a refusal with a worse economic offer unless another
                # term compensates the supplier. This is checked on the full package.
                previous = th.last_terms
                if (
                    previous
                    and self.weighted(
                        th, [th.beliefs.value(terms, p) - th.beliefs.value(previous, p) for p in th.beliefs.particles]
                    )
                    < -0.01
                ):
                    continue
                seen.add(key)
                candidates.append(terms)
        # Cap scenario evaluations using the central full-deal cost, retaining trade diversity.
        candidates.sort(key=lambda t: total_cost(case, t, th.std, th.sup))
        # Pure lowest-cost truncation discards supplier-feasible trades and full coverage.
        # Retain a diverse Pareto-like shortlist: buyer cost, supplier value and
        # sufficiently covered long-term contracts.
        by_supplier = sorted(
            candidates,
            key=lambda t: -self.weighted(
                th, [th.beliefs.value(t, p) for p in th.beliefs.particles]
            ),
        )
        need = case["buyer"]["need_per_year"] * case["buyer"]["horizon_years"]
        def coverage(t):
            closed = closing_terms(case, t, th.std)
            years = min(
                closed["contract_months"] / 12 if closed["contract_months"] else 1,
                case["buyer"]["horizon_years"],
            )
            return min(closed["volume_per_year"], case["buyer"]["need_per_year"]) * years
        by_coverage = sorted(candidates, key=lambda t: (-coverage(t), total_cost(case, t, th.std, th.sup)))
        shortlist = []
        seen_shortlist = set()
        for group, limit in ((candidates, 32), (by_supplier, 16), (by_coverage, 16)):
            for candidate in group[:limit]:
                key = json.dumps(candidate, sort_keys=True)
                if key not in seen_shortlist:
                    seen_shortlist.add(key)
                    shortlist.append(candidate)
        return shortlist[:64]

    def rank(self, case, th, current, continuation, fallback):
        quote = current.get("unit_price") or th.reference["unit_price"]
        rows = []
        for terms in self.candidates(case, th, current):
            costs = self.cost_samples(case, th, terms)
            probabilities = {"accept": 0.0, "counter": 0.0, "walk": 0.0}
            values = []
            repeats = th.repeats if terms["unit_price"] == th.last_price else 0
            for p, cost in zip(th.beliefs.particles, costs, strict=True):
                probs = th.beliefs.probabilities(terms, p, quote, repeats)
                for key in probs:
                    probabilities[key] += p.weight * probs[key]
                values.append(probs["accept"] * cost + probs["counter"] * continuation + probs["walk"] * fallback)
            mean = self.weighted(th, values)
            sd = math.sqrt(self.weighted(th, [(x - mean) ** 2 for x in values]))
            rows.append(
                {
                    "terms": terms,
                    "expected_cost": mean,
                    "uncertainty": sd,
                    "objective": mean + self.risk_aversion * sd,
                    "deal_cost": self.weighted(th, costs),
                    "probabilities": probabilities,
                    "scenario_costs": values,
                    "pressure": max(0, (quote - terms["unit_price"]) / quote),
                }
            )
        return sorted(rows, key=lambda r: r["objective"])

    def decide(self, case, threads):
        started = time.monotonic()
        deadline = started + 40
        if self.case_id != case["case_id"]:
            self.start(case, threads)
        self.turn += 1
        self.observe(case, threads)
        live = live_threads(threads)
        if not live:
            return {"supplier_id": next(iter(threads)), "message": {"action": {"type": "walk_away"}}}
        fallback = self.alternatives(case)
        available = []
        for sid in live:
            th = self.threads[sid]
            offer_id, terms = standing(threads[sid])
            if offer_id and self.valid(case, th, terms):
                costs = self.cost_samples(case, th, terms)
                c = self.weighted(th, costs)
                # Do not accept worse than a feasible alternative or the opening under same estimate.
                opening = self.weighted(th, self.cost_samples(case, th, th.reference))
                if c <= min(opening, fallback) + 0.01:
                    available.append((c, sid, offer_id, terms))
        best = min(available, key=lambda x: x[0]) if available else None
        # Prefer economically viable, compliant suppliers; contact count is only a tie-break.
        # The buyer's standards outrank the raw number of contacted suppliers.
        def supplier_priority(s):
            thread = self.threads[s]
            offer_id, sheet = standing(threads[s])
            valid = bool(offer_id and self.valid(case, thread, sheet))
            cost = (
                self.weighted(thread, self.cost_samples(case, thread, sheet))
                if valid else math.inf
            )
            contacts = sum(m.get("from") == "buyer" for m in threads[s])
            return (not valid, cost, contacts)
        sid = min(live, key=supplier_priority)
        th = self.threads[sid]
        events = threads[sid]
        current = standing(events)[1]
        left = moves_left(case, events)
        status = latest(events).get("status")
        terminal = status in ("agreed", "final_offer") or left <= 1
        if terminal and best:
            return self.accept(best, "closing status or remaining-round limit")
        if terminal:
            # One thread reaching its limit must not end a multi-supplier RFQ while
            # another thread can still negotiate. Switch to an eligible rival.
            remaining = [s for s in live if s != sid and moves_left(case, threads[s]) > 1
                         and latest(threads[s]).get("status") not in ("agreed", "final_offer")]
            if remaining:
                sid = min(remaining, key=supplier_priority)
                th, events = self.threads[sid], threads[sid]
                current = standing(events)[1]
            else:
                decision = {"supplier_id": sid, "message": {"action": {"type": "walk_away"}}}
                self.log("decision", {"action": decision, "reason": "no valid acceptable standing deal"}, sid)
                return decision
        continuation = min(best[0] if best else fallback, fallback)
        ranked = self.rank(case, th, current, continuation, fallback)
        if not ranked:
            if best:
                return self.accept(best, "no improving feasible candidates")
            decision = {"supplier_id": sid, "message": {"action": {"type": "walk_away"}}}
            self.log("decision", {"action": decision, "reason": "no feasible candidate"}, sid)
            return decision
        chosen = ranked[0]
        if best and chosen["objective"] >= best[0] - 0.01:
            return self.accept(best, "available deal dominates estimated continuation")
        reasons = []
        if len(ranked) > 1:
            winners = {
                min(range(min(4, len(ranked))), key=lambda j: ranked[j]["scenario_costs"][i])
                for i in range(len(th.beliefs.particles))
            }
            if len(winners) > 1:
                reasons.append("preferred candidate changes across plausible supplier scenarios")
        if latest(events).get("missing_fields"):
            reasons.append("supplier quote omits decision-relevant terms")
        if any(x.get("result") == "contradicted" for x in latest(events).get("claim_results", [])):
            reasons.append("supplier claim feedback contradicts a prior claim")
        sources = {
            f"reply:{i}": m.get("body", "")[:1800] for i, m in enumerate(events[-4:]) if m.get("from") != "buyer"
        }
        for i, note in enumerate(th.dossier.notes[-6:]):
            sources[f"note:{i}"] = note
        analysis = self.router.analyse(sources, reasons, deadline) if self.router.enabled else {"fallback": True}
        self.log("analysis", {"sources": sources, "reasons": reasons, "result": analysis}, sid)
        claims = [c for c in th.dossier.claims if not set(c.refs) & th.used][:2]
        facts = {**(self.package.facts if self.package else {}), **case.get("facts", {})}
        claims = [c for c in claims if all(r in facts for r in c.refs)]
        intro = "Thank you for your proposal. We would like to find terms that work for both sides."
        question = (
            "Which of payment timing, contract duration or delivery flexibility would help you improve these terms?"
        )
        try:
            prose = self.router.prose({"analysis": analysis, "tone": "firm and respectful"}, deadline)
            a, b = prose.get("intro", ""), prose.get("question", "")
            # Keep model text separate from binding numbers and evidence. No unsupported figures/IDs.
            if (
                not isinstance(a, str)
                or not isinstance(b, str)
                or len(a) + len(b) > 700
                or re.search(r"\d", a + b)
                or compliance.ID_RE.search(a + b)
            ):
                raise ValueError("invalid writer fields")
            bad = compliance.problems(case, {"body": a + " " + b}, facts)
            if bad or not a.strip():
                raise ValueError("unsafe prose")
            intro, question = a, b
        except Exception:
            pass
        terms = chosen["terms"]
        body = "\n\n".join(
            [
                "Dear colleagues,",
                intro,
                *[c.sentence for c in claims],
                "We propose: " + describe(terms, th.std) + ".",
                question,
                "Kind regards, Purchasing, Hollerau Pumpenwerke",
            ]
        )
        message = {"subject": "Re: " + case["title"], "body": body, "term_sheets": [{"terms": terms}]}
        bad = compliance.problems(case, message, facts, standard=th.std)
        if bad:
            # Deterministic prose and no claims; preserve validated binding terms.
            message["body"] = (
                "Thank you for your offer. Please consider the attached term sheet. "
                "Which term would you like to discuss?"
            )
            claims = []
        if not self.valid(case, th, terms) or compliance.problems(case, message, facts, standard=th.std):
            raise ValueError("outgoing message failed validation")
        for c in claims:
            th.used.update(c.refs)
        th.repeats = th.repeats + 1 if terms["unit_price"] == th.last_price else 0
        th.last_price = terms["unit_price"]
        th.last_terms = terms
        th.pending = {
            "terms": terms,
            "quote": current.get("unit_price") or th.reference["unit_price"],
            "repeats": th.repeats,
            "event_count": len(events),
            "probabilities": chosen["probabilities"],
        }
        decision = {"supplier_id": sid, "message": message}
        self.log(
            "decision",
            {
                "policy": POLICY_VERSION,
                "chosen": chosen,
                "candidates": ranked,
                "fallback_cost": fallback,
                "buyer_dependence_eur": fallback - (best[0] if best else continuation),
                "action": decision,
                "seconds": time.monotonic() - started,
                "llm_calls": self.router.calls,
            },
            sid,
        )
        self.router.calls = []
        return decision

    def accept(self, best, reason):
        decision = {"supplier_id": best[1], "message": {"action": {"type": "accept", "term_sheet_id": best[2]}}}
        self.log("decision", {"action": decision, "reason": reason, "estimated_cost": best[0]}, best[1])
        return decision
