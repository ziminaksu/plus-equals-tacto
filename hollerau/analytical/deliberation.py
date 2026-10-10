"""Action consequences presented BEFORE Astra chooses; never an execution veto."""

import math

from arena_kit.cost import RELATIONSHIP_GOALS

from .feedback import context_key


def objective_scope(case):
    buyer = case["buyer"]
    relationship = bool(buyer.get("category_goal") in RELATIONSHIP_GOALS
                        and buyer.get("relationship_eur_per_point") and buyer.get("sustainable_margin_pct"))
    return {"category_goal": buyer.get("category_goal"), "relationship_cost_active": relationship,
            "mode": "arena_improvement",
            "rule": "Maximise improvement over the opening total cost under Arena's published score, "
                    "subject to hard constraints. No deal and no improvement both score zero.",
            "reward_proxy": "Positive euro savings versus opening. The unknown best-cost denominator is "
                            "constant within a case; it is never imported. Saturation at score one is not modelled.",
            "supplier_margin_role": "Scored relationship cost and supplier willingness." if relationship else
            "Willingness evidence only. Supplier margin is NOT an additional buyer objective or price floor.",
            "zero_components": "A zero current component can activate after a term changes; inspect each package."}


def economics_context(case, th):
    if objective_scope(case)["relationship_cost_active"]:
        return th.economics.evidence()
    return {"relationship_cost_active": False,
            "instruction": "No sustainability penalty in this case. Do not pay extra to optimise supplier margin."}


def context_evidence(th, status, offers=True):
    counts = th.response_counts.get(context_key([{}] if offers else [], status), {})
    n, walks = sum(counts.values()), counts.get("walkout", 0)
    interval = [0.0, 1.0]
    if n:
        # Wilson interval describes the recorded proportion, NOT a calibrated action forecast.
        z, rate = 1.96, walks / n
        center = (rate + z * z / (2 * n)) / (1 + z * z / n)
        width = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        interval = [round(max(0, center - width), 3), round(min(1, center + width), 3)]
    return {"context": context_key([{}] if offers else [], status), "observed_outcomes": counts,
            "walkout_proportion_interval": interval,
            "limitation": "Few, non-independent past exchanges. This interval is descriptive, not predictive."}


def action_consequences(th, terms, current, current_cost, candidate_cost, opening_cost, exit_cost, status):
    quote = current.get("unit_price") or th.reference["unit_price"]
    th.beliefs.standing_terms = dict(current)
    probabilities = {k: sum(p.weight * th.beliefs.probabilities(terms, p, quote, th.repeats)[k]
                            for p in th.beliefs.particles) for k in ("accept", "counter", "walk")}
    secured = max(0.0, opening_cost - current_cost)
    target = max(0.0, opening_cost - candidate_cost)
    gain, loss = target - secured, secured
    denominator = max(0, gain) + loss
    expected_gain = probabilities["accept"] * gain - probabilities["walk"] * loss
    return {"gain_if_exact_package_agreed_eur": round(gain, 2),
            "secured_improvement_at_risk_eur": round(loss, 2),
            "target_improvement_eur": round(target, 2),
            "optimistic_break_even_walkout_probability": round(max(0, gain) / denominator, 4)
            if denominator else None,
            "response_estimates_uncalibrated": {k: round(v, 4) for k, v in probabilities.items()},
            "partial_accept_walk_value_eur": round(expected_gain, 2),
            "counteroffer_future_value": "not numerically estimated; Astra must plan this branch explicitly",
            "not_total_expected_value": True,
            "cash_cost_if_offer_lost_eur": round(exit_cost - current_cost, 2),
            "final_offer_warning": status == "final_offer"}


def add_action_consequences(agent, board):
    for sid, supplier in board["suppliers"].items():
        th = agent.threads[sid]
        # Other current suppliers are legitimate alternatives; old quotes are not.
        alternatives = [board["fallback_estimated_cost_eur"]] + [
            s["standing"]["expected_total_eur"] for other, s in board["suppliers"].items()
            if other != sid and s.get("standing")]
        exit_cost = min(alternatives)
        standing = supplier.get("standing")
        baseline = standing or supplier["opening_comparison"]
        supplier["continuation_risk"] = {
            "current_offer_executable": bool(standing), "outside_option_cost_eur": round(exit_cost, 2),
            "cash_loss_if_offer_lost_eur": round(exit_cost - baseline["expected_total_eur"], 2) if standing else None,
            "secured_improvement_at_risk_eur": round(max(0, supplier["opening_comparison"]["expected_total_eur"]
                                                         - baseline["expected_total_eur"]), 2),
            "objective_warning": "Cash fallback loss is business context, NOT Arena score loss. The only "
                                 "negotiation reward at risk is improvement already secured. Accepting an "
                                 "unchanged opening offer locks in zero improvement; a feasible beneficial "
                                 "counter may still earn improvement even when the fallback is expensive.",
            "final_offer_warning": supplier["status"] == "final_offer",
            "offer_history": context_evidence(th, supplier["status"]),
            "question_history": context_evidence(th, supplier["status"], offers=False),
            "forecast_limitations": "Package response estimates omit final-warning hazard. Break-even assumes "
                                    "EVERY non-walkout wins the target. Expected gain assumes counters preserve "
                                    "the current offer; reality can be worse. No guarantee that it stays available.",
            "decision_rule": "At a final warning or repeated unchanged offers, continuation needs an explicit "
                             "gain/loss justification. Remaining moves are not permission from the supplier. "
                             "For questions, identify the answer that would change the decision. Astra decides."}
        for package in board["packages"].values():
            if package["supplier_id"] == sid:
                package["next_action"] = action_consequences(
                    th, package["terms"], baseline["terms"], baseline["expected_total_eur"],
                    package["expected_total_eur"], supplier["opening_comparison"]["expected_total_eur"],
                    exit_cost, supplier["status"])
