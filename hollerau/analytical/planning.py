"""Paired decision risk and bounded receding-horizon negotiation forecasts."""

import math

from arena_kit.cost import closing_terms, complete_offer, total_cost

from .preferences import violated


def paired_objective(values, anchor, weights, risk_aversion):
    """Use the same uncertain world for accept/counter/walk; shared cost uncertainty cancels."""
    delta = [v - a for v, a in zip(values, anchor, strict=True)]
    mean = sum(w * d for w, d in zip(weights, delta, strict=True))
    sd = math.sqrt(sum(w * (d - mean) ** 2 for w, d in zip(weights, delta, strict=True)))
    return sum(w * a for w, a in zip(weights, anchor, strict=True)) + mean + risk_aversion * sd, sd


def counter_template(case, beliefs, terms, current):
    """Approximate a supplier's counter by repairing sourced conditions with allowed values."""
    out = dict(terms)
    for c in beliefs.conditions:
        if not violated(closing_terms(case, out, beliefs.supplier["standard"]), c):
            continue
        for field, value in c["requires"].items():
            if value == "present" and field == "index_clause":
                value = current.get(field) or next((v for v in case["term_options"].get(field, []) if v), None)
            out[field] = value
    return complete_offer(case, out)


def counter_costs(case, th, terms, current, valid, fallback, particles=None):
    """Forecast counteroffers with the option to stop after each reply.

    The reply can be conservative, typical or generous about price movement. Averaging
    these scenarios avoids assuming our entire package will simply be accepted next turn.
    Current offers from this thread are not assumed to survive a new counteroffer.
    Future requests concede gradually; each additional move must pay for its own risk.
    Replan from the actual reply rather than assuming this forecast will happen.
    """
    template = counter_template(case, th.beliefs, terms, current)
    costs = []
    rate = th.beliefs.concession_rate
    for p in th.beliefs.particles if particles is None else particles:
        old_value = th.beliefs.value(current, p)
        requested = th.beliefs.value(template, p)
        v0 = th.beliefs.value({**template, "unit_price": 0}, p)
        slope = th.beliefs.value({**template, "unit_price": 1}, p) - v0
        if slope <= 0:
            costs.append(fallback)
            continue
        replies = []
        for fraction in (0.5 * rate, rate, min(0.7, 1.5 * rate)):
            path_costs, risks = [], []
            worth = old_value
            depth = min(4, max(1, th.planning_moves - 1))
            for step in range(depth):
                request = requested + step * max(0.01, current["unit_price"] * 0.002)
                target = min(worth, max(p.r, request))
                worth = max(target, worth - fraction * max(0, worth - target))
                price = max(0.01, (worth - v0) / slope)
                reply = {**template, "unit_price": round(price, 2)}
                cost = (
                    total_cost(case, reply, th.std, {**th.sup, "full_cost": p.full_cost}) if valid(reply) else fallback
                )
                path_costs.append(min(cost, fallback))
                offer = {**template, "unit_price": max(0.01, (request - v0) / slope)}
                risks.append(th.beliefs.probabilities(offer, p, current["unit_price"])["walk"])
            future = path_costs[-1]
            for step in range(len(path_costs) - 2, -1, -1):
                keep_negotiating = (1 - risks[step + 1]) * future + risks[step + 1] * fallback + fallback * 0.0003
                future = min(path_costs[step], keep_negotiating)
            replies.append(future)
        costs.append(sum(replies) / len(replies))
    return costs
