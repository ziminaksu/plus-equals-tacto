"""Joint weighted supplier scenarios; explicit priors, no LLM-assigned probabilities."""

import hashlib
import math
import random
from dataclasses import asdict, dataclass

from arena_kit.cost import closing_terms, supplier_value


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
        # Full production cost and acceptance threshold are different uncertain variables.
        floor = supplier["full_cost"] / 0.94
        center = min(p * 0.97, max(p * 0.80, floor))
        self.tau = max(0.01, p * 0.025)
        payment_max = p * (0.060 if self.signals["cash_short"] else 0.035)
        term_min, term_max = (-p * 0.005, p * 0.040) if self.signals["wants_partnership"] else (-p * 0.020, p * 0.025)
        capacity_min, capacity_max = (1.0, 6.0) if self.signals["spare_capacity"] else (3.0, 15.0)
        # Quality-first cases already price defects in the official buyer TCO.
        # Use a more cautiously optimistic supplier quality-cost prior, not an
        # extra buyer-side quality penalty. This remains an uncalibrated sensitivity.
        self.quality_cost_max = p * (0.012 if case["buyer"].get("category_goal") == "quality_first" else 0.020)
        self.particles = [
            Particle(
                rng.uniform(center * 0.94, min(p * 1.015, center * 1.06)),
                rng.uniform(0, payment_max),
                rng.uniform(term_min, term_max),
                rng.uniform(0, p * 0.02),
                supplier["full_cost"] * rng.uniform(0.90, 1.10),
                rng.uniform(capacity_min, capacity_max),
                rng.uniform(0, self.quality_cost_max),
                1 / count,
            )
            for _ in range(count)
        ]
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

    def value(self, terms, particle):
        c, ref = self.case, self.reference
        t = closing_terms(c, terms, self.supplier["standard"])
        # Payment is represented by b_pay only, not counted again in supplier_value.
        sup = {**self.supplier, "interest_rate": 0.0, "usual_rate": 0.0}
        cash = supplier_value(c, t, sup)
        return (
            cash
            + particle.b_pay * (ref["payment_days"] - t["payment_days"]) / 30
            + particle.b_term * (t["contract_months"] - ref["contract_months"]) / 12
            + particle.b_flex * (t["lead_time_days"] - ref["lead_time_days"]) / 7
            - particle.b_quality * max(0, (ref.get("ppm_commitment") or 0) - (t.get("ppm_commitment") or 0)) / 1000
        )

    def probabilities(self, terms, particle, quote, repeats=0):
        gap = max(0, (quote - terms["unit_price"]) / max(quote, 0.01))
        walk = sigmoid(self.walk_intercept + self.walk_pressure * gap + self.walk_repeat * repeats)
        accept = (1 - walk) * sigmoid((self.value(terms, particle) - particle.r) / self.tau + self.accept_bias)
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

    def update(self, event_id, offers, outcome, quote, repeats=0):
        if event_id in self.seen or not offers:
            return False
        if outcome not in ("accept", "counter", "walk"):
            raise ValueError("unknown outcome")
        self.seen.add(event_id)
        predicted = {
            k: sum(p.weight * self.probabilities(offers[0], p, quote, repeats)[k] for p in self.particles)
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
        fields = ("r", "b_pay", "b_term", "b_flex", "b_quality")
        return {
            "version": 2,
            "observations": self.learned_observations,
            "means": {f: sum(p.weight * getattr(p, f) for p in self.particles) / price for f in fields},
            "response": [self.walk_intercept, self.walk_pressure, self.walk_repeat, self.accept_bias],
        }

    def import_learning(self, memory):
        models = [m for m in memory.get("models", []) if m.get("version") == 2 and m.get("observations", 0) > 0]
        if not models:
            return
        self.memory_source = memory["source"]
        blend = 0.25 if memory["source"] == "supplier" else 0.10
        price = self.reference["unit_price"]
        for field in ("r", "b_pay", "b_term", "b_flex", "b_quality"):
            prior = sum(p.weight * getattr(p, field) for p in self.particles)
            learned = sum(m["means"][field] for m in models) / len(models) * price
            shift = blend * (learned - prior)
            for p in self.particles:
                value = getattr(p, field) + shift
                setattr(p, field, value if field == "b_term" else max(0, value))
        names = ("walk_intercept", "walk_pressure", "walk_repeat", "accept_bias")
        for i, name in enumerate(names):
            value = sum(m["response"][i] for m in models) / len(models)
            setattr(self, name, (1 - blend) * getattr(self, name) + blend * value)

    def summary(self):
        out = {
            "version": self.version,
            "memory_source": self.memory_source,
            "supplier_signals": dict(self.signals),
            "signals_applied": dict(self.signal_counts),
            "quality_prior_max_eur_per_1000ppm": round(self.quality_cost_max, 6),
            "tau": self.tau,
            "response_coefficients": {
                "w0": self.walk_intercept,
                "w_d": self.walk_pressure,
                "w_repeat": self.walk_repeat,
                "status": "regularised online estimates; not statistically calibrated",
                "accept_bias": self.accept_bias,
            },
        }
        for field in ("r", "b_pay", "b_term", "b_flex", "full_cost", "b_capacity", "b_quality"):
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
