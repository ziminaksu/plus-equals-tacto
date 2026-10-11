"""Behavioural regressions and mocked reviewer integration; no live service calls."""

import copy
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from arena_kit.cost import closing_terms
from arena_kit.sim import load_cases
from hollerau.analytical.agent import AnalyticalAgent
from hollerau.analytical.beliefs import Beliefs
from hollerau.analytical.planning import paired_objective
from hollerau.analytical.preferences import extract_explicit_conditions, validate_conditions, violated
from hollerau.analytical.router import Router
from hollerau.analytical.storage import Store


def fixture():
    case = copy.deepcopy(next(iter(load_cases().values())))
    case = {k: v for k, v in case.items() if not k.startswith("_")}
    case["negotiable"] = ["unit_price", "contract_months", "payment_days", "index_clause"]
    for k in case["negotiable"]:
        case["fixed_terms"].pop(k, None)
    clause = {"series": "CU-NOTATION", "material_share": 0.2, "deadband_pct": 3, "base_month": "2026-08"}
    case["term_options"] = {
        "contract_months": [12, 24, 36],
        "payment_days": [14, 30, 60],
        "index_clause": [None, clause],
    }
    case["buyer"]["must_haves"] = []
    reference = closing_terms(
        case, {"unit_price": 100, "payment_days": 30, "contract_months": 24, "index_clause": None}
    )
    supplier = {"standard": reference, "full_cost": 85, "interest_rate": 0.08, "usual_rate": 0.08}
    return case, reference, supplier


def test_shared_uncertainty_cancels_and_same_action_has_zero_regret():
    assert paired_objective([90, 190], [100, 200], [0.5, 0.5], 0.25) == (140, 0)
    assert paired_objective([100, 200], [100, 200], [0.5, 0.5], 0.25) == (150, 0)
    assert paired_objective([70, 230], [100, 200], [0.5, 0.5], 0.25)[0] > 150


def test_index_requirement_changes_package_acceptance_without_becoming_hard_constraint():
    case, ref, sup = fixture()
    b = Beliefs(case, ref, sup)
    sources = {"reply": "We must include an index clause for a 24-month contract."}
    conditions = extract_explicit_conditions(sources, case, ref)
    assert len(conditions) == 1
    b.apply_conditions(conditions)
    indexed = {**ref, "index_clause": case["term_options"]["index_clause"][1]}
    p = b.particles[0]
    assert b.probabilities(indexed, p, 100)["accept"] > 5 * b.probabilities(ref, p, 100)["accept"]
    assert b.probabilities(ref, p, 100)["accept"] > 0
    agent = AnalyticalAgent(store=Store(":memory:"))
    assert agent.valid(case, SimpleNamespace(std=ref), ref)
    assert not extract_explicit_conditions(
        {"x": "We do not require an index clause for a 24-month contract."}, case, ref
    )


def test_index_condition_not_invented_when_duration_is_unknown():
    case, ref, _ = fixture()
    assert not extract_explicit_conditions({"x": "We must include an index clause."}, case, ref)
    assert extract_explicit_conditions({"x": "We cannot fix prices over a three-year period."}, case, ref)[0][
        "when"
    ] == {"contract_months": 36}


def test_condition_cannot_reopen_fixed_terms_or_invent_source():
    source = {"x": "Our payment is fixed."}
    condition = {"source_id": "x", "quote": "Our payment is fixed.", "when": {}, "requires": {"payment_days": 14}}
    with pytest.raises(ValueError):
        validate_conditions([condition], source, ["unit_price"], {"payment_days": [14]})
    condition["quote"] = "invented"
    with pytest.raises(ValueError):
        validate_conditions([condition], source, ["payment_days"], {"payment_days": [14]})


def test_coupled_index_and_duration_are_valued_together():
    case, ref, sup = fixture()
    b = Beliefs(case, ref, sup)
    p = b.particles[0]
    p.b_term = 0
    p.b_index = 10
    b.apply_evidence([{"kind": "index_protection", "quote": "We require index protection."}])
    clause = case["term_options"]["index_clause"][1]
    short = {**ref, "contract_months": 12}
    long = {**ref, "contract_months": 36}
    short_gain = b.value({**short, "index_clause": clause}, p) - b.value(short, p)
    long_gain = b.value({**long, "index_clause": clause}, p) - b.value(long, p)
    assert long_gain == pytest.approx(3 * short_gain)


def test_numeric_counteroffers_learn_movement_and_do_not_set_a_hard_floor():
    case, ref, sup = fixture()
    b = Beliefs(case, ref, sup)
    offered = {**ref, "unit_price": 95}
    proposed = {**ref, "unit_price": 90}
    assert b.learn_counteroffer("one", ref, offered, proposed)
    assert b.concession_rate > 0.2
    saved = b.summary()
    assert not b.learn_counteroffer("one", ref, offered, proposed)
    assert b.summary() == saved
    assert all(p.weight > 0 for p in b.particles)
    assert sum(p.weight for p in b.particles) == pytest.approx(1)
    assert any(p.r < 95 for p in b.particles)


def test_quotes_constrain_willingness_without_rewriting_cost_hypotheses():
    case, ref, sup = fixture()
    sup["full_cost"] = 110
    b = Beliefs(case, ref, sup)
    costs = [p.full_cost for p in b.particles]
    weights = [p.weight for p in b.particles]
    b.check_cost_consistency(ref)
    assert [p.full_cost for p in b.particles] == costs
    assert [p.weight for p in b.particles] == weights
    assert any(p.full_cost > 100 and p.weight > 0 for p in b.particles)
    assert all(p.r <= b.value(ref, p) for p in b.particles)
    saved = b.snapshot()
    b.check_cost_consistency(ref)
    assert b.snapshot() == saved


def test_supplier_can_withdraw_a_condition_by_offering_conflicting_terms():
    case, ref, sup = fixture()
    b = Beliefs(case, ref, sup)
    condition = extract_explicit_conditions({"x": "We require an index clause for a 24-month contract."}, case, ref)[0]
    b.apply_conditions([condition])
    assert violated(ref, condition)
    b.learn_counteroffer("new", ref, {**ref, "unit_price": 98}, {**ref, "unit_price": 97})
    assert not b.conditions


def test_v3_learning_keeps_new_coefficients_on_restart():
    case, ref, sup = fixture()
    b = Beliefs(case, ref, sup)
    b.update("one", [ref], "counter", 100)
    b.learn_counteroffer("one", ref, {**ref, "unit_price": 95}, {**ref, "unit_price": 90})
    stored = b.export_learning()
    fresh = Beliefs(case, ref, sup)
    fresh.import_learning({"source": "supplier", "models": [stored]})
    assert stored["version"] == 3 and "b_index" in stored["means"]
    assert 0.2 < fresh.concession_rate < b.concession_rate


def test_critic_independent_schema_and_cache():
    case, ref, _ = fixture()
    requests = []

    def handler(req):
        body = json.loads(req.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "issues": [
                                        {"source_id": "x", "quote": "index required", "explanation": "Missing index."}
                                    ],
                                    "conditions": [],
                                    "alternative_terms": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    router = Router("test", httpx.MockTransport(handler))
    for _ in range(2):
        out = router.review({"x": "index required"}, case, {"action": "accept"}, time.monotonic() + 20)
    assert len(requests) == 1 and requests[0]["model"] == router.large
    assert requests[0]["reasoning_effort"] == "low"
    assert "small_analysis" not in requests[0]["messages"][1]["content"]
    assert out["issues"]


def test_critic_hallucinated_evidence_and_timeout_are_safe():
    case, _, _ = fixture()
    for mode in ("invented", "timeout"):

        def handler(req, mode=mode):
            if mode == "timeout":
                raise httpx.ReadTimeout("timeout")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "issues": [{"source_id": "x", "quote": "invented"}],
                                        "conditions": [],
                                        "alternative_terms": [],
                                    }
                                )
                            }
                        }
                    ]
                },
            )

        router = Router("SECRET", httpx.MockTransport(handler))
        out = router.review({"x": "actual text"}, case, {}, time.monotonic() + 20)
        assert out["failed"] and not out["alternative_terms"]
        assert "SECRET" not in json.dumps(router.calls)


def test_reviewer_cannot_send_invalid_or_fixed_term_changes():
    case, ref, _ = fixture()

    class Reviewer:
        enabled = True
        calls = []
        large = "reviewer"

        def review(self, *args):
            return {
                "conditions": [],
                "alternative_terms": [{"unit_price": float("nan")}, {"unit_price": 1, "fixed": "bad"}],
            }

    event = {"from": "supplier", "status": "open", "term_sheets": [{"term_sheet_id": "x", "terms": ref}]}
    agent = AnalyticalAgent(store=Store(":memory:"), router=Reviewer())
    agent.start(case, {"sup:1": [event]})
    th = agent.threads["sup:1"]
    best = (10000, "sup:1", "x", ref)
    ranked = [{"terms": ref, "objective": 11000, "deal_cost": 10000, "probabilities": {"accept": 1}}]
    returned, _ = agent.review_plan(case, "sup:1", th, {}, ranked, best, ref, 20000, time.monotonic() + 30)
    assert returned == ranked and not th.critic_candidates


def test_source_supported_review_reaches_python_ranking(monkeypatch):
    case, ref, _ = fixture()
    sources = {"reply": "We require an index clause for a 24-month contract."}
    condition = extract_explicit_conditions(sources, case, ref)[0]
    suggestion = {
        "unit_price": 92,
        "payment_days": 14,
        "contract_months": 24,
        "index_clause": case["term_options"]["index_clause"][1],
    }

    def handler(req):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "conditions": [condition],
                                    "issues": [],
                                    "alternative_terms": [suggestion],
                                }
                            )
                        }
                    }
                ],
            },
        )

    router = Router("test", httpx.MockTransport(handler))
    agent = AnalyticalAgent(store=Store(":memory:"), router=router)
    event = {"from": "supplier", "status": "open", "term_sheets": [{"term_sheet_id": "x", "terms": ref}]}
    agent.start(case, {"sup:1": [event]})
    th = agent.threads["sup:1"]
    best = (10000, "sup:1", "x", ref)
    ranked = [{"terms": ref, "objective": 11000, "deal_cost": 10000, "probabilities": {"accept": 1}}]
    original_rank = agent.rank
    reranks = []

    def check_rank(*args):
        assert th.beliefs.conditions == [condition]
        assert th.critic_candidates == [suggestion]
        reranks.append(True)
        return original_rank(*args)

    monkeypatch.setattr(agent, "rank", check_rank)
    returned, _ = agent.review_plan(
        case,
        "sup:1",
        th,
        sources,
        ranked,
        best,
        ref,
        20000,
        time.monotonic() + 30,
    )
    assert reranks == [True] and returned is not ranked and returned
    assert all(agent.valid(case, th, row["terms"]) for row in returned)
    router.close()
    agent.store.close()
