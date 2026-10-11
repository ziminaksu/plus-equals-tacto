"""Expose the next useful comparison without pre-authorizing continuation or closure."""


def add_continuation_context(board):
    board["live_supplier_ids"] = list(board["suppliers"])
    board["exit_context"] = {
        "walk_away_ends_entire_case": True,
        "outside_option_estimated_cost_eur": board["fallback_estimated_cost_eur"],
        "outside_option_is_supplier_bid": False,
        "closed_suppliers_are_available": False,
    }
    for sid, supplier in board["suppliers"].items():
        actions = {aid: a for aid, a in board["actions"].items() if a["supplier_id"] == sid}
        useful = [aid for aid, action in actions.items() if action["kind"] in ("counter", "ask")]
        ids = list(dict.fromkeys(pid for a in actions.values() for pid in a.get("package_ids", [])))
        best = min(ids, key=lambda p: board["packages"][p]["expected_total_eur"]) if ids else None
        standing = (supplier.get("standing") or {}).get("expected_total_eur")
        supplier["continuation_comparison"] = {
            "review_before_early_close": bool(useful and supplier["remaining_moves"] >= 3
                                               and supplier["status"] != "final_offer"
                                               and not board["instructions"]["closing_only"]),
            "available_comparison_ids": useful + ids,
            "best_counter_by_estimated_cost": best,
            "estimated_saving_if_obtained_eur": round(standing - board["packages"][best]["expected_total_eur"], 2)
                if best and standing is not None else None,
            "warning": "An unaccepted counter is not an available deal. Compare attainable benefit, "
                       "withdrawal risk and one useful question BEFORE confirming or promising to close. "
                       "Prior stopping conditions are hypotheses, not binding instructions. "
                       "Remaining moves do not prove remaining supplier patience.",
        }


def validate_continuation_comparison(board, action, selection):
    review = board["suppliers"][action["supplier_id"]].get("continuation_comparison", {})
    if action["kind"] in ("confirm", "accept") and review.get("review_before_early_close"):
        if selection["plan"]["rejected_alternative_id"] not in review["available_comparison_ids"]:
            raise ValueError("early confirmation/acceptance must compare an available counter or useful question")
