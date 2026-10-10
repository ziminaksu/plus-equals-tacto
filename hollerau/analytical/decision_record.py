"""Linked decision plans and observed replies; forecasts are never treated as facts."""

import hashlib
import json
import math

from .feedback import response_label

REPLIES = ("accepted_proposal", "counteroffer", "unchanged_offer", "information_only", "walkout", "closed")


def phase(supplier, action=None):
    if (action or {}).get("kind") in ("accept", "walk_away") or supplier.get("status") == "final_offer":
        return "close"
    return "open" if not supplier.get("buyer_messages_sent") else "exchange"


def validate_plan(board, action, selection):
    plan = selection.get("plan")
    fields = {"expected_response", "expected_price_low", "expected_price_high", "basis_source_ids",
              "basis", "if_counteroffer", "if_unchanged", "if_accepted", "if_walkout",
              "rejected_alternative_id", "why_not_alternative", "revision_from_previous"}
    if not isinstance(plan, dict) or set(plan) != fields or plan["expected_response"] not in REPLIES:
        raise ValueError("missing structured negotiation plan")
    closing = action["kind"] in ("accept", "walk_away")
    if (plan["expected_response"] == "closed") != closing:
        raise ValueError("plan must distinguish closing from a supplier response")
    low, high = plan["expected_price_low"], plan["expected_price_high"]
    if (low is None) != (high is None):
        raise ValueError("prediction price bounds must both be supplied or null")
    if low is not None:
        if (any(isinstance(n, bool) or not isinstance(n, (float, int)) or not math.isfinite(n) for n in (low, high))
                or not 0 < low <= high or closing):
            raise ValueError("invalid forecast price interval")
    refs = plan["basis_source_ids"]
    supplier = board["suppliers"][action["supplier_id"]]
    available = set(supplier["sources"]) | {h["source_id"] for h in supplier["past_exchanges"]}
    available |= {k for k, e in board["evidence"].items() if e["supplier_id"] == action["supplier_id"]}
    if not isinstance(refs, list) or len(refs) > 3 or any(r not in available for r in refs):
        raise ValueError("plan must cite available evidence or explicitly use an assumption")
    alternate = plan["rejected_alternative_id"]
    if alternate and (alternate not in board["packages"] and alternate not in board["actions"]):
        raise ValueError("unknown rejected alternative")
    if alternate and (alternate == selection["action_id"] or alternate in selection["package_ids"]):
        raise ValueError("rejected alternative cannot be the selected move")
    for key in ("basis", "if_counteroffer", "if_unchanged", "if_accepted", "if_walkout",
                "why_not_alternative", "revision_from_previous"):
        if not isinstance(plan[key], str) or not plan[key].strip() or len(plan[key]) > 900:
            raise ValueError("plan needs concise, nonempty conditional decisions")


def record_decision(agent, case, board, selection, decision, board_event_id, started, timings):
    action = board["actions"][selection["action_id"]]
    sid = action["supplier_id"]
    supplier = board["suppliers"][sid]
    did = f"{agent.run_id}:{agent.session_id or case['case_id']}:{agent.turn}:{sid}"
    record = {
        "decision_id": did, "board_event_id": board_event_id, "phase": phase(supplier, action),
        "case": board["case"], "state": {k: supplier.get(k) for k in
            ("status", "remaining_moves", "buyer_messages_sent", "standing", "previous_buyer_terms")},
        "evidence": {"observed_source_ids": list(supplier["sources"]),
                     "historical_source_ids": [h["source_id"] for h in supplier["past_exchanges"]],
                     "assumptions": board["policy_rules"],
                     "estimates": {"beliefs": supplier["beliefs"], "economics": supplier["supplier_economics"]}},
        "options": {"count": len(board["packages"]), "all_options_in_board_event": board_event_id,
                    "selected": {p: board["packages"][p] for p in selection["package_ids"]},
                    "generation": board["candidate_generation"]},
        "plan": selection["plan"], "selection": selection,
        "authorized_action": decision, "execution_status": "authorized_not_yet_sent",
        "timing": timings, "model_calls": list(agent.router.calls),
        "board_sha256": hashlib.sha256(json.dumps(board, sort_keys=True).encode()).hexdigest(),
    }
    th = agent.threads[sid]
    th.active_plan = {"decision_id": did, "plan": selection["plan"],
                      "previous_terms": (supplier.get("standing") or supplier["opening_comparison"])["terms"],
                      "request": decision["message"]}
    agent.log("decision_record", record, sid)
    return record


def observe_plan(agent, case, sid, reply, learned=None):
    th = agent.threads[sid]
    active = getattr(th, "active_plan", None)
    if not active:
        return
    request, plan = active["request"], active["plan"]
    offers = [s["terms"] for s in request.get("term_sheets", [])]
    label, terms, _ = response_label(case, th.std, offers, active["previous_terms"], reply)
    price = terms.get("unit_price")
    low, high = plan["expected_price_low"], plan["expected_price_high"]
    price_match = low <= price <= high if low is not None and isinstance(price, (float, int)) else None
    outcome = {"decision_id": active["decision_id"], "phase": "learn",
               "observed_response": label, "expected_response": plan["expected_response"],
               "response_matched": label == plan["expected_response"], "price_within_forecast": price_match,
               "actual_reply": reply, "actual_terms": terms,
               "changed_terms": {k: {"before": active["previous_terms"].get(k), "after": v}
                                 for k, v in terms.items() if active["previous_terms"].get(k) != v},
               "belief_update_recorded": bool(learned), "observation_label": (learned or {}).get("label"),
               "forecast_status": "subjective forecast compared with observation, not calibrated probability"}
    outcome["requires_plan_revision"] = not outcome["response_matched"] or price_match is False
    th.last_plan_outcome = outcome
    th.previous_plan = plan
    th.active_plan = None
    agent.log("plan_outcome", outcome, sid)


def finish_plan(agent, case, result):
    for sid, th in agent.threads.items():
        active = getattr(th, "active_plan", None)
        if not active:
            continue
        is_closing = bool(active["request"].get("action"))
        # A result without a supplier reply cannot establish acceptance of a proposal
        # or a walkout. Preserve the missing observation instead of inventing one.
        agent.log("plan_outcome", {
            "decision_id": active["decision_id"], "phase": "learn",
            "observed_response": "closed" if is_closing else "unobserved_terminal_response",
            "expected_response": active["plan"]["expected_response"],
            "response_matched": active["plan"]["expected_response"] == "closed" if is_closing else None,
            "actual_result": {k: result.get(k) for k in ("deal", "supplier_id", "terms", "end_reason")},
            "belief_update_recorded": False,
        }, sid)
        th.active_plan = None
