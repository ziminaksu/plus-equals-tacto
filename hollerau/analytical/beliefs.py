"""Joint weighted supplier scenarios; explicit priors, no LLM-assigned probabilities."""

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
    weight: float


class Beliefs:
    def __init__(self, case, reference, supplier, seed=7, count=64):
        self.case, self.reference, self.supplier = case, reference, supplier
        self.seen = set()
        self.version = 0
        self.capacity_reference = reference.get("volume_per_year") if case.get("type") == "capacity" else None
        p = reference["unit_price"]
        rng = random.Random(seed)
        # Full production cost and acceptance threshold are different uncertain variables.
        floor = supplier["full_cost"] / 0.94
        center = min(p * 0.97, max(p * 0.80, floor))
        self.tau = max(0.01, p * 0.025)
        self.particles = [
            Particle(
                rng.uniform(center * 0.94, min(p * 1.015, center * 1.06)),
                rng.uniform(0, p * 0.035),
                rng.uniform(-p * 0.02, p * 0.025),
                rng.uniform(0, p * 0.02),
                supplier["full_cost"] * rng.uniform(0.90, 1.10),
                rng.uniform(3, 15),
                1 / count,
            )
            for _ in range(count)
        ]
        # Pooled response assumptions, not coefficients learned from five sessions.
        self.walk_intercept, self.walk_pressure, self.walk_repeat = -5.0, 10.0, 0.35

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
        )

    def probabilities(self, terms, particle, quote, repeats=0):
        gap = max(0, (quote - terms["unit_price"]) / max(quote, 0.01))
        walk = sigmoid(self.walk_intercept + self.walk_pressure * gap + self.walk_repeat * repeats)
        accept = (1 - walk) * sigmoid((self.value(terms, particle) - particle.r) / self.tau)
        if self.capacity_reference:
            volume = closing_terms(self.case, terms, self.supplier["standard"])["volume_per_year"]
            uplift = max(0, volume / self.capacity_reference - 1)
            accept *= math.exp(-particle.b_capacity * uplift)
        return {"accept": accept, "counter": 1 - walk - accept, "walk": walk}

    def update(self, event_id, offers, outcome, quote, repeats=0):
        if event_id in self.seen or not offers:
            return False
        if outcome not in ("accept", "counter", "walk"):
            raise ValueError("unknown outcome")
        self.seen.add(event_id)
        for part in self.particles:
            # Single sheet in MVP; max is a cautious approximation for legacy multi-sheet offers.
            best = max(offers, key=lambda t: self.value(t, part))
            likelihood = self.probabilities(best, part, quote, repeats)[outcome]
            part.weight *= max(0.03, likelihood) ** 0.5  # temper strategic/noisy responses
        total = sum(p.weight for p in self.particles)
        for part in self.particles:
            part.weight /= total
        self.version += 1
        return True

    def summary(self):
        out = {
            "version": self.version,
            "tau": self.tau,
            "response_coefficients": {
                "w0": self.walk_intercept,
                "w_d": self.walk_pressure,
                "w_repeat": self.walk_repeat,
                "status": "uncalibrated pooled defaults",
            },
        }
        for field in ("r", "b_pay", "b_term", "b_flex", "full_cost", "b_capacity"):
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
