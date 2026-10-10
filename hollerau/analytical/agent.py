"""Python selects full deals; Qwen interprets evidence and supplies bounded prose."""

import hashlib
import json
import math
import re
import time
from dataclasses import asdict
from types import SimpleNamespace

from arena_kit.cost import closing_terms, complete_offer, cost_breakdown, must_haves_ok, total_cost
from arena_kit.play import latest, live_threads, moves_left, standing

from .. import compliance, intel, levers
from ..agent import _opening_standard, describe
from ..params import Params
from .beliefs import Beliefs
from .offers import echoed_proposal, equivalent_alternative
from .planning import counter_costs, paired_objective
from .preferences import extract_explicit_conditions, violated
from .router import Router
from .storage import Store

POLICY_VERSION = "bayes-v4-integrated"


class AnalyticalAgent:
    def __init__(
        self,
        package=None,
        store=None,
        router=None,
        run_id="local",
        risk_aversion=None,
        lookahead=True,
        price_pressure=0.0,
        opening_probe=False,
    ):
        self.package = package
        self.store = store or Store()
        self.router = router or Router(enabled=False)
        self.run_id = run_id
        self.risk_aversion = risk_aversion
        self.lookahead = lookahead
        if not math.isfinite(price_pressure) or not 0 <= price_pressure <= 0.4:
            raise ValueError("price_pressure must be between 0 and 0.4")
        self.price_pressure = price_pressure
        # Experimental first-counteroffer safeguard. Defaults off until a separate
        # held-out evaluation shows it improves outcomes in the v4 planner.
        self.opening_probe = bool(opening_probe)
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
        self.parked = set()
        self.case_id = case["case_id"]
        self.log(
            "case",
            {
                "case": case,
                "policy_version": POLICY_VERSION,
                "risk_aversion": self.risk_for_case(case),
                "price_pressure": self.price_pressure,
                "opening_probe": self.opening_probe,
            },
        )
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
            beliefs.check_cost_consistency(reference)
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
                last_supplier_terms=dict(reference),
                critic_candidates=[],
                planning_anchor=None,
                planning_moves=case.get("round_limit", 10),
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
            proposals = pending.get("offers", [pending["terms"]])
            echoed = echoed_proposal(case, th.std, proposals, offered) if offered else None
            proposed = echoed or pending["terms"]
            if echoed:
                th.last_terms = echoed
                th.last_price = echoed["unit_price"]
            if th.beliefs.update(event_id, proposals, outcome, pending["quote"], pending["repeats"]):
                if echoed and outcome in ("accept", "counter"):
                    th.beliefs.learn_choice(event_id, echoed, proposals)
                if outcome in ("accept", "counter"):
                    th.beliefs.learn_counteroffer(event_id, th.last_supplier_terms, offered, proposed)
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
            if offered.get("unit_price"):
                th.last_supplier_terms = dict(offered)
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
        if not isinstance(terms, dict):
            return False
        for field, value in terms.items():
            if isinstance(value, (int, float)) and (isinstance(value, bool) or not math.isfinite(value)):
                return False
            if field in ("volume_per_year", "lead_time_days") and isinstance(value, (int, float)) and value <= 0:
                return False
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
                for k in (
                    "r",
                    "b_pay",
                    "b_term",
                    "b_flex",
                    "b_quality",
                    "b_capacity",
                    "full_cost",
                    "b_index",
                    "b_volume",
                )
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
                if (
                    previous
                    and th.last_outcome == "counter"
                    and any(terms.get(k) != previous.get(k) for k in terms if k != "unit_price")
                ):
                    # A package switch must be a concession in plausible supplier
                    # worlds, not just at the mean of uncertain preference weights.
                    reversal_mass = sum(
                        p.weight
                        for p in th.beliefs.particles
                        if th.beliefs.value(terms, p) < th.beliefs.value(previous, p) + max(0.01, quote * 0.002)
                    )
                    if reversal_mass > 0.1:
                        continue
                seen.add(key)
                cost = total_cost(case, terms, th.std, th.sup)
                probs = th.beliefs.probabilities(terms, center, quote)
                surrogate = probs["accept"] * cost + probs["counter"] * continuation + probs["walk"] * fallback
                row = (terms, cost, probs["accept"], surrogate)
                candidates.append(row)
                package_rows[package_key].append(row)
        if len(candidates) <= 1200:
            return [r[0] for r in candidates] + th.critic_candidates
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
        return list(unique.values()) + th.critic_candidates

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
            analysis = self.router.analyse(
                sources,
                [],
                deadline,
                case["negotiable"],
                allow_escalation=False,
                term_options=case.get("term_options", {}),
            )
        else:
            analysis = {"fallback": True, "signals": [], "interpretations": []}
        applied = th.beliefs.apply_evidence(analysis.get("signals", []))
        current = standing(events)[1] or th.reference
        conditions = extract_explicit_conditions(sources, case, current) + analysis.get("conditions", [])
        added = th.beliefs.apply_conditions(conditions)
        if standing(events)[0]:
            th.beliefs.reconcile_conditions(current)
        self.log(
            "analysis",
            {"sources": sources, "result": analysis, "applied_signals": applied, "applied_conditions": added},
            sid,
        )
        return analysis, sources

    def rank(self, case, th, current, continuation, fallback):
        quote = current.get("unit_price") or th.reference["unit_price"]
        weights = [p.weight for p in th.beliefs.particles]
        anchor = th.planning_anchor or [continuation] * len(weights)
        rows = []
        for terms in self.candidates(case, th, current, continuation, fallback):
            costs = self.cost_samples(case, th, terms)
            probs = [
                th.beliefs.probabilities(terms, p, quote, th.repeats if terms["unit_price"] == th.last_price else 0)
                for p in th.beliefs.particles
            ]
            probabilities = {
                k: sum(w * pr[k] for w, pr in zip(weights, probs, strict=True)) for k in ("accept", "counter", "walk")
            }
            values = [
                pr["accept"] * cost
                + pr["counter"] * (a + fallback * 0.0005 * (1 + th.stagnation))
                + pr["walk"] * fallback
                for pr, cost, a in zip(probs, costs, anchor, strict=True)
            ]
            objective, sd = paired_objective(values, anchor, weights, self.risk_for_case(case))
            rows.append(
                {
                    "terms": terms,
                    "expected_cost": self.weighted(th, values),
                    "uncertainty": sd,
                    "objective": objective - self.price_pressure_bonus(case, terms, quote),
                    "price_pressure_bonus": self.price_pressure_bonus(case, terms, quote),
                    "deal_cost": self.weighted(th, costs),
                    "probabilities": probabilities,
                    "scenario_costs": values,
                    "pressure": max(0, (quote - terms["unit_price"]) / quote),
                    "planning_depth": 1,
                    "_costs": costs,
                    "_probs": probs,
                }
            )
        rows.sort(key=lambda r: r["objective"])
        if self.lookahead and th.planning_moves > 2 and rows:
            center = SimpleNamespace(
                **{
                    k: self.weighted(th, [getattr(p, k) for p in th.beliefs.particles])
                    for k in asdict(th.beliefs.particles[0])
                }
            )
            # A shortlist based only on immediate acceptance discards useful opening
            # anchors. Screen every candidate against the continuation model as well.
            for row in rows:
                future = counter_costs(
                    case, th, row["terms"], current, lambda t: self.valid(case, th, t), fallback, particles=[center]
                )[0]
                pr = row["probabilities"]
                row["screen_objective"] = (
                    pr["accept"] * row["deal_cost"] + pr["counter"] * future + pr["walk"] * fallback
                )
            # Preserve good expected actions, cheap quality/coverage packages, and reliable deals.
            shortlist = rows[:12] + sorted(rows, key=lambda r: r["deal_cost"])[:6]
            shortlist += sorted(rows, key=lambda r: -r["probabilities"]["accept"])[:6]
            shortlist += sorted(rows, key=lambda r: r["screen_objective"])[:12]
            rows = list({json.dumps(r["terms"], sort_keys=True): r for r in shortlist}.values())
            for row in rows:
                future = counter_costs(case, th, row["terms"], current, lambda t: self.valid(case, th, t), fallback)
                values = [
                    pr["accept"] * cost + pr["counter"] * (future_cost + fallback * 0.0003) + pr["walk"] * fallback
                    for pr, cost, future_cost in zip(row["_probs"], row["_costs"], future, strict=True)
                ]
                objective, sd = paired_objective(values, anchor, weights, self.risk_for_case(case))
                row.update(
                    expected_cost=self.weighted(th, values),
                    objective=objective - row["price_pressure_bonus"],
                    uncertainty=sd,
                    scenario_costs=values,
                    planning_depth=min(4, max(1, th.planning_moves - 1)) + 1,
                    predicted_counter_cost=self.weighted(th, future),
                )
        for row in rows:
            row.pop("_costs")
            row.pop("_probs")
        return sorted(rows, key=lambda r: r["objective"])

    def plan_anchor(self, case, th, best, continuation, sid):
        th.planning_anchor = (
            self.cost_samples(case, th, best[3])
            if best and best[1] == sid
            else [continuation] * len(th.beliefs.particles)
        )

    def initial_counteroffer(self, case, threads, sid, th, best, ranked):
        """Select a bounded first counter when taking the opening scores zero.

        Only the untouched executable first quote of the same supplier qualifies.
        No hidden supplier data or outcome score enters this decision. Failing
        safely returns None, preserving the existing v4 planner's acceptance.
        """
        if (
            not self.opening_probe
            or not best
            or best[1] != sid
            or th.last_terms is not None
            or th.planning_moves < 3
            or any(m.get("from") == "buyer" for events in threads.values() for m in events)
        ):
            return None
        opening = closing_terms(case, best[3], th.std)
        if opening != th.reference or not opening.get("unit_price"):
            return None
        opening_price = opening["unit_price"]
        # Model uncertainty cannot make the *official* buyer TCO saving
        # disappear. Use the same scoring cost function, excluding the
        # speculative supplier relationship estimate for this opportunity gate.
        open_cost = total_cost(case, best[3], th.std)
        minimum_saving = max(0.01, open_cost * 0.002)
        choices = []
        for row in ranked:
            terms = row["terms"]
            probs = row["probabilities"]
            proposed = closing_terms(case, terms, th.std)
            if (
                not (0.94 * opening_price <= proposed["unit_price"] <= 0.995 * opening_price)
                or probs["accept"] < 0.15
                or probs["walk"] > 0.05
                or not self.valid(case, th, terms)
                or any(violated(proposed, c) for c in th.beliefs.conditions)
            ):
                continue
            saving = open_cost - total_cost(case, terms, th.std)
            if saving >= minimum_saving:
                # Arena scores an untouched-opening acceptance at zero.
                # A positive-probability, cost-improving counter is therefore
                # worth considering, but its deal remains uncertain.
                choices.append((saving * probs["accept"], saving, row))
        if not choices:
            self.log(
                "opening_probe",
                {"selected": False, "reason": "no bounded, positive-saving first counter",
                 "opening_cost": open_cost, "candidate_count": len(ranked)},
                sid,
            )
            return None
        _, saving, chosen = max(choices, key=lambda item: (item[0], item[1]))
        self.log(
            "opening_probe",
            {"selected": True, "opening_cost": open_cost, "estimated_saving": saving,
             "accept_probability": chosen["probabilities"]["accept"],
             "walk_probability": chosen["probabilities"]["walk"],
             "terms": chosen["terms"]},
            sid,
        )
        return chosen

    def review_plan(self, case, sid, th, sources, ranked, best, current, fallback, deadline):
        if (
            not ranked
            or not getattr(self.router, "review_enabled", self.router.enabled)
            or not hasattr(self.router, "review")
        ):
            return ranked, best
        chosen = ranked[0]
        accepting = best and chosen["objective"] >= best[0] - max(0.01, best[0] * 0.0001)
        conditional = any(violated(closing_terms(case, chosen["terms"], th.std), c) for c in th.beliefs.conditions)
        expensive = chosen["deal_cost"] > self.weighted(th, self.cost_samples(case, th, current)) * 1.005
        # A quality opening also merits review: it can hand away quality cheaply before learning.
        if not (
            (accepting and th.last_terms is None)
            or conditional
            or expensive
            or ("ppm_commitment" in case["negotiable"] and th.last_terms is None)
        ):
            return ranked, best
        if deadline - time.monotonic() < 8:
            return ranked, best
        # At most one large-model call per turn, including a preceding ambiguity escalation.
        large_models = {getattr(self.router, "large", None), getattr(self.router, "review_model", None)}
        if any(c.get("model") in large_models for c in self.router.calls):
            return ranked, best
        packages = [
            {
                "terms": r["terms"],
                "cost_eur": r["deal_cost"],
                "cost_breakdown_at_point_estimate": cost_breakdown(case, r["terms"], th.std, th.sup),
                "probabilities": r["probabilities"],
                "objective": r["objective"],
            }
            for r in ranked[:6]
        ]
        public_case = {k: case.get(k) for k in ("negotiable", "term_options", "fixed_terms", "buyer")}
        # No first-model rationale is passed to the independent critic.
        review = self.router.review(
            sources,
            public_case,
            {
                "action": "accept" if accepting else "counter",
                "packages": packages,
                "standing": {"terms": best[3], "cost_eur": best[0]} if best else None,
                "remaining_moves": th.planning_moves,
                "beliefs": th.beliefs.summary(),
            },
            deadline,
        )
        added = th.beliefs.apply_conditions(review.get("conditions", []))
        approved = []
        for terms in review.get("alternative_terms", []):
            if set(terms) == set(case["negotiable"]) and self.valid(case, th, terms):
                # Critics cannot introduce an unbounded price jump or reverse a genuine concession.
                price = current.get("unit_price") or th.reference["unit_price"]
                delta = (
                    self.weighted(
                        th,
                        [th.beliefs.value(terms, p) - th.beliefs.value(th.last_terms, p) for p in th.beliefs.particles],
                    )
                    if th.last_terms
                    else 1
                )
                if 0.5 * price <= terms["unit_price"] <= 1.2 * price and delta >= 0.01:
                    approved.append(terms)
        th.critic_candidates = approved
        self.log("critic", {"result": review, "approved_candidates": approved, "applied_conditions": added}, sid)
        if (added or approved) and deadline - time.monotonic() > 3:
            continuation = best[0] if best else fallback
            ranked = self.rank(case, th, current, continuation, fallback)
        return ranked, best

    def decide(self, case, threads):
        started = time.monotonic()
        deadline = started + 40
        if self.case_id != case["case_id"]:
            self.start(case, threads)
        self.turn += 1
        self.observe(case, threads)
        return self._decide(case, threads, started, deadline)

    def _decide(self, case, threads, started, deadline):
        live = live_threads(threads)
        if not live:
            return {"supplier_id": next(iter(threads)), "message": {"action": {"type": "walk_away"}}}
        fallback = self.alternatives(case)
        available = self.available(case, threads, fallback)
        best = available[0] if available else None
        actionable = [
            sid
            for sid in live
            if sid not in self.parked
            and latest(threads[sid]).get("status") not in ("agreed", "final_offer")
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
            # Each supplier gets a chance to improve before we select the winner.
            return (contacts, not valid, cost, thread.stagnation)

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
        # Losing this thread does not lose independent executable rival quotes.
        # Use the real backup when pricing exploration risk in an RFQ.
        negotiation_fallback = min([fallback] + [a[0] for a in available if a[1] != sid])
        th.planning_moves = moves_left(case, events)
        self.plan_anchor(case, th, best, continuation, sid)
        ranked = self.rank(case, th, current, continuation, negotiation_fallback)
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
            resolved = self.router.resolve(
                sources, analysis, reasons, deadline, case["negotiable"], case.get("term_options", {})
            )
            applied = th.beliefs.apply_evidence(resolved.get("signals", []))
            th.beliefs.apply_conditions(resolved.get("conditions", []))
            analysis = resolved
            self.log("escalation", {"reasons": reasons, "result": resolved, "applied_signals": applied}, sid)
            available = self.available(case, threads, fallback)
            best = available[0] if available else None
            continuation = best[0] if best else fallback
            negotiation_fallback = min([fallback] + [a[0] for a in available if a[1] != sid])
            self.plan_anchor(case, th, best, continuation, sid)
            ranked = self.rank(case, th, current, continuation, negotiation_fallback)
        ranked, best = self.review_plan(case, sid, th, sources, ranked, best, current, negotiation_fallback, deadline)
        self.log("coefficients", th.beliefs.snapshot(), sid)
        if not ranked:
            if best:
                return self.accept(best, "no improving feasible candidates")
            decision = {"supplier_id": sid, "message": {"action": {"type": "walk_away"}}}
            self.log("decision", {"action": decision, "reason": "no feasible candidate"}, sid)
            return decision
        chosen = ranked[0]
        self.log(
            "plan",
            {
                "top_packages": ranked[:6],
                "standing_cost": best[0] if best else None,
                "conditions": th.beliefs.conditions,
                "remaining_moves": th.planning_moves,
            },
            sid,
        )
        walk_objective, _ = paired_objective(
            [fallback] * len(th.beliefs.particles),
            th.planning_anchor,
            [p.weight for p in th.beliefs.particles],
            self.risk_for_case(case),
        )
        if chosen["objective"] >= walk_objective and (not best or best[0] >= walk_objective):
            if len(actionable) > 1 and deadline - time.monotonic() > 3:
                self.parked.add(sid)
                self.log("park", {"reason": "other supplier negotiations remain available"}, sid)
                return self._decide(case, threads, started, deadline)
            decision = {"supplier_id": sid, "message": {"action": {"type": "walk_away"}}}
            self.log(
                "decision",
                {
                    "action": decision,
                    "reason": "fallback dominates risk-adjusted alternatives",
                    "walk_objective": walk_objective,
                    "llm_calls": self.router.calls,
                },
                sid,
            )
            self.router.calls = []
            return decision
        if best and chosen["objective"] >= best[0] - max(0.01, best[0] * 0.0001):
            if len(actionable) > 1 and deadline - time.monotonic() > 3:
                self.parked.add(sid)
                self.log("park", {"reason": "check remaining suppliers before accepting"}, sid)
                return self._decide(case, threads, started, deadline)
            probe = self.initial_counteroffer(case, threads, sid, th, best, ranked)
            if probe is None:
                return self.accept(best, "available deal dominates estimated continuation")
            chosen = probe
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
        alternate = equivalent_alternative(self, case, th, terms)
        offers = [terms] + ([alternate] if alternate else [])
        if alternate:
            quote = current.get("unit_price") or th.reference["unit_price"]
            forecasts = [
                th.beliefs.probabilities(max(offers, key=lambda t: th.beliefs.value(t, p)), p, quote)
                for p in th.beliefs.particles
            ]
            chosen["probabilities"] = {
                k: self.weighted(th, [pr[k] for pr in forecasts]) for k in ("accept", "counter", "walk")
            }
            chosen["alternative_terms"] = alternate
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
        if alternate:
            body += (
                "\n\nWe have attached a second package at a comparable cost to us. "
                "Please indicate which better suits you."
            )
        message = {"subject": "Re: " + case["title"], "body": body, "term_sheets": [{"terms": t} for t in offers]}
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
            "offers": offers,
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
