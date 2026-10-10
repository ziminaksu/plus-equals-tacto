"""Regression evidence restricted to the two authorised cases P02 and P18; no network."""

import copy
import json
import time
from pathlib import Path

import httpx
import pytest

from arena_kit.cost import complete_offer
from arena_kit.play import standing
from hollerau.analytical.agent import AnalyticalAgent
from hollerau.analytical.contracts import decision_schema, decode_conditions
from hollerau.analytical.planning import counter_costs
from hollerau.analytical.preferences import validate_conditions
from hollerau.analytical.router import ASTRA, Router
from hollerau.analytical.storage import Store

CASES = json.loads((Path(__file__).parent / "fixtures/astra_cases.json").read_text())


def setup(case_id="case:P18", router=None):
    opened = copy.deepcopy(CASES[case_id]["opened"])
    case, threads = opened["case"], opened["threads"]
    agent = AnalyticalAgent(store=Store(":memory:"), router=router)
    agent.start(case, threads)
    sid = next(iter(threads))
    return case, threads, agent, sid, agent.threads[sid]


def completion(obj):
    return {"status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": json.dumps(obj)}]},
    ]}


def test_astra_both_roles_use_separate_calls_and_no_hf_fallback():
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        assert req.url.host == "api.openai.com"
        assert req.headers["Authorization"] == "Bearer openai-test"
        assert body["model"] == ASTRA and body["store"] is False
        assert body["text"]["format"]["strict"]
        name = body["text"]["format"]["name"]
        result = {"interpretations": [], "signals": [], "ambiguities": [], "conditions": [],
                  "alternative_terms": [], "intro": "Thank you.", "question": "Which term matters most?"}
        if name == "strategic_review":
            result = {"issues": [], "conditions": [], "alternative_terms": []}
            assert "small_analysis" not in body["input"]
        return httpx.Response(200, json=completion(result))

    router = Router("hf-never-use", httpx.MockTransport(handler), primary="astra", reviewer="astra",
                    review_key="openai-test")
    case, threads, agent, sid, th = setup(router=router)
    analysis, sources = agent.interpret(case, sid, threads[sid], time.monotonic() + 52)
    assert not analysis.get("fallback")
    current = standing(threads[sid])[1]
    cost = agent.weighted(th, agent.cost_samples(case, th, current))
    ranked = [{"terms": current, "objective": cost, "deal_cost": cost, "probabilities": {"accept": 0.5}}]
    agent.review_plan(case, sid, th, sources, ranked, (cost, sid, "x", current), current, cost * 2,
                      time.monotonic() + 30)
    assert [c["text"]["format"]["name"] for c in calls] == ["negotiator", "strategic_review"]
    assert [c["role"] for c in router.calls] == ["negotiator", "strategic_review"]


def test_welcoming_our_package_does_not_create_a_supplier_requirement():
    case, _, _, _, _ = setup()
    quote = "We welcome the proposal for a 36-month contract with the AS-14404 index clause."
    condition = {"source_id": "reply", "quote": quote, "when": {"contract_months": 36},
                 "requires": {"index_clause": "present"}}
    with pytest.raises(ValueError, match="explicit requirement"):
        validate_conditions([condition], {"reply": quote}, case["negotiable"], case["term_options"])
    quote = "We require an index clause for a 36-month contract."
    condition["quote"] = quote
    assert validate_conditions([condition], {"reply": quote}, case["negotiable"], case["term_options"])


def test_one_bad_quote_does_not_discard_valid_alternative_or_other_evidence():
    case, _, _, _, th = setup()
    terms = complete_offer(case, th.reference)
    output = {"issues": [{"source_id": "x", "quote": "fabricated"},
                         {"source_id": "x", "quote": "index required"}],
              "conditions": [], "alternative_terms": [terms]}
    result = Router.validate_sections(output, {"x": "index required"}, case["negotiable"],
                                      case["term_options"], review=True)
    assert not result.get("failed") and len(result["issues"]) == 1
    assert result["alternative_terms"] == [terms]
    assert result["validation_errors"] == ["issues[0]:rejected"]


def test_package_pivots_remain_available_after_payment_and_duration_concessions():
    case, _, agent, _, th = setup()
    clause = next(v for v in case["term_options"]["index_clause"] if v)
    th.last_terms = {"unit_price": 5.49, "payment_days": 14, "contract_months": 36, "index_clause": clause}
    th.last_outcome = "counter"
    current = {**th.last_terms, "unit_price": 5.70}
    candidates = agent.candidates(case, th, current)
    assert any(t["contract_months"] == 12 and t["index_clause"] is None for t in candidates)
    assert any(t["payment_days"] == 90 for t in candidates)
    assert all(agent.valid(case, th, t) for t in candidates)


def test_supplier_indicative_quote_is_proposed_but_cannot_be_accepted_by_id():
    case, threads, agent, sid, th = setup("case:P02")
    reply = next(r for r in CASES["case:P02"]["replies"] if len(r.get("term_sheets", [])) > 1)
    threads[sid].append(copy.deepcopy(reply))
    agent.interpret(case, sid, threads[sid], time.monotonic() + 30)
    offered = reply["term_sheets"][1]
    terms = complete_offer(case, offered["terms"])
    assert terms in th.indicative_candidates
    assert terms in agent.candidates(case, th, standing(threads[sid])[1])
    available = agent.available(case, threads, agent.alternatives(case))
    assert offered["term_sheet_id"] not in [r[2] for r in available]


def test_stalling_reduces_projected_future_concessions():
    case, _, agent, _, th = setup()
    current = complete_offer(case, th.reference)
    offer = {**current, "unit_price": current["unit_price"] * 0.9}
    th.planning_moves = 8
    fallback = agent.alternatives(case)
    ordinary = counter_costs(case, th, offer, current, lambda t: agent.valid(case, th, t), fallback)
    th.stagnation = 2
    stalled = counter_costs(case, th, offer, current, lambda t: agent.valid(case, th, t), fallback)
    assert agent.weighted(th, stalled) >= agent.weighted(th, ordinary)


@pytest.mark.parametrize("case_id", ["case:P02", "case:P18"])
def test_complete_case_schema_and_condition_decoding(case_id):
    case = CASES[case_id]["opened"]["case"]
    schema = decision_schema(case)
    fields = schema["properties"]["alternative_terms"]["items"]
    assert set(fields["required"]) == set(case["negotiable"])
    assert fields["additionalProperties"] is False
    output = {"conditions": [{"when": [{"field": "payment_days", "value": 14}],
                              "requires": [{"field": "index_clause", "value": "present"}]}]}
    assert decode_conditions(output)["conditions"][0]["when"] == {"payment_days": 14}


def test_invalid_proposals_cannot_reopen_fixed_terms_or_use_nan():
    case, _, agent, _, th = setup("case:P02")
    terms = complete_offer(case, th.reference)
    bad = [{**terms, "lead_time_days": 1}, {**terms, "unit_price": float("nan")},
           {**terms, "payment_days": 999}]
    assert not agent.approved_proposals(case, th, bad, th.reference)


def test_two_session_cap_survives_restart(tmp_path):
    path = tmp_path / "two.sqlite"
    store = Store(path)
    for case_id in ("case:P02", "case:P18"):
        store.reserve("two-only", case_id, 2)
    store.close()
    store = Store(path)
    with pytest.raises(ValueError, match="exhausted"):
        store.reserve("two-only", "case:P02", 2)
