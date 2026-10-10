"""Case-aware continuation of the team's anchoring and concession strategy.

Public buyer terms choose a playbook; case IDs, scores and hidden benchmark prices
are never inputs. These are candidate offers and advice, not execution decisions.
"""

import json

from arena_kit.cost import OPS, complete_offer


def route(case):
    goal = case["buyer"].get("category_goal")
    if goal in ("quality_first", "secure_supply", "stabilise"):
        return goal
    if len(case.get("suppliers") or []) > 1:
        return "competitive_rfq"
    return "commercial"


def legal_options(case, field):
    constraints = [c for c in case["buyer"].get("must_haves", []) if c["field"] == field]
    return [value for value in case.get("term_options", {}).get(field, [])
            if all(OPS[c["op"]](value, c["value"]) for c in constraints)]


def feasible_seed(case, current):
    """Repair joint must-haves before generating variants of an invalid opening."""
    terms = complete_offer(case, current)
    for c in case["buyer"].get("must_haves", []):
        field = c["field"]
        if field not in terms or OPS[c["op"]](terms[field], c["value"]):
            continue
        options = legal_options(case, field)
        if options:
            value = terms[field]
            terms[field] = min(options, key=lambda x: abs(x - value)) if isinstance(value, (int, float)) else options[0]
    return terms


def anchor_packages(case, th, current):
    """At most 24 balanced price/term anchors, with honest provenance labels."""
    seed = feasible_seed(case, current or th.reference)
    quote = seed.get("unit_price")
    if not quote:
        return []
    buyer, kind = case["buyer"], route(case)
    preferred = dict(seed)
    for field in case["negotiable"]:
        values = legal_options(case, field)
        if not values or field == "unit_price":
            continue
        if field in ("payment_days", "effective_date", "chargeback_eur_per_complaint"):
            preferred[field] = max(values)
        elif field == "ppm_commitment":
            preferred[field] = min(values)
        elif field in ("contract_months", "volume_per_year"):
            target = 12 * buyer["horizon_years"] if field == "contract_months" else buyer["need_per_year"]
            sufficient = [v for v in values if v >= target]
            preferred[field] = min(sufficient) if sufficient else max(values)
        elif field == "lead_time_days":
            on_time = [v for v in values if v <= buyer["need_lead_time_days"]]
            preferred[field] = max(on_time) if on_time else min(values)
        elif field == "index_clause":
            preferred[field] = None if None in values else max(values, key=lambda v: v.get("deadband_pct", 0))

    profiles = []
    seen = set()

    def profile(terms, reason):
        key = json.dumps(terms, sort_keys=True)
        if key not in seen:
            seen.add(key)
            profiles.append((terms, reason))

    profile(preferred, "buyer-favourable joint terms; not a supplier commitment")
    profile(seed, "current terms with negotiable hard constraints repaired")
    # Term alternatives are available even when the original supplier offer was invalid.
    order = ("ppm_commitment", "chargeback_eur_per_complaint", "volume_per_year", "lead_time_days",
             "effective_date", "index_clause", "contract_months", "payment_days")
    for field in order:
        if field in preferred:
            for value in legal_options(case, field):
                profile({**preferred, field: value}, f"trade {field}; other buyer-favourable terms retained")

    references = dict(getattr(th.dossier, "reference_prices", {}) or {})
    # A bundled kit is not comparable to the unit price of just its first component.
    if case.get("type") == "bundling":
        references = {}
    if buyer.get("current_unit_price"):
        references["case current price"] = buyer["current_unit_price"]
    price_rows = [(round(p, 2), f"reference price: {name}; comparability requires review")
                  for name, p in references.items() if p and p <= quote]
    factors = (0.98, 1.0, 1.02) if kind == "secure_supply" else (
        (0.94, 0.98, 1.0) if kind == "stabilise" else (0.80, 0.85, 0.90, 0.94))
    price_rows += [(round(quote * f, 2), f"exploratory price at {f:.0%} of quote; not a sourced valuation")
                   for f in factors]
    previous = getattr(th, "last_terms", None) or {}
    if previous.get("unit_price", quote) < quote:
        for fraction in (0.25, 0.5):
            p = previous["unit_price"] + fraction * (quote - previous["unit_price"])
            price_rows.insert(0, (round(p, 2), "intermediate concession between our last price and their quote"))
    unique_prices = {}
    for price, reason in price_rows:
        unique_prices.setdefault(price, reason)
    prices = list(unique_prices.items())
    rows, seen = [], set()

    def append(terms, origin):
        key = json.dumps(terms, sort_keys=True)
        if key not in seen and len(rows) < 24:
            seen.add(key)
            rows.append((terms, origin))

    # Show each non-price route first, then several opening prices. Do not consume
    # all slots on the price grid before capacity, quality or dates become visible.
    anchor = prices[0] if prices else (quote, "current quoted price")
    for terms, reason in profiles[:12]:
        append({**terms, "unit_price": anchor[0]}, f"{reason}; {anchor[1]}")
    for price, origin in prices:
        append({**preferred, "unit_price": price}, f"opening/concession anchor; {origin}")
    for terms, reason in profiles[:12]:
        append(terms, f"non-price comparison at the supplier's quote; {reason}")
    return rows


GUIDANCE = {
    "stabilise": {
        "aim": "Improve total cost while accounting for the published supplier-relationship penalty.",
        "opening": "Use supported order prices/notice evidence. Compare delayed effectiveness, payment and fixed/indexed structures, where negotiable. A lowest-price anchor is not necessarily the best deal.",
        "trade": "Exchange one payment step or an allowed index clause for a quantified base-price reduction; preserve other levers. Indexation must not pay again for increases already included in the base.",
        "next": "If the first proposal is accepted immediately, assess a different supported structure before closing; acceptance alone is not proof of further room. If stalled, request approval with new evidence, not repeated low prices.",
    },
    "secure_supply": {
        "aim": "Secure the required volume, horizon coverage and timely delivery at the best total cost, including supplier health.",
        "opening": "Propose a jointly feasible full-volume/on-time package even if the supplier's opening allocation fails our minimum. A modest premium may beat uncovered demand and late-delivery costs.",
        "trade": "Trade an allowed longer commitment for volume or delivery improvement. Compare its exact cost. Do not sacrifice mandatory capacity to obtain a lower unit price.",
        "next": "Escalate a specific capacity/delivery request while open. Once a feasible final offer exists, choose accept or walk; do not restart a price-only fight.",
    },
    "quality_first": {
        "aim": "Minimise price plus defect exposure under the quality ceiling, using the case's exact defect/chargeback formula.",
        "opening": "Offer two quality/liability alternatives: a tight ppm target with moderate reimbursement and a permitted looser target with stronger reimbursement. Price both; chargebacks above cost_per_defect give no extra buyer benefit.",
        "trade": "Concede one allowed ppm or reimbursement step only for a corresponding price move. A small price premium can be worthwhile for a large defect-cost reduction.",
        "next": "When the supplier asks for faster payment but payment is fixed, explicitly retain the fixed payment term and redirect to negotiable quality/liability choices. Do not promise a payment change or extra service outside this case.",
    },
    "competitive_rfq": {
        "aim": "Use genuine competition between current feasible offers, compared on total delivered cost.",
        "opening": "Consider each still-open supplier before closing early with the first responder. Approach an untried supplier when there is a credible route to a better feasible package.",
        "trade": "Exchange one payment or delivery concession for a better complete quote. A lower price with lead time beyond a must-have is not usable competition.",
        "next": "Use live_competition to assess alternatives, never claim a hypothetical quote is real. Keep a good standing offer while approaching another open supplier; final status closes bargaining only with that supplier.",
    },
    "commercial": {
        "aim": "Obtain a better total-cost package through a supported anchor and staged reciprocal exchanges.",
        "opening": "Use comparable order prices and buyer-favourable terms. Historical agreements are unconfirmed fallback possibilities, not a target to repeat automatically.",
        "trade": "Move one allowed payment, duration or index term at a time and request a price concession. Use longer commitments and the share-of-business prospect only when supported; promises remain inside case terms.",
        "next": "If a real concession brings no benefit, consider management approval with an unused commercial argument before closing. Lack of movement does not prove that a manager can concede further.",
    },
}


def add_playbooks(board):
    case = board["case"]
    kind = route(case)
    board["playbook"] = {"kind": kind, **GUIDANCE[kind],
                         "fixed_terms_are_not_concessions": case.get("fixed_terms", {}),
                         "uncertainty": "Open status is not a guarantee against walkout. Stopping rules use actual responses; exploratory anchors are not predicted agreements."}
    competition = []
    for sid, supplier in board["suppliers"].items():
        standing = supplier.get("standing")
        if standing:
            competition.append({"supplier_id": sid, "term_sheet_id": standing["term_sheet_id"],
                                "terms": standing["terms"], "expected_total_eur": standing["expected_total_eur"],
                                "currently_executable": True})
        supplier["untried"] = supplier["buyer_messages_sent"] == 0
        # Each suggested route is a selectable package, never a Python acceptance/veto.
        packages = [(pid, p) for pid, p in board["packages"].items() if p["supplier_id"] == sid]
        groups = {}
        for pid, p in packages:
            signature = json.dumps({k: v for k, v in p["terms"].items() if k != "unit_price"}, sort_keys=True)
            if signature not in groups or p["expected_total_eur"] < groups[signature][1]["expected_total_eur"]:
                groups[signature] = (pid, p)
        shortlist = sorted(groups.values(), key=lambda row: row[1]["expected_total_eur"])[:6]
        supplier["plan_candidates"] = [{"package_id": pid, "origin": p["origin"],
                                        "total_cost_delta_vs_standing_eur": p["versus_standing"]["mean_delta_eur"],
                                        "changed_terms_from_previous_buyer": [f for f, v in p["terms"].items()
                                            if (supplier["previous_buyer_terms"] or {}).get(f) != v]}
                                       for pid, p in shortlist]
    board["live_competition"] = competition
    board["playbook"]["plan_candidates_note"] = "An indicative cost shortlist across different terms, not all actions and not a feasibility forecast. All validated packages remain selectable. Choose the appropriate negotiating step yourself."
