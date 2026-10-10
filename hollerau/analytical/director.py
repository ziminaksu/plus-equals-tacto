"""Astra chooses the final action. Python supplies arithmetic and protocol checks.

There is deliberately no expected-utility veto, cheap-quote shortcut or automatic
acceptance on this path. Supplier response estimates are advisory, uncalibrated
evidence. Only current, received standing IDs can be accepted.
"""

import copy
import json
import os
import time

from arena_kit.cost import complete_offer, cost_breakdown, total_cost
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


def data_anchors(case, th, current):
    """Packages below the supplier's ask, priced from our own data, on the levers that cost us least.
    Without them the board only held prices near the supplier's numbers (P18: nothing below 5.70,
    while the supplier later accepted 5.50 and the arena's best package was ~4.73)."""
    quote = (current or th.reference).get("unit_price")
    if not quote:
        return []
    # near-ask anchors too: with a relationship penalty deep cuts are worthless (P02: 297-349 on the
    # board, the supplier agreed at once to 361 = -2.7 % with 90 days and a deadband-5 copper clause)
    prices = {round(quote * m, 2) for m in (0.80, 0.85, 0.90, 0.94, 0.96, 0.97, 0.98)}
    refs = dict(getattr(th.dossier, "reference_prices", {}) or {})
    if case["buyer"].get("current_unit_price"):
        refs["current_price"] = case["buyer"]["current_unit_price"]
    prices |= {round(p, 2) for p in refs.values() if p and p < quote}
    fields, opts = case["negotiable"], case.get("term_options", {})
    base = complete_offer(case, current or th.reference)
    best = dict(base)
    pay = [d for d in opts.get("payment_days", []) if d >= case["buyer"]["reference_payment_days"]]
    if "payment_days" in fields and pay:
        best["payment_days"] = max(pay)  # never pay earlier than our reference for free
    if "effective_date" in fields and opts.get("effective_date"):
        best["effective_date"] = max(opts["effective_date"])  # the current price for longer (P01: +5 months)
    months = 12 * case["buyer"]["horizon_years"]
    if "contract_months" in fields and months in opts.get("contract_months", []):
        best["contract_months"] = months  # cover the horizon, no more
    variants = [best]
    if "index_clause" in fields:
        clauses = opts.get("index_clause", [])
        if None in clauses:
            variants.append({**best, "index_clause": None})
        banded = [c for c in clauses if c]
        if banded:
            variants.append({**best, "index_clause": max(banded, key=lambda c: c.get("deadband_pct") or 0)})
    out, seen = [], set()
    for v in variants:
        for price in sorted(prices):
            terms = {**v, "unit_price": price}
            key = json.dumps(terms, sort_keys=True)
            if key not in seen:
                seen.add(key)
                out.append((terms, "data anchor: below the ask, from our order history and current price"))
    return out[:24]


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
            "anchoring": "A package a supplier agreed to at once was too generous: it is a ceiling to fall back "
                         "to, never an opening. The first offer sets the range: open with a 'data anchor' package "
                         "(our own order prices, below the ask) and concede in steps against the supplier's moves. "
                         "Suppliers answer a low but data-backed first offer with a counter, not a walk-out; repeating "
                         "a previously accepted package forfeits everything below it. While the supplier's status is 'open' "
                         "and three or more moves remain, do not accept its first counter: answer with a smaller "
                         "step (a data anchor between your last offer and its counter, or a lever it values). In our "
                         "practice history suppliers walked only after a push past a final offer or after a timeout, "
                         "never after an ordinary step while 'open'.",
            "concession_ladder": "Suppliers give nothing without a move from us and send a final offer soon after "
                                 "we stop moving (P18: every final came one or two messages after a repeated or "
                                 "near-repeated offer). Plan the remaining moves as a ladder: in EACH counter make "
                                 "one real move: EITHER a lever toward the supplier (payment 90 -> 60 -> 45 -> 30 days, a "
                                 "longer contract, an index clause with a wide then narrower deadband) while keeping "
                                 "the price, OR a small price step while keeping the levers - choose the lever only "
                                 "when the supplier values it more than it costs us (see payment_days_value and the "
                                 "cost cards; P02: it priced 30 payment days at 1.35/unit, they cost us 2.47, so "
                                 "giving payment steps lost money). Add one or "
                                 "two UNUSED verified arguments. Keep a lever in reserve for every remaining step; "
                                 "do not give the whole lever at once. When the supplier quotes the same price for "
                                 "different values of a lever, that lever is worth nothing to it - keep our side. "
                                 "When a real move of ours produced NO price reduction, the desk has reached its own "
                                 "limit, not the company's: do not accept yet. Counter with a package it values that "
                                 "is free for us (a contract longer than our horizon costs us nothing; volume/"
                                 "commitment matters to suppliers focused on volume customers), add the share-of-business argument "
                                 "if it is on the board, attach the "
                                 "approval-route question so the desk takes it to its pricing committee/boss, and "
                                 "keep the price where it is. Accept only after the approver has answered or a "
                                 "final offer arrives.",
            "rfq_competition": "walk_away ends the WHOLE case for every supplier; with several live "
                               "suppliers it is not on the menu - simply stop answering a supplier you do not "
                               "need and close with the best one. With several suppliers, competition is the lever: cite a rival's live offer "
                               "(rival_offer evidence) to each other supplier and ask for a better complete "
                               "package; repeat as the best offer improves. Compare complete costs, not unit "
                               "price: payment days, lead time and quality change the total. Do not close while "
                               "a supplier that has not yet seen the best rival offer is still open.",
            "lock_in": "Accept a supplier's live offer when it is the best complete offer on the table AND either "
                       "its last step was 5 % or more, or - only with several suppliers or at most three moves "
                       "left - its price is within 3 % of our last offer (supplier.closeness). With one supplier "
                       "and moves left, a 1-2 % step is ordinary bargaining, not its limit (P01: accepted at "
                       "round 2 of 10, 0.51). A supplier that has just made a big step is at its limit: one more "
                       "push made it walk away (P05: 28.00 refused, 27.20 asked, supplier withdrew). This rule "
                       "outranks the 'do not accept while open' guidance.",
            "index_trade": "An index clause whose deadband is at least the case's expected index move "
                           "(buyer.index_paths) costs us only the index risk (index_risk_pct x material share), "
                           "while a supplier passing on raw-material costs values it highly. Offer it in the "
                           "FIRST counter together with our longest payment term in exchange for a lower base "
                           "price (P02: 361.00 / 90 days / copper clause with deadband 5 was agreed at once = 0.73, "
                           "while every price-only or payment-step path ended near 0.4). A clause with a deadband "
                           "below the expected move costs us the move itself - avoid it.",
            "effective_date": "When effective_date is negotiable, every month later keeps the CURRENT (lower) "
                              "price on that month's volume - in a price increase usually the most valuable lever. "
                              "Ask for the latest option from the first counter on and keep it; a letter giving "
                              "less notice than the contract requires is the argument for it (P01: the latest "
                              "date was worth about 27 k EUR, ~0.47 of the score).",
            "explicit_final_offer": "An explicit final offer is a closing decision. Astra may accept a currently valid standing quote or walk away, but must not counter or ask for more concessions.",
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
            "previous_continuation_review": th.continuation_review,
            "observed_response_counts": th.response_counts,
            "evidence_inventory": th.retrieval_inventory,
            "previous_practice_outcomes": th.economics.feedback[-6:],
            "opening_comparison": {"terms": complete_offer(case, th.reference),
                                   **cost_card(agent, case, th, th.reference),
                                   "currently_executable": False},
        }
        board["suppliers"][sid] = supplier
        facts = {**(agent.package.facts if agent.package else {}), **case.get("facts", {})}
        case_used = getattr(agent, "case_used", set())
        for i, claim in enumerate(th.dossier.claims + th.retrieved_claims):
            # A re-cited ID scores 'duplicate' and buys nothing (P18 rounds 2-3); an ID counts once per
            # CASE, so one cited to another supplier is spent too (P05: index evidence 'duplicate').
            if set(claim.refs) & (th.used | case_used):
                continue
            if all(r in facts for r in claim.refs):
                board["evidence"][f"{sid}:e{i}"] = {"supplier_id": sid, "text": claim.sentence,
                                                   "refs": claim.refs,
                                                   "already_used": bool(set(claim.refs) & th.used)}

        # How close is the supplier, and how big was its last step? (P05: Dralveck dropped 30.50 -> 28.00,
        # we pushed to 27.20 and it walked away; 28.00 would have scored ~0.82.)
        prices = [ts["terms"].get("unit_price") for m in events if m.get("from") != "buyer"
                  for ts in (m.get("term_sheets") or [])[:1] if ts["terms"].get("unit_price")]
        if current_sheet and th.last_terms and current.get("unit_price"):
            supplier["closeness"] = {
                "gap_to_our_last_offer_pct": round((current["unit_price"] / th.last_terms["unit_price"] - 1) * 100, 2),
                "its_last_step_pct": round((prices[-1] / prices[-2] - 1) * 100, 2) if len(prices) >= 2 else None,
            }
        # What is a payment day worth to THIS supplier? Two of its sheets that differ only in payment days
        # price it (P02: 369.50 @30 vs 370.85 @60 = 1.35/unit per 30 days, while 30 days are worth 2.47/unit
        # to us at 8 %). Then keep long payment and concede on price; trade payment only if it values it more.
        rates = []
        for m in events:  # alternatives in ONE message: across rounds the price also moved for other reasons
            if m.get("from") == "buyer":
                continue
            sheets = [ts["terms"] for ts in m.get("term_sheets") or []
                      if ts["terms"].get("unit_price") and ts["terms"].get("payment_days") is not None]
            for i, a in enumerate(sheets):
                for b2 in sheets[i + 1:]:
                    if a["payment_days"] != b2["payment_days"] and all(
                            a.get(k) == b2.get(k) for k in a if k not in ("unit_price", "payment_days")):
                        lo, hi = sorted((a, b2), key=lambda t: t["payment_days"])
                        days = hi["payment_days"] - lo["payment_days"]
                        rates.append((hi["unit_price"] - lo["unit_price"]) * 30 / days)
        if rates and current.get("unit_price"):
            theirs = sum(rates) / len(rates)
            ours = current["unit_price"] * case["buyer"]["interest_rate"] * 30 / 360
            supplier["payment_days_value"] = {
                "supplier_eur_per_unit_per_30_days": round(theirs, 2),
                "ours_eur_per_unit_per_30_days": round(ours, 2),
                "verdict": ("keep long payment on our side and concede on price instead" if theirs < ours
                            else "shortening payment is a good trade: it values cash more than we do"),
            }
        # RFQ: a rival's live offer is the strongest argument and counts once per supplier (P05: a
        # supplier asked "which figures is that competing offer based on?" and got none).
        mine = current_sheet["terms"] if current_sheet else None
        my_cost = total_cost(case, mine, th.std) if mine and mine.get("unit_price") else None
        for other in live_threads(threads):
            if other == sid:
                continue
            rival = standing_sheet(threads[other])
            if not rival or not rival["terms"].get("unit_price") or rival["term_sheet_id"] in th.used:
                continue
            r_cost = total_cost(case, rival["terms"], agent.threads[other].std)
            if my_cost is None or r_cost < my_cost - 0.01 or rival["terms"]["unit_price"] < mine["unit_price"]:
                board["evidence"][f"{sid}:rival:{other}"] = {
                    "supplier_id": sid, "kind": "rival_offer", "refs": [rival["term_sheet_id"]],
                    "text": f"We hold a competing complete offer at EUR {rival['terms']['unit_price']:.2f} per unit "
                            f"({rival['term_sheet_id']}).",
                    "already_used": False,
                }

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
        # walk_away ends the WHOLE case, every thread (P05: walking away from one RFQ supplier threw
        # away another's 27.50 = ~0.87). Offer it only when this is the last live supplier.
        if len(live_threads(threads)) == 1:
            board["actions"][f"{sid}:walk"] = {"supplier_id": sid, "kind": "walk_away"}
        if latest(events).get("status") == "final_offer":
            standing_cost = supplier.get("standing", {}).get("expected_total_eur")
            supplier["final_offer_decision"] = {
                "only_closing_actions": True,
                "standing_estimated_cost_eur": standing_cost,
                "fallback_estimated_cost_eur": board["fallback_estimated_cost_eur"],
                "estimated_fallback_loss_eur": (
                    round(board["fallback_estimated_cost_eur"] - standing_cost, 2)
                    if standing_cost is not None else None
                ),
                "warning": "A further counter risks losing the executable offer.",
            }
        if closing_only or remaining <= 1 or latest(events).get("status") == "final_offer":
            continue
        # A message without a term sheet gets a "hold" and burns a round (P18: two or three in a row
        # led straight to a final offer or a walk-out). One standalone question per thread at most;
        # further questions ride along with a counter.
        standalone_ok = remaining >= 3 and not getattr(th, "standalone_questions", 0)
        if standalone_ok:
            board["actions"][f"{sid}:reply"] = {"supplier_id": sid, "kind": "reply"}
        for kind, body in questions(case, source, history):
            if kind in th.asked_quotes:
                continue
            qid = f"{sid}:{kind}"
            board["questions"][qid] = {"supplier_id": sid, "kind": kind, "body": body}
            # Leave a reply and a closing move after a standalone question.
            if standalone_ok:
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
        for terms, origin in data_anchors(case, th, current):
            add_package(terms, origin)
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
    if evidence and action["kind"] in ("accept", "walk_away"):
        raise ValueError("evidence requires a supplier-facing message")
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
    if latest(events).get("status") == "final_offer" and kind not in ("accept", "walk_away"):
        raise ValueError("cannot negotiate after supplier final_offer")
    if kind == "accept":
        live_sheet = standing_sheet(events)
        if not live_sheet or live_sheet["term_sheet_id"] != action["term_sheet_id"]:
            raise ValueError("stale standing offer")
        if not agent.valid(case, th, live_sheet["terms"]):
            raise ValueError("invalid standing offer")
        message = {"action": {"type": "accept", "term_sheet_id": action["term_sheet_id"]}}
    elif kind == "walk_away":
        if len(live_threads(threads)) > 1:
            raise ValueError("walk_away would end every live thread of this case")
        message = {"action": {"type": "walk_away"}}
    else:
        offers = []
        authored = render_reply(selection["reply_text"], board["reply_facts"])
        if kind in ("reply", "ask"):
            th.standalone_questions = getattr(th, "standalone_questions", 0) + 1
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
                agent.case_used = getattr(agent, "case_used", set()) | {
                    r for r in claim["refs"] if not r.startswith("offer:")}
            if qid:
                th.asked_quotes.add(board["questions"][qid]["kind"])
            quote = (standing_sheet(events) or {}).get("terms", th.reference).get("unit_price")
            forecasts = [th.beliefs.probabilities(max(offers, key=lambda t: th.beliefs.value(t, p)), p, quote)
                         for p in th.beliefs.particles]
            probabilities = {k: agent.weighted(th, [pr[k] for pr in forecasts]) for k in ("accept", "counter", "walk")}
            th.last_terms, th.last_price = offers[0], offers[0]["unit_price"]
            th.pending = {"terms": offers[0], "offers": offers, "quote": quote, "repeats": th.repeats,
                          "event_count": len(events), "probabilities": probabilities}
        if kind != "counter" and selection["evidence_ids"]:
            claims = [board["evidence"][eid] for eid in selection["evidence_ids"]]
            body += "\n\n" + "\n\n".join(claim["text"] for claim in claims)
            for claim in claims:
                th.used.update(claim["refs"])
        if any(not valid_offer(agent, case, th, t) for t in offers):
            raise ValueError("final offer violates constraints")
        message = {"subject": "Re: " + case["title"], "body": body,
                   "term_sheets": [{"terms": t} for t in offers]}
        facts = {**(agent.package.facts if agent.package else {}), **case.get("facts", {})}
        offers = {ts.get("term_sheet_id") for ev in threads.values() for m in ev for ts in m.get("term_sheets") or []}
        if compliance.problems(case, message, facts, offers, standard=th.std):
            raise ValueError("final message violates constraints")
    th.continuation_review = selection["continuation_review"]
    decision = {"supplier_id": sid, "message": message}
    agent.log("decision", {"authority": "astra", "kind": kind, "selection": selection,
                           "action": decision, "llm_calls": agent.router.calls}, sid)
    agent.router.calls = []
    return decision


def compact_board(board, keep=24):
    """A smaller board for chat providers / free tiers (ASTRA_BASE_URL or ASTRA_COMPACT=1): the full one
    ran ~36 k tokens, 68 % of it 70+ package cards. Keeps the cheapest packages plus data anchors, steps
    and current terms, trims history and sources; the counter action lists only kept packages."""
    pk = board["packages"]

    def total(pid):
        v = pk[pid].get("expected_total_eur")
        return v if isinstance(v, (int, float)) else float("inf")

    chosen = []
    for marker, limit in (("next step", 6), ("ladder", 4), ("data anchor", 6), ("current/previous", 3),
                          ("Astra proposal", 3), ("indicative", 2)):
        group = sorted((pid for pid in pk if marker in (pk[pid].get("origin") or "")), key=total)[:limit]
        chosen += [pid for pid in group if pid not in chosen]
    for pid in sorted(pk, key=total):
        if len(chosen) >= keep:
            break
        if pid not in chosen:
            chosen.append(pid)
    chosen = chosen[:keep]
    small = copy.deepcopy(board)
    small["packages"] = {pid: {k: v for k, v in pk[pid].items()
                               if k not in ("versus_opening", "public_cost_scenario")} for pid in chosen}
    for action in small["actions"].values():
        if action.get("kind") == "counter":
            action["package_ids"] = [pid for pid in action["package_ids"] if pid in small["packages"]]
        if action.get("kind") == "confirm" and action.get("package_id") not in small["packages"]:
            action["_drop"] = True
    small["actions"] = {k: v for k, v in small["actions"].items()
                        if not v.get("_drop") and not (v.get("kind") == "counter" and not v["package_ids"])}
    for sup in small["suppliers"].values():
        for key in ("past_exchanges", "previous_practice_outcomes", "standing_vs_previous_practice"):
            if isinstance(sup.get(key), list):
                sup[key] = sup[key][-2:]
        if isinstance(sup.get("sources"), dict):
            sup["sources"] = {k: (v[:800] if isinstance(v, str) else v) for k, v in sup["sources"].items()}
    return small


def decide(agent, case, threads, deadline, closing_only=False):
    sources, history = {}, {}
    for sid in live_threads(threads):
        sources[sid] = agent.sources(sid, threads[sid])
        history[sid] = agent.threads[sid].episodes
    # One negotiator call per turn. The final reviewer sees all suppliers and chooses
    # independently. Reserve time for it instead of spending the window on grid search.
    viable = [sid for sid in live_threads(threads)
              if moves_left(case, threads[sid]) > 1
              and latest(threads[sid]).get("status") != "final_offer"]
    if viable and not closing_only:
        sid = min(viable, key=lambda s: sum(e.get("from") == "buyer" for e in threads[s]))
        agent.interpret(case, sid, threads[sid], min(deadline - 14, time.monotonic() + 17))
    board = build_board(agent, case, threads, sources, history, closing_only)
    if os.environ.get("ASTRA_BASE_URL") or os.environ.get("ASTRA_COMPACT"):
        board = compact_board(board)
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
