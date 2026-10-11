"""Decision-quality regressions on received P02/P18 states, not invented Arena scores."""

import copy
import json
import time
from pathlib import Path

import httpx
import pytest

from arena_kit.cost import complete_offer, cost_breakdown
from arena_kit.play import latest
from hollerau.analytical.agent import AnalyticalAgent
from hollerau.analytical.director import (
    FinalDecisionUnavailable,
    build_board,
    cost_card,
    execute,
    standing_sheet,
    validate_selection,
)
from hollerau.analytical.router import Router
from hollerau.analytical.storage import Store

CASES = json.loads((Path(__file__).parent / "fixtures/astra_cases.json").read_text())


def selection(aid, packages=(), question="", evidence=()):
    return {"action_id": aid, "package_ids": list(packages), "question_id": question,
            "evidence_ids": list(evidence), "tone": "cooperative",
            "rationale": "Continue exploring a priced exchange before committing."}


def setup(cid="case:P18", reply=True):
    opened = copy.deepcopy(CASES[cid]["opened"])
    case, threads = opened["case"], opened["threads"]
    sid = next(iter(threads))
    router = Router(enabled=False)
    agent = AnalyticalAgent(store=Store(":memory:"), router=router, run_id="new")
    agent.final_authority = True  # Inject decisions locally; no paid API or Arena calls.
    agent.start(case, threads)
    if reply:
        threads[sid].extend([{"from": "buyer", "body": "Earlier proposal"},
                             copy.deepcopy(CASES[cid]["v5_replies"][0])])
    return agent, case, threads, sid


def board_for(agent, case, threads):
    return build_board(agent, case, threads, {s: agent.sources(s, e) for s, e in threads.items()},
                       {s: agent.threads[s].episodes for s in threads})


@pytest.mark.parametrize("status", ["open", "agreed"])
def test_p18_quote_status_never_bypasses_astra_or_forces_acceptance(status, monkeypatch):
    agent, case, threads, sid = setup()
    latest(threads[sid])["status"] = status
    monkeypatch.setattr(agent, "rank", lambda *a: pytest.fail("Python ranking must not select the final action"))
    monkeypatch.setattr(agent, "confirm_priced_alternative", lambda *a: pytest.fail("automatic confirmation"))

    def choose(board, deadline):
        # A received indicative alternative is visible, but Astra chooses a counter.
        assert any(a["kind"] == "confirm" for a in board["actions"].values())
        pid = next(p for p, row in board["packages"].items() if row["terms"]["payment_days"] == 30)
        return selection(f"{sid}:counter", [pid])

    agent.router.final_decision = choose
    decision = agent.decide(case, threads)
    assert not decision["message"].get("action")
    assert decision["message"]["term_sheets"][0]["terms"]["payment_days"] == 30


def test_p02_astra_payment_choice_is_sent_exactly_despite_python_preferences():
    agent, case, threads, sid = setup("case:P02")
    expected = complete_offer(case, {**standing_sheet(threads[sid])["terms"], "unit_price": 360.94,
                                     "payment_days": 30})
    agent.router.enabled = True
    agent.router.analyse = lambda *a, **kw: {"alternative_terms": [expected], "signals": []}

    def choose(board, deadline):
        pid = next(p for p, row in board["packages"].items() if row["terms"] == expected)
        return selection(f"{sid}:counter", [pid], f"{sid}:payment_quotes")

    agent.router.final_decision = choose
    decision = agent.decide(case, threads)
    assert decision["message"]["term_sheets"] == [{"terms": expected}]
    assert "exact price reduction" in decision["message"]["body"]
    assert agent.threads[sid].pending["terms"] == expected


def test_unvolunteered_index_inquiry_is_available_and_does_not_commit():
    agent, case, threads, sid = setup("case:P02", reply=False)
    agent.router.final_decision = lambda b, d: selection(f"{sid}:index_rebase")
    result = agent.decide(case, threads)
    assert result["message"]["term_sheets"] == []
    assert "rebased unit price" in result["message"]["body"]
    assert agent.threads[sid].pending["kind"] == "quote_request"
    assert f"{sid}:index_rebase" not in board_for(agent, case, threads)["actions"]


def test_conditional_menu_preserves_both_selected_packages_after_previous_counter():
    agent, case, threads, sid = setup("case:P02")
    agent.threads[sid].last_terms = complete_offer(case, standing_sheet(threads[sid])["terms"])
    board = board_for(agent, case, threads)
    paired, row = next((p, r) for p, r in board["packages"].items()
                       if r.get("paired_with") and r["terms"]["payment_days"] == 30)
    base = row["paired_with"]
    assert abs(row["direct_cost_eur"] - board["packages"][base]["direct_cost_eur"]) < 40
    decision = execute(agent, case, threads, board, selection(f"{sid}:counter", [base, paired]))
    assert decision["message"]["term_sheets"] == [
        {"terms": board["packages"][pid]["terms"]} for pid in [base, paired]]
    assert "not cumulative concessions" in decision["message"]["body"]


def test_identical_cost_distribution_is_given_to_both_roles_and_sums_correctly():
    agent, case, threads, sid = setup("case:P02")
    th = agent.threads[sid]
    terms = complete_offer(case, {**standing_sheet(threads[sid])["terms"], "unit_price": 345})
    card = cost_card(agent, case, th, terms)
    assert abs(sum(card["expected_breakdown_eur"].values()) - card["expected_total_eur"]) < 0.05
    assert abs(agent.weighted(th, agent.cost_samples(case, th, terms)) - card["expected_total_eur"]) < 0.02
    assert card["direct_cost_eur"] == round(sum(cost_breakdown(case, terms, th.std).values()), 2)
    assert card["expected_total_eur"] > card["direct_cost_eur"]  # relationship is NOT discarded


def test_questions_use_approval_and_cost_notes_without_numeric_claim_fabrication():
    agent, case, threads, sid = setup()
    agent.threads[sid].dossier.notes = [
        "Cost calculation: owner offered a walkthrough of hourly rates and material costs.",
        "Price changes require committee approval.",
    ]
    board = board_for(agent, case, threads)
    assert f"{sid}:cost_walkthrough" in board["actions"]
    assert f"{sid}:approval_route" in board["actions"]
    assert "responsible decision-maker" in board["questions"][f"{sid}:approval_route"]["body"]


def test_historical_alternative_survives_repetition_and_is_not_executable():
    agent, case, threads, sid = setup()
    store = agent.store
    quoted = copy.deepcopy(latest(threads[sid]))
    store.log("old", "sent", {"body": "Please price the indexed alternative."}, case["case_id"], sid, "prior")
    store.log("old", "received", quoted, case["case_id"], sid, "prior")
    for i in range(20):
        store.log("old", "received", {"body": f"Price remains unchanged {i}", "term_sheets": []},
                  case["case_id"], sid, "prior")
    store.log("old", "result", {"c_best": 1, "score": 0.99}, case["case_id"], sid, "prior")
    store.log("new", "received", {"body": "CURRENT"}, case["case_id"], sid, "current")
    store.log("other", "received", {"body": "WRONG CASE"}, "case:P99", sid, "other")
    episodes = store.episodes(sid, case["case_id"], "current", "new")
    assert len(episodes) <= 10
    assert episodes[0]["quoted_packages_then"]
    assert episodes[0]["buyer_request"] == "Please price the indexed alternative."
    text = json.dumps(episodes)
    assert all(x not in text for x in ["c_best", "score", "CURRENT", "WRONG CASE", "term_sheet_id"])
    assert all(not e["currently_executable"] for e in episodes)
    agent.threads[sid].episodes = episodes
    board = board_for(agent, case, threads)
    assert f"{sid}:revisit_history" in board["actions"]
    # only the live offer is ever acceptable (and not yet while the supplier is still moving, many moves left)
    accepts = [a for a in board["actions"].values() if a["kind"] == "accept"]
    assert len(accepts) <= 1 and all(a["supplier_id"] == sid for a in accepts)


@pytest.mark.parametrize("corruption", ["unknown_action", "unknown_package", "empty_counter", "accept_package",
                                        "foreign_question", "fabricated_evidence", "duplicate_package"])
def test_invalid_authorization_cannot_be_replaced_by_python(corruption):
    agent, case, threads, sid = setup()

    def choose(board, deadline):
        pid = next(iter(board["packages"]))
        out = selection(f"{sid}:counter", [pid])
        if corruption == "unknown_action":
            out["action_id"] = "imaginary"
        elif corruption == "unknown_package":
            out["package_ids"] = ["imaginary"]
        elif corruption == "empty_counter":
            out["package_ids"] = []
        elif corruption == "accept_package":
            out["action_id"] = f"{sid}:accept"
        elif corruption == "foreign_question":
            out["question_id"] = "sup:other:payment_quotes"
        elif corruption == "fabricated_evidence":
            out["evidence_ids"] = ["imaginary"]
        else:
            out["package_ids"] = [pid, pid]
        return out

    agent.router.final_decision = choose
    with pytest.raises(FinalDecisionUnavailable):
        agent.decide(case, threads)
    assert not agent.store.db.execute("SELECT 1 FROM events WHERE kind='decision'").fetchone()


def test_confirmation_remains_nonbinding_and_agreed_goes_back_to_astra():
    agent, case, threads, sid = setup()
    board = board_for(agent, case, threads)
    aid = next(k for k, a in board["actions"].items() if a["kind"] == "confirm")
    sent = execute(agent, case, threads, board, selection(aid))["message"]
    assert "not acceptance" in sent["body"]
    assert not sent.get("action")
    threads[sid].extend([{**sent, "from": "buyer"}, {"from": "supplier", "status": "agreed", "body": "Confirmed",
                         "term_sheets": [{"term_sheet_id": "new-standing", "terms": sent["term_sheets"][0]["terms"]}]}])
    agent.router.final_decision = lambda b, d: selection(f"{sid}:cost_walkthrough") if (
        f"{sid}:cost_walkthrough" in b["actions"]) else selection(f"{sid}:trade_priority")
    result = agent.decide(case, threads)
    assert not result["message"].get("action")


def test_last_move_and_wave_cap_still_require_final_authorization():
    agent, case, threads, sid = setup()
    board_seen = []

    def choose(board, deadline):
        board_seen.append(board)
        assert {a["kind"] for a in board["actions"].values()} <= {"accept", "walk_away"}
        return selection(f"{sid}:accept")

    agent.router.final_decision = choose
    assert agent.close_decision(case, threads)["message"]["action"]["type"] == "accept"
    assert board_seen[-1]["instructions"]["closing_only"]
    case["round_limit"] = 2  # one earlier buyer message
    assert agent.decide(case, threads)["message"]["action"]["type"] == "accept"


def test_expired_deadline_cannot_silently_accept():
    agent, case, threads, sid = setup()
    agent.move_deadline = time.monotonic() - 1
    with pytest.raises(FinalDecisionUnavailable):
        agent.decide(case, threads)


@pytest.mark.parametrize("failure", ["timeout", "invalid", "incomplete"])
def test_real_transport_final_role_is_bounded_and_never_falls_back(failure):
    agent, case, threads, sid = setup()
    board = board_for(agent, case, threads)
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        assert body["text"]["format"]["name"] == "final_decision"
        assert body["text"]["format"]["strict"] is True
        assert sum(request.extensions["timeout"].values()) <= 20.001
        if failure == "timeout":
            raise httpx.ReadTimeout("secret details")
        return httpx.Response(200, json={"status": "incomplete" if failure == "incomplete" else "completed",
                                        "output": [{"type": "message", "content": [
                                            {"type": "output_text", "text": json.dumps(selection("unknown"))}]}]})

    router = Router(transport=httpx.MockTransport(handler), review_key="test-openai", primary="astra")
    with pytest.raises(FinalDecisionUnavailable):
        router.final_decision(board, time.monotonic() + 35)
    assert len(requests) == 1
    assert "secret details" not in json.dumps(router.calls)


def test_explicit_standing_id_and_stale_id_checks():
    agent, case, threads, sid = setup()
    reply = latest(threads[sid])
    reply["standing_offer_id"] = reply["term_sheets"][1]["term_sheet_id"]
    board = board_for(agent, case, threads)
    chosen = selection(f"{sid}:accept")
    assert validate_selection(board, chosen)["term_sheet_id"] == reply["standing_offer_id"]
    reply["standing_offer_id"] = reply["term_sheets"][0]["term_sheet_id"]
    with pytest.raises(ValueError, match="stale"):
        execute(agent, case, threads, board, chosen)


def test_live_exchange_memory_is_idempotent_and_reusable_with_same_run_id():
    agent, case, threads, sid = setup()
    agent.session_id = "earlier-live-session"
    agent.observe(case, threads)
    agent.observe(case, threads)
    assert agent.store.db.execute("SELECT COUNT(*) FROM events WHERE kind='exchange'").fetchone()[0] == 1
    memory = agent.store.episodes(sid, case["case_id"], "new-live-session", agent.run_id)
    assert len(memory) == 1 and memory[0]["buyer_request"] == "Earlier proposal"
    assert not agent.store.episodes(sid, case["case_id"], agent.session_id, agent.run_id)


def test_main_runner_requires_astra_key_not_unrelated_hf_key(monkeypatch):
    from hollerau.cli import make_agent_factory

    monkeypatch.setenv("ANALYTICAL_PRIMARY", "astra")
    monkeypatch.setenv("STRATEGIC_REVIEWER", "astra")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("HF_TOKEN", "unrelated-test-key")
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        make_agent_factory(brain="analytical")


def test_wave_runner_never_uses_python_closing_move(monkeypatch):
    import importlib
    from types import SimpleNamespace

    runner = importlib.import_module("arena_kit.play")
    agent, case, threads, sid = setup()
    for event in threads[sid]:
        event.pop("attachments", None)
    monkeypatch.setattr(runner, "closing_move", lambda *a: pytest.fail("Python closing bypass"))
    agent.router.final_decision = lambda board, deadline: selection(f"{sid}:walk")
    table = SimpleNamespace(open=lambda cid: (case, threads), close=lambda s, m: m,
                            session_id="current-live-session")
    assert runner.play(table, case["case_id"], agent, deadline=time.time() + 1) == {
        "action": {"type": "walk_away"}}
    assert agent.session_id == "current-live-session"


def test_verified_numeric_evidence_is_rendered_without_blanket_digit_ban():
    from hollerau.intel import Claim

    agent, case, threads, sid = setup()
    ref = "sc:test@2026-Q3"
    case.setdefault("facts", {})[ref] = {"otd_pct": 81.0}
    text = f"Your on-time delivery was 81.0% ({ref})."
    agent.threads[sid].dossier.claims = [Claim("delivery", [ref], text, 0.7, 81.0)]
    board = board_for(agent, case, threads)
    pid = next(iter(board["packages"]))
    chosen = selection(f"{sid}:counter", [pid], evidence=[f"{sid}:e0"])
    result = execute(agent, case, threads, board, chosen)
    assert text in result["message"]["body"]


@pytest.mark.parametrize("args", [["play", "case:P02"], ["run", "--set", "final"]])
def test_public_commands_default_to_astra_path_without_opening_sessions(args, monkeypatch):
    from types import SimpleNamespace

    from arena_kit import data
    from hollerau import cli

    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setattr(data, "DataPackage", lambda *a: SimpleNamespace(lookup=lambda query: None))

    def factory(writer, package, brain):
        assert brain == "analytical"
        raise RuntimeError("stop before Arena")

    monkeypatch.setattr(cli, "make_agent_factory", factory)
    with pytest.raises(RuntimeError, match="stop before Arena"):
        cli.main(args)
