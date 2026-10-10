"""Learn from observed replies, not agreement labels or terminal score values."""

import hashlib
import json

from arena_kit.cost import closing_terms

from .offers import echoed_proposal


def same_terms(case, standard, left, right):
    if not left or not right:
        return False
    # Compare the complete package INCLUDING price, index details and fixed terms.
    return closing_terms(case, left, standard) == closing_terms(case, right, standard)


def response_label(case, standard, offers, previous, reply):
    sheets = reply.get("term_sheets") or []
    active = reply.get("standing_offer_id")
    sheet = next((s for s in sheets if s.get("term_sheet_id") == active), {}) if active else (
        sheets[0] if sheets else {})
    returned = sheet.get("terms", {})
    status = reply.get("status")
    matched = next((p for p in offers if same_terms(case, standard, p, returned)), None)
    if status in ("walked_away", "no_bid"):
        label = "walkout"
    elif same_terms(case, standard, previous, returned):
        label = "unchanged_offer"
    elif matched is not None and status in ("agreed", "final_offer"):
        label = "accepted_proposal"
    elif returned:
        label = "counteroffer"
    else:
        label = "information_only"
    return label, returned, matched


def context_key(offers, previous_status):
    return ("offer" if offers else "question") + ("_after_final" if previous_status == "final_offer" else "")


def learn_reply(case, th, request, reply, event_id, previous=None, previous_status=None, repeats=0):
    """Shared live/reconstruction path; no model calls, simulations or score inputs."""
    if event_id in th.feedback_seen or request.get("action"):
        return None
    th.feedback_seen.add(event_id)
    offers = [s["terms"] for s in request.get("term_sheets", []) if s.get("terms")]
    previous = previous if previous is not None else th.last_supplier_terms
    label, returned, matched = response_label(case, th.std, offers, previous, reply)
    context = context_key(offers, previous_status)
    counts = th.response_counts.setdefault(context, {})
    counts[label] = counts.get(label, 0) + 1
    outcome = "walk" if label == "walkout" else "accept" if label == "accepted_proposal" else "counter"
    th.beliefs.standing_terms = dict(previous)
    quote = previous.get("unit_price") or th.reference["unit_price"]
    prediction = None
    if offers and label != "information_only":
        prediction = {
            k: sum(p.weight * th.beliefs.probabilities(
                max(offers, key=lambda t: th.beliefs.value(t, p)), p, quote, repeats)[k]
                   for p in th.beliefs.particles) for k in ("accept", "counter", "walk")}
        th.beliefs.update(event_id, offers, outcome, quote, repeats)
        if label in ("accepted_proposal", "counteroffer"):
            echoed = matched or echoed_proposal(case, th.std, offers, returned)
            if echoed:
                th.beliefs.learn_choice(event_id, echoed, offers)
            th.beliefs.learn_counteroffer(event_id, previous, returned, echoed or offers[0])
    # Questions also consume patience; their walkouts are recorded separately and
    # must not be mislabelled as rejections of a price never offered.
    if returned:
        th.last_supplier_terms = dict(returned)
        th.beliefs.standing_terms = dict(returned)
    th.stagnation = th.stagnation + 1 if label == "unchanged_offer" else 0
    th.repeats = th.stagnation
    th.last_outcome = outcome
    return {"label": label, "outcome": outcome, "context": context,
            "response": reply, "prediction": prediction,
            "exact_proposal_match": matched is not None,
            "brier": sum((prediction[k] - float(outcome == k)) ** 2 for k in prediction)
            if prediction else None}


def event_key(session, request, reply):
    # Message IDs separate identical successive replies; content is a fallback.
    return hashlib.sha256(json.dumps([session, request, reply], sort_keys=True).encode()).hexdigest()
