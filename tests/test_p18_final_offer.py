"""P18 final-offer regression: offline only, no Arena or paid model requests."""

from test_astra_authority import board_for, selection, setup
from arena_kit.play import latest
from hollerau.analytical.director import execute, validate_selection

import pytest


def test_p18_final_offer_closes_negotiation_without_python_acceptance():
    agent, case, threads, sid = setup("case:P18")
    latest(threads[sid])["status"] = "final_offer"
    board = board_for(agent, case, threads)
    assert {a["kind"] for a in board["actions"].values()} == {"accept", "walk_away"}
    assert board["suppliers"][sid]["final_offer_decision"]["only_closing_actions"]
    assert board["suppliers"][sid]["final_offer_decision"]["estimated_fallback_loss_eur"] > 0
    assert validate_selection(board, selection(f"{sid}:accept"))["kind"] == "accept"
    assert validate_selection(board, selection(f"{sid}:walk"))["kind"] == "walk_away"
    decision = execute(agent, case, threads, board, selection(f"{sid}:accept"))
    assert decision["message"]["action"]["type"] == "accept"


def test_final_offer_is_not_allowed_to_counter_even_with_stale_board():
    agent, case, threads, sid = setup("case:P18")
    board = board_for(agent, case, threads)
    package_id = next(iter(board["packages"]))
    latest(threads[sid])["status"] = "final_offer"
    with pytest.raises(ValueError, match="cannot negotiate after supplier final_offer"):
        execute(agent, case, threads, board, selection(f"{sid}:counter", [package_id]))


def test_p18_astra_can_walk_away_at_final_offer():
    agent, case, threads, sid = setup("case:P18")
    latest(threads[sid])["status"] = "final_offer"
    agent.router.final_decision = lambda board, deadline: selection(f"{sid}:walk")
    result = agent.decide(case, threads)
    assert result["message"]["action"]["type"] == "walk_away"
