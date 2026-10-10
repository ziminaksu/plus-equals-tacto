"""Equivalent-cost choices reveal supplier preferences without giving value away."""

from arena_kit.cost import closing_terms

from .. import levers
from .preferences import violated


def equivalent_alternative(agent, case, th, primary):
    """Offer at most one distinct, affordable package, using only public information.

    A supplier's choice gives us evidence about trade-offs (e.g. price vs payment).
    Both choices must satisfy the buyer's constraints and the same expected budget.
    """
    # Learn from an opening menu, then follow through on the supplier's response.
    # Repeatedly repricing both options can accidentally reverse a concession.
    if th.last_terms is not None:
        return None
    base_costs = agent.cost_samples(case, th, primary)
    budget = agent.weighted(th, base_costs)
    supplier = {**th.sup, "full_cost": agent.weighted(th, [p.full_cost for p in th.beliefs.particles])}
    candidates = []
    for field in levers.lever_fields(case):
        for value in levers.field_options(case, field, th.std):
            if value == primary.get(field):
                continue
            pkg = {k: v for k, v in primary.items() if k != "unit_price"}
            pkg[field] = value
            price = levers.price_for_cost(case, pkg, budget, th.std, supplier)
            if price is None or not 0.8 * primary["unit_price"] <= price <= 1.2 * primary["unit_price"]:
                continue
            terms = {**pkg, "unit_price": round(price, 2)}
            if not agent.valid(case, th, terms):
                continue
            if any(violated(closing_terms(case, terms, th.std), c) for c in th.beliefs.conditions):
                continue
            costs = agent.cost_samples(case, th, terms)
            # Keep the mean and the adverse *difference* affordable, including relationship cost.
            if agent.weighted(th, costs) > budget * 1.001:
                continue
            if max(c - b for c, b in zip(costs, base_costs, strict=True)) > budget * 0.003:
                continue
            gains = [th.beliefs.value(terms, p) - th.beliefs.value(primary, p) for p in th.beliefs.particles]
            win = sum(p.weight for p, gain in zip(th.beliefs.particles, gains, strict=True) if gain > 0)
            # Prefer choices that split plausible preferences; repeated equivalent sheets teach nothing.
            information = 4 * win * (1 - win)
            upside = agent.weighted(th, [max(0, gain) for gain in gains])
            if information > 0.1 and upside > primary["unit_price"] * 0.0005:
                candidates.append((information * upside, terms))
    return max(candidates, key=lambda x: x[0])[1] if candidates else None


def echoed_proposal(case, standard, proposals, reply):
    """Infer the chosen package only when non-price terms identify it unambiguously."""
    actual = closing_terms(case, reply, standard)
    matches = [
        p
        for p in proposals
        if all(
            value == actual.get(field)
            for field, value in closing_terms(case, p, standard).items()
            if field != "unit_price"
        )
    ]
    return matches[0] if len(matches) == 1 else None
