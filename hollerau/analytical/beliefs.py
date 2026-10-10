"""Joint weighted supplier scenarios; explicit priors, no LLM-assigned probabilities."""

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass

from arena_kit.cost import closing_terms, supplier_value

from .preferences import violated


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-35, min(35, x))))


@dataclass
class Particle:
    r: float
    b_pay: float
    b_term: float
    b_flex: float
    full_cost: float
    b_capacity: float
    b_quality: float
    weight: float
    b_index: float = 0.0
    b_volume: float = 0.0


class Beliefs:
    def __init__(self, case, reference, supplier, seed=7, count=64, signals=None):
        self.case, self.reference, self.supplier = case, reference, supplier
        signals = signals or {}
        self.signals = {
            name: bool(signals.get(name, False))
            for name in ("cash_short", "spare_capacity", "approval_ladder", "wants_partnership")
        }
        self.seen = set()
        self.version = 0
        self.capacity_reference = reference.get("volume_per_year") if case.get("type") == "capacity" else None
        p = reference["unit_price"]
        rng = random.Random(seed)
        extra_rng = random.Random(seed ^ 0x1D3E)
        # Full production cost and acceptance threshold are different uncertain variables.
        floor = supplier["full_cost"] / 0.94
        center = min(p * 0.97, max(p * 0.80, floor))
        self.tau = max(0.01, p * 0.025)
        # b_pay is EUR per unit for *30 days* earlier payment. Start from an
        # uncertain annual financing rate and convert it to that unit.
        payment_max = p * (0.30 if self.signals["cash_short"] else 0.18) * 30 / 360
        term_min, term_max = (-p * 0.005, p * 0.040) if self.signals["wants_partnership"] else (-p * 0.020, p * 0.025)
        capacity_min, capacity_max = (1.0, 6.0) if self.signals["spare_capacity"] else (3.0, 15.0)
        # Quality-first cases already price defects in the official buyer TCO.
        # Use a more cautiously optimistic supplier quality-cost prior, not an
        # extra buyer-side quality penalty. This remains an uncalibrated sensitivity.
        self.quality_cost_max = p * (0.012 if case["buyer"].get("category_goal") == "quality_first" else 0.020)
        # Uncalibrated supplier-side benefit per unit from index protection.
        # It has NO effect until a quote-backed index_protection signal is applied.
        self.index_value_max = p * 0.05
        self.particles = [
            Particle(
                # Public should-costs have material estimation error, and a quote-based
                # substitute is weaker still. Do not rule out lower floors a priori.
                rng.uniform(center * 0.85, min(p * 1.015, center * 1.10)),
                rng.uniform(0, payment_max),
                rng.uniform(term_min, term_max),
                rng.uniform(0, p * 0.02),
                supplier["full_cost"] * rng.uniform(0.90, 1.10),
                rng.uniform(capacity_min, capacity_max),
                rng.uniform(0, self.quality_cost_max),
                1 / count,
                extra_rng.uniform(0, self.index_value_max),
                extra_rng.uniform(0, p * (0.04 if self.signals["spare_capacity"] else 0.01)),
            )
            for _ in range(count)
        ]
        uncertainty = supplier.get("cost_uncertainty_pct", 10)
        spread = min(0.5, max(0.01, float(uncertainty) / 100))
        self.cost_prior_conflict = bool(supplier.get("has_should_cost") and supplier["full_cost"] > p)
        for i, particle in enumerate(self.particles):
            particle.full_cost = supplier["full_cost"] * extra_rng.uniform(1 - spread, 1 + spread)
            # Production cost is no longer mixed with quote-implied discounts.
            # Live costs use the independent SupplierEconomics distribution.
        # Pooled response assumptions, not coefficients learned from five sessions.
        self.walk_intercept = -5.0
        self.walk_pressure = 12.0 if self.signals["approval_ladder"] else 10.0
        self.walk_repeat = 0.50 if self.signals["approval_ladder"] else 0.35
        self.response_prior = (self.walk_intercept, self.walk_pressure, self.walk_repeat)
        self.evidence_seen = set()
        self.signal_counts = {}
        self.accept_bias = 0.0
        self.learned_observations = 0
        self.memory_source = None
        self.conditions = []
        self.numeric_seen = set()
        self.numeric_observations = 0
        self.concession_rate = 0.20
        self.cost_checks = set()
        self.condition_version = 0
        self.standing_terms = dict(reference)
        self.choice_seen = set()

    @staticmethod
    def index_protection(terms):
        clause = terms.get("index_clause")
        if not clause:
            return 0.0
        return (
            clause["material_share"]
            * max(0, 1 - clause["deadband_pct"] / 10)
            * min(3, terms.get("contract_months", 12) / 12)
        )

    def value(self, terms, particle):
        c, ref = self.case, self.reference
        t = closing_terms(c, terms, self.supplier["standard"])
        # Payment is represented by b_pay only, not counted again in supplier_value.
        sup = {**self.supplier, "interest_rate": 0.0, "usual_rate": 0.0}
        cash = supplier_value(c, t, sup)
        # Activate one continuous, relative index value only with sourced evidence.
        # Do not add the legacy binary bonus on top of the same preference.
        index_supported = self.signal_counts.get("index_protection") or any(
            c.get("requires", {}).get("index_clause") == "present" for c in self.conditions
        )
        index_delta = (
            particle.b_index * (self.index_protection(t) - self.index_protection(ref))
            if index_supported and "index_clause" in c["negotiable"]
            else 0.0
        )
        return (
            cash
            + index_delta
            + particle.b_pay * (ref["payment_days"] - t["payment_days"]) / 30
            + particle.b_term * (t["contract_months"] - ref["contract_months"]) / 12
            + particle.b_flex * (t["lead_time_days"] - ref["lead_time_days"]) / 7
            - particle.b_quality * max(0, (ref.get("ppm_commitment") or 0) - (t.get("ppm_commitment") or 0)) / 1000
            + particle.b_volume
            * (t["volume_per_year"] / max(1, ref["volume_per_year"]) - 1)
            * min(2, t["contract_months"] / 12)
        )

    def probabilities(self, terms, particle, quote, repeats=0):
        # Price alone overstates pressure when payment or freight compensates the supplier.
        old_value = self.value(self.standing_terms, particle)
        offered_value = self.value(terms, particle)
        gap = max(0, (old_value - offered_value) / max(quote, 0.01))
        walk = sigmoid(self.walk_intercept + self.walk_pressure * gap + self.walk_repeat * repeats)
        # Reservation value is a possible eventual agreement, not immediate willingness
        # to accept. Estimate the next ask from observed concessions, separately from r.
        threshold = max(particle.r, old_value - self.concession_rate * max(0, old_value - particle.r))
        accept = (1 - walk) * sigmoid((offered_value - threshold) / self.tau + self.accept_bias)
        t = closing_terms(self.case, terms, self.supplier["standard"])
        if any(violated(t, c) for c in self.conditions):
            accept *= 0.08  # a sourced negotiating condition is strong, but not a physical law
        # An explicit supplier requirement for index protection is a *soft*
        # acceptance signal, not a new buyer-side must-have. In particular,
        # offering a longer contract without any index clause remains possible
        # but is predicted less likely to succeed (the factor is uncalibrated).
        elif (
            self.signal_counts.get("index_protection")
            and "index_clause" in self.case["negotiable"]
            and not t.get("index_clause")
            and t["contract_months"] >= 24
        ):
            accept *= 0.35
        if self.capacity_reference:
            volume = closing_terms(self.case, terms, self.supplier["standard"])["volume_per_year"]
            uplift = max(0, volume / self.capacity_reference - 1)
            # Conditional relief is uncertain and only enabled by sourced commitment evidence.
            if self.signal_counts.get("long_commitment"):
                extra_years = max(
                    0, volume and (terms.get("contract_months", 12) - self.reference["contract_months"]) / 12
                )
                uplift *= math.exp(-0.25 * extra_years)
            accept *= math.exp(-particle.b_capacity * uplift)
        return {"accept": accept, "counter": 1 - walk - accept, "walk": walk}

    def apply_conditions(self, conditions):
        old = {json.dumps([c["when"], c["requires"]], sort_keys=True) for c in self.conditions}
        added = []
        for condition in conditions:
            key = json.dumps([condition["when"], condition["requires"]], sort_keys=True)
            if key not in old:
                self.conditions.append(condition)
                old.add(key)
                added.append(condition)
        if added:
            self.condition_version += 1
        return added

    def check_cost_consistency(self, terms):
        """A voluntary quote constrains willingness to accept, never production cost."""
        # Every new executable quote constrains reservation value, even after the limited
        # production-cost updates have been exhausted.
        for part in self.particles:
            part.r = min(part.r, self.value(terms, part))

    def normalise(self):
        total = sum(p.weight for p in self.particles)
        for p in self.particles:
            p.weight /= total

    def learn_counteroffer(self, event_id, previous, offered, proposed):
        """Learn soft trade-offs from public counteroffers; never treat an ask as a floor."""
        if event_id in self.numeric_seen or not offered.get("unit_price"):
            return False
        self.numeric_seen.add(event_id)
        before = previous or self.reference
        rates = []
        for p in self.particles:
            old, now, ask = self.value(before, p), self.value(offered, p), self.value(proposed, p)
            gap = max(self.tau, old - ask)
            rates.append(max(0, min(0.6, (old - now) / gap)))
            # Upper-bound evidence only: a quoted package is usually above reservation value.
            upper = max(0.10, sigmoid((now - p.r) / self.tau))
            # A price decrease traded for payment/duration/etc. should roughly conserve value,
            # allowing wide error for discretionary concessions and strategic posturing.
            expected = old - self.concession_rate * max(0, old - ask)
            residual = (now - expected) / (self.tau * 2)
            trade = max(0.20, math.exp(-0.5 * min(16, residual * residual)))
            p.weight *= (upper * trade) ** 0.25
        self.normalise()
        observed = sum(p.weight * v for p, v in zip(self.particles, rates, strict=True))
        self.concession_rate = 0.5 * self.concession_rate + 0.5 * observed
        self.numeric_observations += 1
        self.check_cost_consistency(offered)
        self.standing_terms = dict(offered)
        # Directly contradictory behaviour weakens a textual condition: remove it when the
        # supplier itself quotes a package violating that condition.
        self.reconcile_conditions(offered)
        return True

    def learn_choice(self, event_id, chosen, alternatives):
        """A clearly echoed package is noisy evidence about relative preferences."""
        if event_id in self.choice_seen or len(alternatives) < 2:
            return False
        self.choice_seen.add(event_id)
        for p in self.particles:
            chosen_value = self.value(chosen, p)
            other_value = max(self.value(t, p) for t in alternatives if t != chosen)
            p.weight *= max(0.1, sigmoid((chosen_value - other_value) / (self.tau * 0.5))) ** 0.5
        self.normalise()
        return True

    def reconcile_conditions(self, offered):
        t = closing_terms(self.case, offered, self.supplier["standard"])
        kept = [c for c in self.conditions if not violated(t, c)]
        if len(kept) != len(self.conditions):
            self.conditions = kept
            self.condition_version += 1

    def update(self, event_id, offers, outcome, quote, repeats=0):
        if event_id in self.seen or not offers:
            return False
        if outcome not in ("accept", "counter", "walk"):
            raise ValueError("unknown outcome")
        self.seen.add(event_id)
        predicted = {
            k: sum(
                p.weight * self.probabilities(max(offers, key=lambda t: self.value(t, p)), p, quote, repeats)[k]
                for p in self.particles
            )
            for k in ("accept", "walk")
        }
        for part in self.particles:
            # Single sheet in MVP; max is a cautious approximation for legacy multi-sheet offers.
            best = max(offers, key=lambda t: self.value(t, part))
            likelihood = self.probabilities(best, part, quote, repeats)[outcome]
            part.weight *= max(0.03, likelihood) ** 0.5  # temper strategic/noisy responses
        total = sum(p.weight for p in self.particles)
        for part in self.particles:
            part.weight /= total
        # Regularised online calibration of response assumptions; still uncertain with few observations.
        error = float(outcome == "walk") - predicted["walk"]
        gap = max(0, (quote - offers[0]["unit_price"]) / max(quote, 0.01))
        self.walk_intercept = max(
            -7, min(-2, self.walk_intercept + 0.15 * error - 0.01 * (self.walk_intercept - self.response_prior[0]))
        )
        self.walk_pressure = max(
            2, min(18, self.walk_pressure + 0.5 * error * gap - 0.01 * (self.walk_pressure - self.response_prior[1]))
        )
        self.walk_repeat = max(
            0, min(2, self.walk_repeat + 0.1 * error * repeats - 0.01 * (self.walk_repeat - self.response_prior[2]))
        )
        self.accept_bias = max(-2, min(2, self.accept_bias + 0.5 * (float(outcome == "accept") - predicted["accept"])))
        self.version += 1
        self.learned_observations += 1
        return True

    def apply_evidence(self, signals):
        """Bounded soft updates from quoted statements. Never turn a claim into a hard constraint."""
        applied = []
        mapping = {
            "early_payment": "b_pay",
            "long_commitment": "b_term",
            "delivery_flexibility": "b_flex",
            "capacity_limit": "b_capacity",
            "quality_cost": "b_quality",
            "price_resistance": "r",
            "index_protection": "b_index",
        }
        for signal in signals:
            kind = signal.get("kind")
            token = hashlib.sha256((kind + signal["quote"].strip().lower()).encode()).hexdigest()
            if kind not in mapping or token in self.evidence_seen or self.signal_counts.get(kind, 0) >= 2:
                continue
            self.evidence_seen.add(token)
            self.signal_counts[kind] = self.signal_counts.get(kind, 0) + 1
            field = mapping[kind]
            vals = [getattr(p, field) for p in self.particles]
            lo, hi = min(vals), max(vals)
            for p in self.particles:
                # At most a 2x likelihood ratio per independent statement; keep alternative scenarios.
                p.weight *= 1 + (getattr(p, field) - lo) / max(1e-9, hi - lo)
            total = sum(p.weight for p in self.particles)
            for p in self.particles:
                p.weight /= total
            applied.append(kind)
        return applied

    def export_learning(self):
        price = self.reference["unit_price"]
        fields = ("r", "b_pay", "b_term", "b_flex", "b_quality", "b_index", "b_volume")
        return {
            "version": 3,
            "observations": self.learned_observations,
            "means": {f: sum(p.weight * getattr(p, f) for p in self.particles) / price for f in fields},
            "response": [self.walk_intercept, self.walk_pressure, self.walk_repeat, self.accept_bias],
            "concession_rate": self.concession_rate,
            "numeric_observations": self.numeric_observations,
        }

    def import_learning(self, memory):
        models = [m for m in memory.get("models", []) if m.get("version") in (2, 3) and m.get("observations", 0) > 0]
        if not models:
            return
        self.memory_source = memory["source"]
        blend = 0.25 if memory["source"] == "supplier" else 0.10
        price = self.reference["unit_price"]
        for field in ("r", "b_pay", "b_term", "b_flex", "b_quality", "b_index", "b_volume"):
            matching = [m for m in models if field in m["means"]]
            if not matching:
                continue
            prior = sum(p.weight * getattr(p, field) for p in self.particles)
            learned = sum(m["means"][field] for m in matching) / len(matching) * price
            shift = blend * (learned - prior)
            for p in self.particles:
                value = getattr(p, field) + shift
                setattr(p, field, value if field == "b_term" else max(0, value))
        names = ("walk_intercept", "walk_pressure", "walk_repeat", "accept_bias")
        for i, name in enumerate(names):
            value = sum(m["response"][i] for m in models) / len(models)
            setattr(self, name, (1 - blend) * getattr(self, name) + blend * value)
        numeric = [m for m in models if m.get("numeric_observations", 0)]
        if numeric:
            learned = sum(m["concession_rate"] for m in numeric) / len(numeric)
            self.concession_rate = (1 - blend) * self.concession_rate + blend * learned

    def summary(self):
        out = {
            "version": self.version,
            "memory_source": self.memory_source,
            "cost_prior_conflict": self.cost_prior_conflict,
            "cost_prior_note": (
                "public mean exceeds quote; this alone is not a contradiction within the public uncertainty interval"
                if self.cost_prior_conflict else "public cost evidence kept independent of acceptance"
            ),
            "supplier_signals": dict(self.signals),
            "signals_applied": dict(self.signal_counts),
            "quality_prior_max_eur_per_1000ppm": round(self.quality_cost_max, 6),
            "index_prior_max_eur_per_unit": round(self.index_value_max, 6),
            "index_protection_active": bool(self.signal_counts.get("index_protection")),
            "tau": self.tau,
            "conditions": self.conditions,
            "concession_rate": self.concession_rate,
            "numeric_observations": self.numeric_observations,
            "response_coefficients": {
                "w0": self.walk_intercept,
                "w_d": self.walk_pressure,
                "w_repeat": self.walk_repeat,
                "status": "regularised online estimates; not statistically calibrated",
                "accept_bias": self.accept_bias,
            },
        }
        for field in ("r", "b_pay", "b_term", "b_flex", "b_capacity", "b_quality", "b_index", "b_volume"):
            values = sorted((getattr(p, field), p.weight) for p in self.particles)

            def quantile(q, values=values):
                cumulative = 0
                for v, w in values:
                    cumulative += w
                    if cumulative >= q:
                        return round(v, 4)
                return values[-1][0]

            out[field] = {"mean": round(sum(v * w for v, w in values), 4), "p10": quantile(0.1), "p90": quantile(0.9)}
        out["effective_scenarios"] = round(1 / sum(p.weight**2 for p in self.particles), 2)
        return out

    def snapshot(self):
        return {
            "summary": self.summary(),
            "reference": self.reference,
            "capacity_reference": self.capacity_reference,
            "particles": [asdict(p) for p in self.particles],
        }
