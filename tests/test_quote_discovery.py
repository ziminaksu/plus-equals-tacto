"""P02/P18 saved-decision regressions. No Arena or model network calls."""

import copy
import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from arena_kit.cost import complete_offer
from arena_kit.play import fetch_documents, standing
from hollerau.analytical.agent import AnalyticalAgent, DecisionBudgetExpired
from hollerau.analytical.cli import LoggedTable
from hollerau.analytical.discovery import discover_quote_requests
from hollerau.analytical.router import Router
from hollerau.analytical.storage import Store

CASES = json.loads((Path(__file__).parent / "fixtures/astra_cases.json").read_text())


def saved(case_id, reply_index):
    opened = copy.deepcopy(CASES[case_id]["opened"])
    case, threads = opened["case"], opened["threads"]
    sid = next(iter(threads))
    # Keep public received messages and the count of already-used buyer moves.
    for reply in CASES[case_id]["v5_replies"][:reply_index + 1]:
        threads[sid].extend([{"from": "buyer", "body": "Previous offer"}, copy.deepcopy(reply)])
    agent = AnalyticalAgent(store=Store(":memory:"), router=Router(enabled=False))
    agent.start(case, {sid: [threads[sid][0]]})
    return case, threads, agent, sid


@pytest.mark.parametrize("reply_index", [1, 2])
def test_p02_saved_openness_and_rebase_replies_request_actual_price_before_ranking(reply_index, monkeypatch):
    case, threads, agent, sid = saved("case:P02", reply_index)
    # This regression fails if a guessed counter price can veto the missing-quote action.
    monkeypatch.setattr(agent, "rank", lambda *a: pytest.fail("unpriced alternative reached price ranking"))
    decision = agent.decide(case, threads)
    message = decision["message"]
    assert decision["supplier_id"] == sid
    assert not message.get("action") and message["term_sheets"] == []
    assert "recalculated base unit price" in message["body"]
    assert "not acceptance" in message["body"]
    assert not agent.threads[sid].beliefs.signal_counts.get("index_protection")


def test_p02_information_response_does_not_train_offer_rejection_and_cannot_loop():
    case, threads, agent, sid = saved("case:P02", 1)
    decision = agent.decide(case, threads)
    th = agent.threads[sid]
    before = th.beliefs.snapshot()
    threads[sid].extend([{**decision["message"], "from": "buyer"},
                         copy.deepcopy(CASES["case:P02"]["v5_replies"][2])])
    agent.observe(case, threads)
    assert th.beliefs.snapshot() == before
    _, sources = agent.interpret(case, sid, threads[sid], time.monotonic() + 30)
    assert agent.request_missing_quote(case, sid, threads[sid], sources) is None


@pytest.mark.parametrize("restriction", ["quoted", "final", "last_two_moves", "fixed_index"])
def test_discovery_respects_actual_quotes_closing_round_and_allowed_terms(restriction):
    case, threads, agent, sid = saved("case:P02", 2)
    events = threads[sid]
    if restriction == "quoted":
        clause = next(v for v in case["term_options"]["index_clause"] if v)
        events[-1]["term_sheets"].append({"term_sheet_id": "indicative-only", "terms": {
            **standing(events)[1], "unit_price": 350, "index_clause": clause,
        }})
    elif restriction == "final":
        events[-1]["status"] = "final_offer"
    elif restriction == "last_two_moves":
        case["round_limit"] = sum(e.get("from") == "buyer" for e in events) + 2
    else:
        case["negotiable"].remove("index_clause")
    _, sources = agent.interpret(case, sid, events, time.monotonic() + 30)
    assert agent.request_missing_quote(case, sid, events, sources) is None


def test_reviewer_quote_request_is_actionable_without_fabricating_alternative_terms():
    case, threads, agent, sid = saved("case:P02", 2)
    _, sources = agent.interpret(case, sid, threads[sid], time.monotonic() + 30)
    request = discover_quote_requests(sources, case)[0]
    router = agent.router
    router.enabled = router.review_enabled = True
    router.review = lambda *a: {"quote_requests": [request], "alternative_terms": [], "conditions": []}
    th = agent.threads[sid]
    th.quote_requests = []
    current = standing(threads[sid])[1]
    cost = agent.weighted(th, agent.cost_samples(case, th, current))
    ranked = [{"terms": current, "objective": cost, "deal_cost": cost, "probabilities": {"accept": 0.5}}]
    agent.review_plan(case, sid, th, sources, ranked, (cost, sid, "x", current), current, cost * 2,
                      time.monotonic() + 30)
    assert agent.request_missing_quote(case, sid, threads[sid], sources)


@pytest.mark.parametrize("quote", [
    "We cannot offer an index clause or recalculate the base price.",
    "We are not open to introducing an index clause.",
    "We hold our price. The index is CU-NOTATION.",
])
def test_refusal_or_mere_index_mention_cannot_trigger_discovery(quote):
    case = CASES["case:P02"]["opened"]["case"]
    assert not discover_quote_requests({"reply:last": quote}, case)


def test_model_quote_request_needs_exact_supplier_evidence_and_allowed_kind():
    case = CASES["case:P02"]["opened"]["case"]
    quote = "We are open to introducing an index clause."
    good = {"kind": "index_rebase", "source_id": "reply:last", "quote": quote}
    output = {"quote_requests": [good, {**good, "quote": "made up"}, {**good, "source_id": "note:0"},
                                 {**good, "kind": "accept"}]}
    result = Router.validate_sections(output, {"reply:last": quote, "note:0": quote}, case["negotiable"],
                                     case["term_options"], review=True)
    assert result["quote_requests"] == [good]
    assert len(result["validation_errors"]) == 3


def test_p18_expired_shared_budget_closes_received_standing_quote_without_llm(monkeypatch):
    case, threads, agent, sid = saved("case:P18", 1)
    agent.move_deadline = time.monotonic() - 1  # attachment/read time already used the budget
    monkeypatch.setattr(agent, "interpret", lambda *a: pytest.fail("LLM called after budget exhausted"))
    decision = agent.decide(case, threads)
    assert decision["supplier_id"] == sid
    assert decision["message"]["action"] == {
        "type": "accept", "term_sheet_id": threads[sid][-1]["term_sheets"][0]["term_sheet_id"],
    }


def test_p18_timeout_during_analysis_still_returns_valid_close(monkeypatch):
    case, threads, agent, sid = saved("case:P18", 1)

    def slow_analysis(*args):
        agent.decision_deadline = time.monotonic() - 1
        return {"fallback": True}, {}

    monkeypatch.setattr(agent, "interpret", slow_analysis)
    decision = agent.decide(case, threads)
    assert decision["message"]["action"]["type"] == "accept"


def test_p18_search_checks_time_inside_ranking():
    case, threads, agent, sid = saved("case:P18", 1)
    agent.decision_deadline = time.monotonic() - 1
    th = agent.threads[sid]
    with pytest.raises(DecisionBudgetExpired):
        agent.rank(case, th, complete_offer(case, standing(threads[sid])[1]), 300000, 310000)


def test_p18_slow_attachments_share_budget_and_are_explicitly_marked_missing():
    case, _, agent, _ = saved("case:P18", 1)
    calls = []

    def slow_attachment(*args, timeout):
        calls.append(timeout)
        raise httpx.ReadTimeout("simulated slow document")

    table = LoggedTable(SimpleNamespace(attachment=slow_attachment), Store(":memory:"), "offline", agent)
    agent.move_deadline = time.monotonic() + 35
    message = {"attachments": [{"name": "quote.pdf", "attachment_id": "att:test"}]}
    fetch_documents(table, message)
    assert message["attachments"][0]["read_error"] == "timeout"
    assert 0 < sum(calls[0].as_dict().values()) <= 8 + 1e-6
    agent.move_deadline = time.monotonic()
    fetch_documents(table, message)
    assert len(calls) == 1  # no document request can start once the shared budget expires


@pytest.mark.parametrize("case_id", ["case:P02", "case:P18"])
def test_saved_priced_alternative_uses_real_terms_and_requests_confirmation_without_accepting_id(case_id):
    case, threads, agent, sid = saved(case_id, 0)
    reply = next(r for r in CASES[case_id]["replies"] + CASES[case_id]["v5_replies"]
                 if len(r.get("term_sheets", [])) > 1)
    threads[sid].append(copy.deepcopy(reply))
    decision = agent.confirm_priced_alternative(case, threads, sid, agent.alternatives(case))
    expected = complete_offer(case, reply["term_sheets"][1]["terms"])
    assert decision["message"]["term_sheets"] == [{"terms": expected}]
    assert "action" not in decision["message"]
    assert "confirm" in decision["message"]["body"].lower()
    assert agent.confirm_priced_alternative(case, threads, sid, agent.alternatives(case)) is None


def test_p18_does_not_confirm_a_more_expensive_indicative_alternative():
    case, threads, agent, sid = saved("case:P18", 0)
    reply = threads[sid][-1]
    # Same risk/terms as the standing quote, only a higher price.
    reply["term_sheets"][1]["terms"] = {**reply["term_sheets"][0]["terms"], "unit_price": 6.5}
    assert agent.confirm_priced_alternative(case, threads, sid, agent.alternatives(case)) is None


def test_p18_closing_does_not_spend_time_on_redundant_offer_refresh():
    case, threads, agent, sid = saved("case:P18", 1)
    calls = []

    def send(session_id, supplier_id, message):
        calls.append(message)
        return {"result": {"deal": True}}

    client = SimpleNamespace(send_message=send, thread=lambda *a: pytest.fail("redundant network read"))
    table = LoggedTable(client, Store(":memory:"), "offline", agent)
    table.remember_standing(sid, threads[sid])
    decision = {"action": {"type": "accept", "term_sheet_id": standing(threads[sid])[0]}}
    assert table.close(sid, decision) == {"deal": True}
    assert calls == [decision]
