"""Astra chooses the final action. Python supplies arithmetic and protocol checks.

There is deliberately no expected-utility veto, cheap-quote shortcut or automatic
acceptance on this path. Supplier response estimates are advisory, uncalibrated
evidence. Only current, received standing IDs can be accepted.
"""

import copy
import json
import time

from arena_kit.cost import complete_offer, cost_breakdown
from arena_kit.play import latest, live_threads, moves_left

from .. import compliance
from .communication import describe_complete, render_reply, reply_facts
from .deliberation import add_action_consequences, economics_context, objective_scope


class FinalDecisionUnavailable(RuntimeError):
    """No valid Astra authorization: send nothing rather than silently replace it."""


def quantile(values, weights, q):
    accumulated = 0.0
    for value, weight in sorted(zip(values, weights, strict=True)):
        accumulated += weight
        if accumulated >= q:
            return round(value, 2)
    return round(max(values), 2)


def cost_card(agent, case, th, terms):
    """One consistent distribution for both Astra roles and the audit log."""
    if hasattr(th, "economics"):
        card = th.economics.card(terms)
        if not objective_scope(case)["relationship_cost_active"]:
            card.pop("supplier_margin_pct_range", None)
            card.pop("public_cost_scenario", None)
        return card
    direct = cost_breakdown(case, terms, th.std)
    samples = [cost_breakdown(case, terms, th.std, {**th.sup, "full_cost": p.full_cost})
               for p in th.beliefs.particles]
    weights = [p.weight for p in th.beliefs.particles]
    expected = {k: sum(w * b[k] for w, b in zip(weights, samples, strict=True)) for k in direct}
    costs = [sum(b.values()) for b in samples]
    return {
        "direct_cost_eur": round(sum(direct.values()), 2),
        "expected_total_eur": round(sum(expected.values()), 2),
        "expected_breakdown_eur": {k: round(v, 2) for k, v in expected.items()},
        "total_p10_p90_eur": [quantile(costs, weights, q) for q in (0.1, 0.9)],
        "uncertainty": "Published buyer formula; relationship cost uses uncertain supplier-cost estimates. "
                       "Expected cost is not a supplier quote or a predicted Arena score.",
    }


def standing_sheet(events):
    reply = latest(events)
    sheets = reply.get("term_sheets", [])
    active = reply.get("standing_offer_id")
    return next((s for s in sheets if s.get("term_sheet_id") == active), None) if active else (
        sheets[0] if sheets else None
    )


def valid_offer(agent, case, th, terms):
    try:
        return (isinstance(terms, dict) and set(terms) == set(case["negotiable"])
                and agent.valid(case, th, terms)
                and not compliance.problems(case, {"body": "Proposed package.", "term_sheets": [{"terms": terms}]},
                                            {}, standard=th.std))
    except (TypeError, ValueError, KeyError, ArithmeticError):
        return False


def questions(case, sources, history):
    """Questions are available without pretending the supplier has promised anything."""
    fields, opts = case["negotiable"], case.get("term_options", {})
    items = []
    if "payment_days" in fields and len(opts.get("payment_days", [])) > 1:
        days = ", ".join(str(x) for x in opts["payment_days"])
        items.append(("payment_quotes", f"Please quote comparable complete packages with payment at {days} days, "
                      "keeping the other terms unchanged. What exact price reduction would earlier payment buy?"))
    if "index_clause" in fields and any(opts.get("index_clause", [])):
        items.append(("index_rebase", "Please quote a fixed-price package and an indexed alternative with its "
                      "corresponding rebased unit price, removing raw-material increases already covered by the "
                      "clause. State the series, base month, material share and deadband. This inquiry accepts "
                      "neither indexation nor a price. Please confirm whether the existing offer remains available."))
    text = " ".join(sources.values()).lower()
    if any(w in text for w in ("hourly", "calculation", "material", "cost", "kalkulation", "stundensatz")):
        items.append(("cost_walkthrough", "Could we review the material basis, processing quantities and hourly "
                      "rates behind your price, separating base costs from surcharges? Which assumption could "
                      "we change together to improve the complete package?"))
    if any(w in text for w in ("approval", "committee", "freigabe", "genehmigung", "management")):
        items.append(("approval_route", "What evidence and package would support approval of a larger reduction? "
                      "Could you take the proposal to the responsible decision-maker and explain the approval steps?"))
    if history:
        items.append(("revisit_history", "Could you confirm which pricing structures discussed previously are "
                      "available now, and provide updated complete quotes for comparison? Earlier discussions "
                      "are not being treated as current offers or acceptance."))
    items.append(("trade_priority", "Which permitted term change would allow the largest price improvement? "
                  "Please quantify the exchange in a complete alternative quote while keeping the existing "
                  "offer available for comparison."))
    return items


def build_board(agent, case, threads, source_map, history_map, closing_only=False):
    """Expose feasible actions, not a Python-selected winner. No guessed probability pruning."""
    board = {
        "case": {k: case.get(k) for k in ("case_id", "title", "briefing", "negotiable", "term_options",
                                         "fixed_terms", "buyer")},
        "instructions": {
            "response_forecasts": "UNCALIBRATED estimates from sparse observations; never ground truth.",
            "history": "Past same-supplier/same-case exchanges; quotes need fresh confirmation.",
            "agreed": "Supplier agreement is an executable offer, not an obligation to accept.",
            "confirmation": "Confirming a quote establishes its status; it does not close the case.",
            "closing_only": closing_only,
            "weights": "Use the published buyer costs, including relationship costs. Do not invent score weights.",
            "sustainability": "ONLY when objective_scope.relationship_cost_active is true: compare public "
                              "should-cost, practice-calibrated interval and downside. Acceptance is not "
                              "profitability. Otherwise do not add a supplier-margin objective.",
            "comparisons": "Negative cost delta means cheaper, using shared cost scenarios. Historical "
                           "and opening packages are not executable unless freshly confirmed. "
                           "Scenario ranges and means are modelling assumptions, not calibrated probabilities.",
        },
        "objective_scope": objective_scope(case),
        "reply_facts": reply_facts(case),
        "fallback_estimated_cost_eur": agent.alternatives(case),
        "suppliers": {}, "packages": {}, "actions": {}, "evidence": {}, "questions": {},
    }
    for sid in live_threads(threads):
        th, events = agent.threads[sid], threads[sid]
        source = source_map.get(sid, {})
        history = history_map.get(sid, [])
        current_sheet = standing_sheet(events)
        current = current_sheet["terms"] if current_sheet else th.reference
        remaining = moves_left(case, events)
        supplier = {
            "status": latest(events).get("status"), "remaining_moves": remaining,
            "sources": source, "past_exchanges": history,
            "recent_exchange": [{k: e.get(k) for k in ("from", "body", "term_sheets", "status")}
                                for e in events[-6:]],
            "beliefs": th.beliefs.summary(), "previous_buyer_terms": th.last_terms,
            "asked_questions": sorted(th.asked_quotes),
            "supplier_economics": economics_context(case, th),
            "stagnant_replies": th.stagnation,
            "observed_response_counts": th.response_counts,
            "previous_practice_outcomes": th.economics.feedback[-6:],
            "opening_comparison": {"terms": complete_offer(case, th.reference),
                                   **cost_card(agent, case, th, th.reference),
                                   "currently_executable": False},
        }
        board["suppliers"][sid] = supplier
        facts = {**(agent.package.facts if agent.package else {}), **case.get("facts", {})}
        for i, claim in enumerate(th.dossier.claims):
            if all(r in facts for r in claim.refs):
                board["evidence"][f"{sid}:e{i}"] = {"supplier_id": sid, "text": claim.sentence,
                                                   "refs": claim.refs,
                                                   "already_used": bool(set(claim.refs) & th.used)}

        keys = {}

        def add_package(terms, origin, th=th, sid=sid, keys=keys):
            if not valid_offer(agent, case, th, terms):
                return None
            key = json.dumps(terms, sort_keys=True)
            if key in keys:
                return keys[key]
            pid = f"{sid}:p{len(keys)}"
            keys[key] = pid
            card = cost_card(agent, case, th, terms)
            card.pop("uncertainty", None)  # Shared warning above; avoid repeating it per package.
            board["packages"][pid] = {
                "supplier_id": sid, "terms": terms, "origin": origin, **card,
                "versus_standing": th.economics.compare(terms, current),
                "versus_opening": th.economics.compare(terms, th.reference),
            }
            return pid

        if current_sheet and agent.valid(case, th, current):
            supplier["standing"] = {"term_sheet_id": current_sheet["term_sheet_id"], "terms": current,
                                     **cost_card(agent, case, th, current),
                                     "versus_opening": th.economics.compare(current, th.reference)}
            supplier["standing_vs_previous_practice"] = [
                {"session_id": f["session_id"], "terms_then": f["terms"],
                 "actual_total_then_eur": round(sum(f["actual_components_eur"].values()), 2),
                 "current_minus_historical_actual_eur": round(
                     supplier["standing"]["expected_total_eur"] - sum(f["actual_components_eur"].values()), 2),
                 "paired_scenario_comparison": th.economics.compare(current, f["terms"]),
                 "currently_executable": False}
                for f in th.economics.feedback[-6:]
            ]
            # Even an expensive deal is shown: cost is a decision for Astra, not a Python veto.
            board["actions"][f"{sid}:accept"] = {"supplier_id": sid, "kind": "accept",
                                                 "term_sheet_id": current_sheet["term_sheet_id"]}
        board["actions"][f"{sid}:walk"] = {"supplier_id": sid, "kind": "walk_away"}
        if closing_only or remaining <= 1:
            continue
        if remaining >= 3:
            board["actions"][f"{sid}:reply"] = {"supplier_id": sid, "kind": "reply"}
        for kind, body in questions(case, source, history):
            if kind in th.asked_quotes:
                continue
            qid = f"{sid}:{kind}"
            board["questions"][qid] = {"supplier_id": sid, "kind": kind, "body": body}
            # Leave a reply and a closing move after a standalone question.
            if remaining >= 3:
                board["actions"][qid] = {"supplier_id": sid, "kind": "ask", "question_id": qid}
        for sheet in latest(events).get("term_sheets", []):
            if current_sheet and sheet["term_sheet_id"] == current_sheet["term_sheet_id"]:
                continue
            terms = {f: sheet["terms"][f] for f in case["negotiable"] if f in sheet["terms"]}
            pid = add_package(terms, "current supplier indicative quote; not directly acceptable")
            if pid and json.dumps(terms, sort_keys=True) not in th.asked_confirmations:
                board["actions"][f"{sid}:confirm:{pid}"] = {
                    "supplier_id": sid, "kind": "confirm", "package_id": pid,
                    "source_sheet_id": sheet["term_sheet_id"],
                }
        seeds = th.analyst_candidates[:3] + [complete_offer(case, current)]
        if th.last_terms:
            seeds.append(th.last_terms)
        # Include history as explicitly unconfirmed proposals, not executable sheet IDs.
        for episode in history:
            for sheet in episode["quoted_packages_then"]:
                terms = {f: sheet["terms"][f] for f in case["negotiable"] if f in sheet["terms"]}
                add_package(terms, "historical quote: must renegotiate/reconfirm")
        for row in th.sustainability_candidates:
            add_package(row["terms"], row["origin"])
        for seed in seeds:
            base_id = add_package(seed, "Astra proposal" if seed in th.analyst_candidates else "current/previous terms")
            if not base_id:
                continue
            target = board["packages"][base_id]["direct_cost_eur"]
            for field in case["negotiable"]:
                if field == "unit_price":
                    continue
                for option in case.get("term_options", {}).get(field, []):
                    if option == seed.get(field):
                        continue
                    variant = {**seed, field: option}
                    pid = add_package(variant, f"same-price sensitivity: change only {field}")
                    if not pid:
                        continue
                    board["packages"][pid]["direct_delta_from_base_eur"] = round(
                        board["packages"][pid]["direct_cost_eur"] - target, 2)
                    # Pair the concession with a compensating price, not a free gift.
                    # The published direct formula is affine in price; uncertain relationship
                    # effects are priced separately in the resulting card, never hidden.
                    zero = sum(cost_breakdown(case, {**variant, "unit_price": 0.01}, th.std).values())
                    one = sum(cost_breakdown(case, {**variant, "unit_price": 1.01}, th.std).values())
                    if one > zero:
                        price = round(0.01 + (target - zero) / (one - zero), 2)
                        paired = add_package({**variant, "unit_price": price},
                                             f"exchange for {base_id}; approximately equal direct buyer cost")
                        if paired:
                            board["packages"][paired]["paired_with"] = base_id
        if keys:
            board["actions"][f"{sid}:counter"] = {"supplier_id": sid, "kind": "counter",
                                                  "package_ids": list(keys.values()), "max_packages": 3}
    add_action_consequences(agent, board)
    return board


def validate_selection(board, selection):
    if not isinstance(selection, dict) or set(selection) != {
        "action_id", "package_ids", "question_id", "evidence_ids", "tone", "rationale",
        "reply_text", "continuation_review",
    }:
        raise ValueError("invalid final decision shape")
    action = board["actions"].get(selection["action_id"])
    if not action:
        raise ValueError("unknown final action")
    sid = action["supplier_id"]
    ids = selection["package_ids"]
    if not isinstance(ids, list) or len(ids) > 3 or len(set(ids)) != len(ids):
        raise ValueError("invalid package selection")
    if action["kind"] == "counter":
        if not ids or any(pid not in action["package_ids"] for pid in ids):
            raise ValueError("counter requires this supplier's validated packages")
    elif ids:
        raise ValueError("packages only allowed on counter")
    qid = selection["question_id"]
    if qid and (qid not in board["questions"] or board["questions"][qid]["supplier_id"] != sid
                or action["kind"] != "counter"):
        raise ValueError("question belongs to another supplier or action")
    evidence = selection["evidence_ids"]
    if not isinstance(evidence, list) or len(evidence) > 3 or len(set(evidence)) != len(evidence):
        raise ValueError("invalid evidence selection")
    if any(e not in board["evidence"] or board["evidence"][e]["supplier_id"] != sid for e in evidence):
        raise ValueError("unverified evidence")
    if evidence and action["kind"] != "counter":
        raise ValueError("evidence only allowed on counter")
    if selection["tone"] not in ("warm", "cooperative", "firm"):
        raise ValueError("invalid tone")
    if not isinstance(selection["rationale"], str) or not selection["rationale"].strip():
        raise ValueError("missing final rationale")
    review = selection["continuation_review"]
    if not isinstance(review, dict) or set(review) != {
        "target_package_id", "walkout_probability_low", "walkout_probability_high",
        "risk_reason", "information_needed", "stop_condition",
    }:
        raise ValueError("missing continuation risk review")
    low, high = review["walkout_probability_low"], review["walkout_probability_high"]
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)) or not 0 <= low <= high <= 1:
        raise ValueError("invalid subjective walkout range")
    target = review["target_package_id"]
    if target and (target not in board["packages"] or board["packages"][target]["supplier_id"] != sid):
        raise ValueError("invalid risk-review target")
    if action["kind"] == "counter" and target not in ids:
        raise ValueError("risk review must refer to a selected package")
    if action["kind"] == "confirm" and target != action["package_id"]:
        raise ValueError("confirmation risk review must refer to its package")
    if not all(isinstance(review[k], str) and review[k].strip() for k in ("risk_reason", "stop_condition")):
        raise ValueError("risk reason and stopping condition are required")
    if action["kind"] in ("ask", "reply") and not review["information_needed"].strip():
        raise ValueError("a question needs an explicit decision-relevant information goal")
    if action["kind"] not in ("accept", "walk_away"):
        render_reply(selection["reply_text"], board["reply_facts"])
    return action


def execute(agent, case, threads, board, selection):
    """Render exactly the approved action; no reranking, fallback or term substitutions."""
    action = validate_selection(board, selection)
    sid, kind = action["supplier_id"], action["kind"]
    th, events = agent.threads[sid], threads[sid]
    if kind == "accept":
        live_sheet = standing_sheet(events)
        if not live_sheet or live_sheet["term_sheet_id"] != action["term_sheet_id"]:
            raise ValueError("stale standing offer")
        if not agent.valid(case, th, live_sheet["terms"]):
            raise ValueError("invalid standing offer")
        message = {"action": {"type": "accept", "term_sheet_id": action["term_sheet_id"]}}
    elif kind == "walk_away":
        message = {"action": {"type": "walk_away"}}
    else:
        offers = []
        authored = render_reply(selection["reply_text"], board["reply_facts"])
        if kind == "reply":
            body = authored
            th.pending = {"kind": "quote_request", "event_count": len(events)}
        elif kind == "ask":
            question = board["questions"][action["question_id"]]
            body = authored
            th.asked_quotes.add(question["kind"])
            th.pending = {"kind": "quote_request", "request": question, "event_count": len(events)}
        elif kind == "confirm":
            offers = [board["packages"][action["package_id"]]["terms"]]
            body = authored + "\n\n" + describe_complete(case, offers[0], th.std)
            th.asked_confirmations.add(json.dumps(offers[0], sort_keys=True))
            th.pending = {"kind": "quote_confirmation", "request": action, "event_count": len(events)}
        else:
            offers = [board["packages"][pid]["terms"] for pid in selection["package_ids"]]
            claims = [board["evidence"][eid] for eid in selection["evidence_ids"]]
            qid = selection["question_id"]
            question = board["questions"][qid]["body"] if qid else ""
            body = "\n\n".join(x for x in [authored, *[c["text"] for c in claims], *[
                f"Package {i + 1}: {describe_complete(case, offer, th.std)}."
                for i, offer in enumerate(offers)
            ], "These are alternative complete packages, not cumulative concessions." if len(offers) > 1 else "",
                question] if x)
            for claim in claims:
                th.used.update(claim["refs"])
            if qid:
                th.asked_quotes.add(board["questions"][qid]["kind"])
            quote = (standing_sheet(events) or {}).get("terms", th.reference).get("unit_price")
            forecasts = [th.beliefs.probabilities(max(offers, key=lambda t: th.beliefs.value(t, p)), p, quote)
                         for p in th.beliefs.particles]
            probabilities = {k: agent.weighted(th, [pr[k] for pr in forecasts]) for k in ("accept", "counter", "walk")}
            th.last_terms, th.last_price = offers[0], offers[0]["unit_price"]
            th.pending = {"terms": offers[0], "offers": offers, "quote": quote, "repeats": th.repeats,
                          "event_count": len(events), "probabilities": probabilities}
        if any(not valid_offer(agent, case, th, t) for t in offers):
            raise ValueError("final offer violates constraints")
        message = {"subject": "Re: " + case["title"], "body": body,
                   "term_sheets": [{"terms": t} for t in offers]}
        facts = {**(agent.package.facts if agent.package else {}), **case.get("facts", {})}
        if compliance.problems(case, message, facts, standard=th.std):
            raise ValueError("final message violates constraints")
    decision = {"supplier_id": sid, "message": message}
    agent.log("decision", {"authority": "astra", "kind": kind, "selection": selection,
                           "action": decision, "llm_calls": agent.router.calls}, sid)
    agent.router.calls = []
    return decision


def decide(agent, case, threads, deadline, closing_only=False):
    sources, history = {}, {}
    for sid in live_threads(threads):
        sources[sid] = agent.sources(sid, threads[sid])
        history[sid] = agent.threads[sid].episodes
    # One negotiator call per turn. The final reviewer sees all suppliers and chooses
    # independently. Reserve time for it instead of spending the window on grid search.
    viable = [sid for sid in live_threads(threads) if moves_left(case, threads[sid]) > 1]
    if viable and not closing_only:
        sid = min(viable, key=lambda s: sum(e.get("from") == "buyer" for e in threads[s]))
        agent.interpret(case, sid, threads[sid], min(deadline - 14, time.monotonic() + 17))
    board = build_board(agent, case, threads, sources, history, closing_only)
    if not board["actions"]:
        raise FinalDecisionUnavailable("No remaining valid action")
    agent.log("final_board", board)
    try:
        choice = agent.router.final_decision(copy.deepcopy(board), deadline)
        # Validate twice: schema membership and actual current state at execution.
        validate_selection(board, choice)
        return execute(agent, case, threads, board, choice)
    except (ValueError, KeyError, TypeError, ArithmeticError, TimeoutError, FinalDecisionUnavailable) as exc:
        agent.log("final_decision_failed", {"error_type": type(exc).__name__, "sent": False,
                                            "llm_calls": agent.router.calls})
        raise FinalDecisionUnavailable("Astra did not authorize a valid action; no substitute was sent") from None
