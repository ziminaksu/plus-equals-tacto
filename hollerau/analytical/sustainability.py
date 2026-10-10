"""Supplier economics, independent of willingness-to-accept scenarios.

Only completed practice feedback may calibrate these estimates. Never use C_best,
leaderboards or live-final results. Inferred effective cost is not an audited factory cost.
"""

import hashlib
import json
import math

from arena_kit.cost import RELATIONSHIP_GOALS, closing_terms, cost_breakdown, supplier_value

COST_COMPONENTS = ("price", "uncovered_need", "fallback_risk", "payment_terms", "freight",
                   "late_delivery", "quality", "tooling", "index_clause", "index_risk", "relationship")

def context_id(case):
    data = {k: case.get(k) for k in ("case_id", "parts", "buyer", "fixed_terms", "term_options")}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def practice_observation(case, result, session, predicted=None):
    """Whitelist observed components; deliberately never retain score/hidden benchmark."""
    if (not case.get("case_id", "").startswith("case:P") or not session
            or not result.get("deal") or not result.get("terms")
            or not isinstance(result.get("cost_breakdown"), dict)):
        return None
    components = {k: result["cost_breakdown"][k] for k in COST_COMPONENTS if k in result["cost_breakdown"]}
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in components.values()):
        return None
    return {"source": "completed practice cost breakdown", "session_id": session,
            "context_id": context_id(case), "supplier_id": result.get("supplier_id"),
            "terms": result["terms"], "actual_components_eur": components,
            "predicted_components_eur": predicted or {},
            "forecast_error_eur": {k: round(v - predicted[k], 2) for k, v in components.items()
                                   if predicted and k in predicted},
            "currently_executable": False}


def percentile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


class SupplierEconomics:
    def __init__(self, case, supplier, standard, raw_cost, cost_ref, uncertainty_pct, feedback):
        self.case, self.supplier, self.standard = case, supplier, standard
        self.raw_cost, self.cost_ref = raw_cost, cost_ref
        self.spread = min(0.5, max(0.01, float(uncertainty_pct) / 100))
        self.center = float(raw_cost or supplier["full_cost"])
        self.low, self.high = self.center * (1 - self.spread), self.center * (1 + self.spread)
        self.feedback = [f for f in feedback if f.get("context_id") == context_id(case)]
        self.calibration = []
        self.conflict = False
        self._calibrate()
        # These values/weights NEVER change when an offer is accepted or rejected.
        self.costs = [self.low + (self.high - self.low) * i / 8 for i in range(9)]

    def _calibrate(self):
        buyer = self.case["buyer"]
        rate, target = buyer.get("relationship_eur_per_point", 0), buyer.get("sustainable_margin_pct", 0)
        if buyer.get("category_goal") not in RELATIONSHIP_GOALS or not rate or not target:
            return
        intervals, caps = [], []
        seen = set()
        for feedback in self.feedback:
            terms = closing_terms(self.case, feedback["terms"], self.standard)
            penalty = feedback["actual_components_eur"].get("relationship")
            if penalty is None or penalty < 0:
                continue
            signature = json.dumps([terms, penalty], sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            years = min(terms["contract_months"] / 12 if terms["contract_months"] else 1,
                        buyer["horizon_years"])
            if years <= 0:
                continue
            # Financing is still uncertain; preserve its effect on the inference.
            values = [supplier_value(self.case, terms, {**self.supplier, "interest_rate": r})
                      for r in (0.04, 0.18, self.supplier["interest_rate"])]
            if min(values) <= 0:
                continue
            gap_cost = penalty / (rate * years)
            gap = math.sqrt(10 * gap_cost) if gap_cost <= 2.5 else gap_cost + 2.5
            inferred = [value * (1 - (target - gap) / 100) for value in values]
            # A 0.5% effective-value allowance covers unmodelled supplier cash effects.
            # This is a modelling assumption, displayed to Astra, not a confidence claim.
            allowance = max(values) * 0.005
            low, high = max(0.01, min(inferred) - allowance), max(inferred) + allowance
            row = {"session_id": feedback["session_id"], "observed_relationship_eur": penalty,
                   "effective_cost_interval_eur": [round(low, 4), round(high, 4)],
                   "kind": "interval" if penalty > 0 else "upper_bound_only"}
            self.calibration.append(row)
            if penalty > 0:
                intervals.append((low, high))
            else:
                caps.append(high)
        if intervals:
            low, high = max(v[0] for v in intervals), min(v[1] for v in intervals)
            if low > high:
                self.conflict = True
                low, high = min(v[0] for v in intervals), max(v[1] for v in intervals)
            if caps and min(caps) >= low:
                high = min(high, min(caps))
            elif caps:
                self.conflict = True
            self.low, self.high = low, high
        elif caps:
            cap = min(caps)
            if cap >= self.low:
                self.high = min(self.high, cap)
            else:
                self.conflict = True  # Do not replace conflicting public data with invented certainty.

    def evidence(self):
        return {
            "public_should_cost": {"source_ref": self.cost_ref, "unit_cost_eur": self.raw_cost,
                                   "uncertainty_plus_minus_pct": self.spread * 100,
                                   "status": "estimate, not proven supplier cost"},
            "working_effective_cost_eur": {"low": round(self.low, 4), "high": round(self.high, 4),
                                          "midpoint": round((self.low + self.high) / 2, 4)},
            "calibration": self.calibration,
            "calibration_conflict": self.conflict,
            "assumptions": "Acceptance does not update production cost. Practice-derived intervals assume the "
                           "published formula, supplier financing at 4–18% (plus the initial estimate), and "
                           "a +/-0.5% cash-value allowance. Zero penalty is only an upper bound. "
                           "Same supplier/case/context only; no transfer of inferred costs to strangers.",
        }

    def breakdowns(self, terms):
        return [cost_breakdown(self.case, terms, self.standard, {**self.supplier, "full_cost": cost})
                for cost in self.costs]

    def card(self, terms):
        direct = cost_breakdown(self.case, terms, self.standard)
        samples = self.breakdowns(terms)
        expected = {k: sum(b[k] for b in samples) / len(samples) for k in direct}
        totals = [sum(b.values()) for b in samples]
        public = cost_breakdown(self.case, terms, self.standard,
                                {**self.supplier, "full_cost": self.center})
        cash = supplier_value(self.case, terms, self.supplier)
        margins = [(cash - c) / cash * 100 for c in self.costs] if cash > 0 else []
        return {"direct_cost_eur": round(sum(direct.values()), 2),
                "expected_total_eur": round(sum(expected.values()), 2),
                "expected_breakdown_eur": {k: round(v, 2) for k, v in expected.items()},
                "total_p10_p90_eur": [round(percentile(totals, q), 2) for q in (0.1, 0.9)],
                "public_cost_scenario": {"total_eur": round(sum(public.values()), 2),
                                         "relationship_eur": round(public["relationship"], 2)},
                "supplier_margin_pct_range": [round(min(margins), 3), round(max(margins), 3)] if margins else None,
                "uncertainty": "Independent cost scenarios, not calibrated probabilities or a predicted score. "
                               "Public should-cost scenario is shown separately. Acceptance is not sustainability."}

    def compare(self, terms, baseline):
        candidate, base = self.breakdowns(terms), self.breakdowns(baseline)
        deltas = [sum(a.values()) - sum(b.values()) for a, b in zip(candidate, base, strict=True)]
        return {"mean_delta_eur": round(sum(deltas) / len(deltas), 2),
                "p90_delta_eur": round(percentile(deltas, 0.9), 2),
                "worst_delta_eur": round(max(deltas), 2)}

    def frontier(self, seed):
        """Price trade-offs across legal terms, including higher-price sustainability options.

        This proposes a menu, never executes or vetoes Astra. No acceptance-probability pruning.
        """
        case = self.case
        if case["buyer"].get("category_goal") not in RELATIONSHIP_GOALS:
            return []
        packages = [{k: seed[k] for k in case["negotiable"]}]
        for field in ("payment_days", "index_clause"):
            if field in case["negotiable"]:
                packages = [{**p, field: option} for p in packages
                            for option in case.get("term_options", {}).get(field, [seed[field]])]
        rows = []
        for package in packages:
            values = []
            # Price range comes from the cost evidence and current package, not case IDs.
            low = max(0.01, min(self.low, seed["unit_price"]) * 0.85)
            high = max(self.high, self.center, seed["unit_price"]) * 1.10
            for i in range(65):
                terms = {**package, "unit_price": round(low + (high - low) * i / 64, 2)}
                totals = [sum(b.values()) for b in self.breakdowns(terms)]
                values.append((sum(totals) / len(totals), percentile(totals, 0.9), terms))
            # Mean and downside optimum at each legal term package; keep a small menu.
            for key, label in ((0, "mean total cost"), (1, "downside total cost")):
                best = min(values, key=lambda row, key=key: row[key])
                step = (high - low) / 64
                for _ in range(2):
                    center = best[2]["unit_price"]
                    for j in range(9):
                        terms = {**package, "unit_price": round(max(0.01, center - step + step * j / 4), 2)}
                        totals = [sum(b.values()) for b in self.breakdowns(terms)]
                        row = (sum(totals) / len(totals), percentile(totals, 0.9), terms)
                        if row[key] < best[key]:
                            best = row
                    step /= 4
                rows.append({"terms": best[2], "origin": f"sustainability trade-off: {label}; unconfirmed",
                             "criterion": key, "estimated_cost_eur": round(best[key], 2)})
        # Keep mean/downside alternatives for every payment choice and index presence.
        # Other exact index options remain in the ordinary sensitivity menu.
        groups = {}
        for row in rows:
            terms = row["terms"]
            group = (terms.get("payment_days"), bool(terms.get("index_clause")), row["criterion"])
            if group not in groups or row["estimated_cost_eur"] < groups[group]["estimated_cost_eur"]:
                groups[group] = row
        rows = list(groups.values())
        unique = {json.dumps(r["terms"], sort_keys=True): r for r in rows}
        return list(unique.values())
