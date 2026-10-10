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

POLICY_VERSION = "bayes-v2.5-index-evidence"


class AnalyticalAgent:
    def __init__(self, package=None, store=None, router=None, run_id="local", risk_aversion=None, price_pressure=0.0, continuation_credit=0.0):
        self.package = package
        self.store = store or Store()
        self.router = router or Router(enabled=False)
        self.run_id = run_id
        self.risk_aversion = risk_aversion
        if not math.isfinite(price_pressure) or not 0 <= price_pressure <= 0.4:
            raise ValueError("price_pressure must be between 0 and 0.4")
        self.price_pressure = price_pressure
        if not math.isfinite(continuation_credit) or not 0 <= continuation_credit <= 0.05:
            raise ValueError("continuation_credit must be between 0 and 0.05")
        # Experimental assumption about concessions achievable in a later round.
        # Zero by default; never subtract from reported official buyer deal cost.
        self.continuation_credit = continuation_credit
        self.threads = {}
        self.case_id = None
        self.session_id = None
        self.turn = 0

    def log(self, kind, payload, sid=None):
        self.store.log(self.run_id, kind, payload, self.case_id, sid, self.session_id)

    def risk_for_case(self, case):
        """Conservative default except for quality-first cases where tail risk can overprice quality.

        The P11 audit shows the 0.25 standard-deviation surcharge ranked EUR 48.41
        above EUR 47.64 despite the latter having lower expected cost. This
        lower coefficient is a modelling choice, not an observed acceptance rate.
        """
        if self.risk_aversion is not None:
            return self.risk_aversion
        return 0.05 if case["buyer"].get("category_goal") == "quality_first" else 0.25

    def objective(self, case, expected_cost, uncertainty):
        return expected_cost + self.risk_for_case(case) * uncertainty

    def price_pressure_bonus(self, case, terms, quote):
        """Bounded ranking-only reward for seeking a lower price, not reported as savings.

        The true Arena cost is still evaluated separately by total_cost().
        This is an experimental negotiation preference, not an official score term.
        """
        if not self.price_pressure or terms["unit_price"] >= quote:
            return 0.0
        full = closing_terms(case, terms)
        months = full["contract_months"]
        years = min(months / 12 if months else 1, case["buyer"]["horizon_years"])
        committed = full["volume_per_year"] * years
        return self.price_pressure * (quote - terms["unit_price"]) * committed

    def start(self, case, threads):
        self.case_id = case["case_id"]
        self.log("case", {"case": case, "policy_version": POLICY_VERSION, "risk_aversion": self.risk_for_case(case), "price_pressure": self.price_pressure})
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
                case,
                reference,
                sup,
                seed=seed,
                signals={
                    "cash_short": dossier.cash_short,
                    "spare_capacity": dossier.spare_capacity,
                    "approval_ladder": dossier.approval_ladder,
                    "wants_partnership": dossier.wants_partnership,
                },
            )
            memory = self.store.load_learning(sid, case["buyer"].get("category_goal", "unknown"))
            beliefs.import_learning(memory)
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
                last_outcome=None,
                stagnation=0,
                last_reply_terms=None,
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
            th.last_outcome = outcome
            canonical = json.dumps([x.get("terms", {}) for x in reply.get("term_sheets", [])], sort_keys=True)
            th.stagnation = th.stagnation + 1 if canonical == th.last_reply_terms and outcome == "counter" else 0
            th.last_reply_terms = canonical
            self.store.save_learning(sid, case["buyer"].get("category_goal", "unknown"), th.beliefs.export_learning())
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

    def candidates(self, case, th, current, continuation=None, fallback=None):
        baseline = complete_offer(case, current or th.reference)
        packages = [{k: v for k, v in baseline.items() if k != "unit_price"}]
        for field in levers.lever_fields(case):
            for value in levers.field_options(case, field, th.std):
                packages.append({**packages[0], field: value})
        packages.extend(levers.packages(case, th.std))
        # Even when generic cross-product search is capped, keep explicit
        # index-protection / commitment combinations for supplier trade-offs.
        # This does not force acceptance: official buyer TCO still prices
        # indexed packages, and ranking must justify any extra cost.
        if th.beliefs.signal_counts.get("index_protection") and "index_clause" in case["negotiable"]:
            clauses = [c for c in levers.field_options(case, "index_clause", th.std) if c]
            months = (
                levers.field_options(case, "contract_months", th.std)
                if "contract_months" in case["negotiable"]
                else [packages[0].get("contract_months")]
            )
            for clause in clauses:
                for duration in months:
                    combined = {**packages[0], "index_clause": clause}
                    if "contract_months" in case["negotiable"]:
                        combined["contract_months"] = duration
                    packages.append(combined)
        quote = current.get("unit_price") or th.reference["unit_price"]
        center = SimpleNamespace(
            **{
                k: self.weighted(th, [getattr(p, k) for p in th.beliefs.particles])
                for k in ("r", "b_pay", "b_term", "b_flex", "b_quality", "b_capacity", "full_cost", "b_index")
            }
        )
        previous = th.last_terms
        previous_value = th.beliefs.value(previous, center) if previous else None
        fallback = self.alternatives(case) if fallback is None else fallback
        continuation = fallback if continuation is None else continuation
        candidates, seen = [], set()
        package_rows = {}
        for pkg in packages:
            package_key = json.dumps(pkg, sort_keys=True)
            if package_key in package_rows:
                continue
            package_rows[package_key] = []
            prices = [quote * m for m in (0.80, 0.86, 0.90, 0.94, 0.97, 0.99, 1, 1.01, 1.03, 1.06, 1.10, 1.15)]
            v0 = th.beliefs.value({**pkg, "unit_price": 0}, center)
            slope = th.beliefs.value({**pkg, "unit_price": 1}, center) - v0
            if slope > 0:
                # Add adaptive prices at the estimated reservation value, with a modest acceptance cushion.
                prices.extend((center.r - v0 + pad * th.beliefs.tau) / slope for pad in (0, 0.7, 1.4))
                if previous:
                    prices.append((previous_value + quote * 0.004 - v0) / slope)
            for price in prices:
                if not 0.5 * quote <= price <= 1.20 * quote:
                    continue
                terms = complete_offer(case, {**pkg, "unit_price": round(price, 2)})
                key = json.dumps(terms, sort_keys=True)
                if key in seen or not self.valid(case, th, terms):
                    continue
                value = th.beliefs.value(terms, center)
                # A refusal must lead to a genuine concession or a compensating package change.
                if previous and (
                    value < previous_value - 0.01
                    or (th.last_outcome == "counter" and value < previous_value + max(0.01, quote * 0.002))
                ):
                    continue
                seen.add(key)
                cost = total_cost(case, terms, th.std, th.sup)
                probs = th.beliefs.probabilities(terms, center, quote)
                surrogate = probs["accept"] * cost + probs["counter"] * continuation + probs["walk"] * fallback
                row = (terms, cost, probs["accept"], surrogate)
                candidates.append(row)
                package_rows[package_key].append(row)
        if len(candidates) <= 1200:
            return [r[0] for r in candidates]
        # Preselection is needed only for very large grids. Preserve the strongest central
        # expected-value options, plus cheap and high-acceptance alternatives for uncertainty.
        chosen = sorted(candidates, key=lambda r: r[3])[:600]
        chosen.extend(sorted(candidates, key=lambda r: r[1])[:150])
        chosen.extend(sorted(candidates, key=lambda r: -r[2])[:150])
        representatives = [min(rows, key=lambda r: r[3]) for rows in package_rows.values() if rows]
        if len(representatives) > 300:
            representatives = [representatives[round(i * (len(representatives) - 1) / 299)] for i in range(300)]

        def coverage(row):
            terms = closing_terms(case, row[0], th.std)
            years = min(
                terms["contract_months"] / 12 if terms["contract_months"] else 1, case["buyer"]["horizon_years"]
            )
            return min(terms["volume_per_year"], case["buyer"]["need_per_year"]) * years

        chosen.extend(sorted(candidates, key=lambda r: (-coverage(r), r[1]))[:150])
        chosen.extend(representatives[:150])
        unique = {json.dumps(r[0], sort_keys=True): r[0] for r in chosen}
        return list(unique.values())

    def available(self, case, threads, fallback, include_indicative=False):
        available = []
        for sid in live_threads(threads):
            th = self.threads[sid]
            opening = (
                self.weighted(th, self.cost_samples(case, th, th.reference))
                if self.valid(case, th, th.reference)
                else fallback
            )
            sheets = latest(threads[sid]).get("term_sheets", [])
            # Secondary sheets can be indicative alternatives, not API-acceptable standing IDs.
            # The message API puts the standing sheet first; a refreshed thread may identify it explicitly.
            active_id = latest(threads[sid]).get("standing_offer_id") or (
                sheets[0]["term_sheet_id"] if sheets else None
            )
            for sheet in sheets:
                if not include_indicative and sheet["term_sheet_id"] != active_id:
                    continue
                terms = sheet["terms"]
                if self.valid(case, th, terms):
                    cost = self.weighted(th, self.cost_samples(case, th, terms))
                    if cost <= min(opening, fallback) + 0.01:
                        available.append((cost, sid, sheet["term_sheet_id"], terms))
        return sorted(available, key=lambda r: r[0])

    def interpret(self, case, sid, events, deadline):
        th = self.threads[sid]
        sources = {}
        for index, event in enumerate(events):
            if event.get("from") != "buyer" and (index == 0 or index >= len(events) - 4):
                ref = event.get("message_id") or str(index)
                sources[f"reply:{ref}"] = event.get("body", "")[:2500]
                for j, att in enumerate(event.get("attachments", [])):
                    if att.get("text"):
                        sources[f"attachment:{ref}:{j}"] = att["text"][:1800]
        for index, note in enumerate(th.dossier.notes[-6:]):
            sources[f"note:{index}"] = note
        if self.router.enabled:
            analysis = self.router.analyse(sources, [], deadline, case["negotiable"], allow_escalation=False)
        else:
            analysis = {"fallback": True, "signals": [], "interpretations": []}
        applied = th.beliefs.apply_evidence(analysis.get("signals", []))
        self.log("analysis", {"sources": sources, "result": analysis, "applied_signals": applied}, sid)
        return analysis, sources

    def rank(self, case, th, current, continuation, fallback):
        quote = current.get("unit_price") or th.reference["unit_price"]
        rows = []
        for terms in self.candidates(case, th, current, continuation, fallback):
            costs = self.cost_samples(case, th, terms)
            probabilities = {"accept": 0.0, "counter": 0.0, "walk": 0.0}
            values = []
            repeats = th.repeats if terms["unit_price"] == th.last_price else 0
            for p, cost in zip(th.beliefs.particles, costs, strict=True):
                probs = th.beliefs.probabilities(terms, p, quote, repeats)
                for key in probs:
                    probabilities[key] += p.weight * probs[key]
                values.append(
                    probs["accept"] * cost
                    + probs["counter"] * (continuation + fallback * 0.0005 * (1 + th.stagnation))
                    + probs["walk"] * fallback
                )
            mean = self.weighted(th, values)
            sd = math.sqrt(self.weighted(th, [(x - mean) ** 2 for x in values]))
            rows.append(
                {
                    "terms": terms,
                    "expected_cost": mean,
                    "uncertainty": sd,
                    "objective": self.objective(case, mean, sd) - self.price_pressure_bonus(case, terms, quote),
                    "price_pressure_bonus": self.price_pressure_bonus(case, terms, quote),
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
        available = self.available(case, threads, fallback)
        best = available[0] if available else None
        actionable = [
            sid
            for sid in live
            if latest(threads[sid]).get("status") not in ("agreed", "final_offer")
            and moves_left(case, threads[sid]) > 1
        ]
        if not actionable:
            if best:
                return self.accept(best, "all threads closing; best valid package across suppliers")
            decision = {"supplier_id": live[0], "message": {"action": {"type": "walk_away"}}}
            self.log("decision", {"action": decision, "reason": "no valid acceptable standing deal"})
            return decision

        def supplier_priority(sid):
            thread = self.threads[sid]
            offer_id, sheet = standing(threads[sid])
            valid = bool(offer_id and self.valid(case, thread, sheet))
            cost = self.weighted(thread, self.cost_samples(case, thread, sheet)) if valid else math.inf
            contacts = sum(m.get("from") == "buyer" for m in threads[sid])
            return (not valid, cost, thread.stagnation, contacts)

        sid = min(actionable, key=supplier_priority)
        th, events = self.threads[sid], threads[sid]
        # Only the standing offer is executable. Indicative alternatives can
        # inform negotiation, but must not silently become the pricing baseline.
        _, current = standing(events)
        if not current:
            current = th.reference
        analysis, sources = self.interpret(case, sid, events, deadline)
        # Interpretation changes belief weights BEFORE cost scenarios and offers are evaluated.
        available = self.available(case, threads, fallback)
        best = available[0] if available else None
        continuation = best[0] if best else fallback
        if best and self.continuation_credit and moves_left(case, events) > 2:
            reference = closing_terms(case, current, th.std)
            years = min(reference["contract_months"] / 12 or 1, case["buyer"]["horizon_years"])
            committed = reference["volume_per_year"] * years
            # Bounded estimated future supplier concessions, not guaranteed savings.
            continuation = max(0, continuation - self.continuation_credit * current["unit_price"] * committed)
        ranked = self.rank(case, th, current, continuation, fallback)
        reasons = []
        if not analysis.get("fallback") and analysis.get("ambiguities") and len(ranked) > 1:
            potential_regret = max(
                ranked[0]["scenario_costs"][i] - min(r["scenario_costs"][i] for r in ranked[:6])
                for i in range(len(th.beliefs.particles))
            )
            if potential_regret > max(20, fallback * 0.005):
                reasons.append("unresolved source interpretation could materially change package ranking")
        if analysis.get("fallback") and case.get("type") == "capacity" and not best:
            reasons.append("no feasible standing capacity offer; source interpretation may change commitment trade")
        if reasons and time.monotonic() < deadline - 8:
            resolved = self.router.resolve(sources, analysis, reasons, deadline, case["negotiable"])
            applied = th.beliefs.apply_evidence(resolved.get("signals", []))
            analysis = resolved
            self.log("escalation", {"reasons": reasons, "result": resolved, "applied_signals": applied}, sid)
            available = self.available(case, threads, fallback)
            best = available[0] if available else None
            continuation = best[0] if best else fallback
            ranked = self.rank(case, th, current, continuation, fallback)
        self.log("coefficients", th.beliefs.snapshot(), sid)
        if not ranked:
            if best:
                return self.accept(best, "no improving feasible candidates")
            decision = {"supplier_id": sid, "message": {"action": {"type": "walk_away"}}}
            self.log("decision", {"action": decision, "reason": "no feasible candidate"}, sid)
            return decision
        chosen = ranked[0]
        if best and chosen["objective"] >= best[0] - max(0.01, best[0] * 0.0001):
            return self.accept(best, "available deal dominates estimated continuation")
        claims = [c for c in th.dossier.claims if not set(c.refs) & th.used][:2]
        facts = {**(self.package.facts if self.package else {}), **case.get("facts", {})}
        claims = [c for c in claims if all(r in facts for r in c.refs)]
        intro = "Thank you for your proposal. We would like to agree on a workable package."
        question = "Would the attached package address your priorities?"
        # Reuse the analyst's bounded prose instead of spending another model call per turn.
        a, b = analysis.get("intro", ""), analysis.get("question", "")
        if (
            isinstance(a, str)
            and isinstance(b, str)
            and a.strip()
            and len(a) + len(b) <= 700
            and not re.search(r"\d", a + b)
            and not compliance.ID_RE.search(a + b)
            and not compliance.problems(case, {"body": a + " " + b}, facts)
        ):
            intro, question = a, b
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
        self.log(
            "decision",
            {"action": decision, "reason": reason, "estimated_cost": best[0], "llm_calls": self.router.calls},
            best[1],
        )
        self.router.calls = []
        return decision
