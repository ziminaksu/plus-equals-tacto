import json
import math
import sqlite3
import time

import httpx
import pytest

from arena_kit.cost import closing_terms
from arena_kit.sim import load_cases
from hollerau.analytical.agent import AnalyticalAgent
from hollerau.analytical.beliefs import Beliefs
from hollerau.analytical.router import Router, parse_object
from hollerau.analytical.storage import Store


def sample():
    case = next(iter(load_cases().values()))
    # Simulator cases include private fields; only public fields enter the buyer.
    public = {k: v for k, v in case.items() if not k.startswith("_")}
    reference = closing_terms(public, {"unit_price": 100, "payment_days": 60, "lead_time_days": 30})
    sup = {"standard": reference, "full_cost": 85, "interest_rate": 0.08, "usual_rate": 0.08}
    return public, reference, sup


def test_faster_payment_increases_value_and_acceptance():
    case, ref, sup = sample()
    b = Beliefs(case, ref, sup)
    p = b.particles[0]
    p.b_pay = 2
    faster = {**ref, "payment_days": 30}
    assert b.value(faster, p) - b.value(ref, p) == pytest.approx(2)
    assert b.probabilities(faster, p, 100)["accept"] > b.probabilities(ref, p, 100)["accept"]
    assert sum(b.probabilities(faster, p, 100).values()) == pytest.approx(1)


def test_rejection_reweights_once_without_collapsing():
    case, ref, sup = sample()
    b = Beliefs(case, ref, sup)
    before = b.summary()["r"]["mean"]
    assert b.update("reply1", [ref], "counter", 100)
    after = b.summary()["r"]["mean"]
    assert after > before
    assert not b.update("reply1", [ref], "counter", 100)
    assert b.summary()["r"]["mean"] == after
    assert sum(p.weight for p in b.particles) == pytest.approx(1)
    assert all(p.weight > 0 for p in b.particles)


def test_budget_survives_restart_and_counts_uncertain_starts(tmp_path):
    path = tmp_path / "audit.sqlite"
    s = Store(path)
    for i in range(5):
        s.reserve("authorized-five", str(i), 5)
    s.close()
    s = Store(path)
    with pytest.raises(ValueError, match="exhausted"):
        s.reserve("authorized-five", "sixth", 5)
    with pytest.raises(ValueError):
        s.reserve("authorized-five", "sixth", 6)
    assert s.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 5
    s.close()


def test_duplicate_case_does_not_spend_an_extra_allowance(tmp_path):
    s = Store(tmp_path / "a.sqlite")
    s.reserve("r", "P01", 5)
    with pytest.raises(sqlite3.IntegrityError):
        s.reserve("r", "P01", 5)
    assert s.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


def test_router_escalates_once_and_checks_source_quotes():
    calls = []

    def handler(req):
        data = json.loads(req.content)
        calls.append(data["model"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "interpretations": [
                                        {"claim": "payment preference", "source_id": "doc:1", "quote": "early payment"}
                                    ],
                                    "ambiguities": [],
                                    "question": "Would earlier payment help?",
                                }
                            )
                        },
                    }
                ]
            },
        )

    r = Router("test", httpx.MockTransport(handler))
    out = r.analyse({"doc:1": "We prefer early payment."}, ["ranking changes"], time.monotonic() + 20)
    assert calls == [r.small, r.large] and out["escalated"]
    with pytest.raises(ValueError):
        Router.validate({"interpretations": [{"source_id": "x", "quote": "made up"}], "ambiguities": []}, {})


def test_router_no_escalation_for_clear_evidence():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"interpretations":[],"ambiguities":[],"question":""}'}}]}
        )

    r = Router("test", httpx.MockTransport(handler))
    r.analyse({}, [], time.monotonic() + 20)
    assert len(calls) == 1


def test_extra_json_is_rejected_not_silently_truncated():
    with pytest.raises(ValueError):
        parse_object('{"a":1}{"b":2}')
    assert parse_object('```json\n{"a":1}\n```') == {"a": 1}


def test_no_secret_in_failure_audit():
    r = Router("SECRET_VALUE", httpx.MockTransport(lambda req: httpx.Response(401, text="SECRET_VALUE")))
    r.analyse({}, [], time.monotonic() + 20)
    assert "SECRET_VALUE" not in json.dumps(r.calls)
    assert len(r.calls) == 2


def test_public_local_games_have_valid_moves_and_audit(tmp_path):
    from hollerau.cases import kit_cases
    from hollerau.simulate import play_local

    for i, case in enumerate(kit_cases(__import__("random").Random(5))):
        store = Store(tmp_path / f"{i}.sqlite")
        agent = AnalyticalAgent(store=store, router=Router(enabled=False))
        result = play_local(case, agent, seed=5, log=True)
        assert not result["problems"]
        assert math.isfinite(result["score"])
        assert store.db.execute("SELECT COUNT(*) FROM events WHERE kind='decision'").fetchone()[0] > 0
        store.close()


def test_pressure_increases_walk_risk_without_changing_prior():
    case, ref, sup = sample()
    b = Beliefs(case, ref, sup)
    p = b.particles[0]
    assert b.probabilities({**ref, "unit_price": 80}, p, 100)["walk"] > b.probabilities(ref, p, 100)["walk"]
    assert b.version == 0


def test_sustainability_uses_uncertain_full_cost(tmp_path):
    from types import SimpleNamespace

    from arena_kit.cost import total_cost

    case, ref, sup = sample()
    case["buyer"].update(category_goal="stabilise", relationship_eur_per_point=1000, sustainable_margin_pct=10)
    b = Beliefs(case, ref, sup)
    b.particles[0].full_cost = 110
    th = SimpleNamespace(std=ref, sup=sup, beliefs=b)
    agent = AnalyticalAgent(store=Store(tmp_path / "cost.sqlite"))
    assert agent.cost_samples(case, th, ref)[0] > total_cost(case, ref, ref)


def test_large_model_request_keeps_thinking_and_bounds_effort():
    requests = []

    def handler(req):
        requests.append(json.loads(req.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"interpretations":[],"ambiguities":[],"question":""}'}}]}
        )

    r = Router("test", httpx.MockTransport(handler))
    r.analyse({}, ["conflict"], time.monotonic() + 20)
    assert requests[1]["reasoning_effort"] == "low"
    assert requests[1].get("chat_template_kwargs", {}).get("enable_thinking") is not False


def test_audit_escapes_supplier_content(tmp_path):
    from hollerau.analytical.report import render

    db = tmp_path / "audit.sqlite"
    store = Store(db)
    store.log("run", "received", {"body": "<script>alert(1)</script>"}, "P01")
    out = tmp_path / "audit.html"
    render(db, "run", out)
    assert "<script>" not in out.read_text()
    assert "&lt;script&gt;" in out.read_text()


def test_capacity_search_keeps_full_volume_long_contracts(tmp_path):
    case, ref, _ = sample()
    need = case["buyer"]["need_per_year"]
    case["type"] = "capacity"
    case["negotiable"] = ["unit_price", "volume_per_year", "contract_months", "lead_time_days"]
    for field in case["negotiable"]:
        case.get("fixed_terms", {}).pop(field, None)
    case["term_options"] = {
        "volume_per_year": [int(need * 0.7), int(need * 0.85), need],
        "contract_months": [12, 24, 36],
        "lead_time_days": [35, 42, 56],
    }
    case["buyer"]["must_haves"] = [{"field": "volume_per_year", "op": ">=", "value": need * 0.95}]
    opening = {**ref, "volume_per_year": int(need * 0.7), "contract_months": 12, "lead_time_days": 56}
    events = [
        {
            "from": "supplier",
            "status": "open",
            "body": "Capacity is limited.",
            "term_sheets": [{"term_sheet_id": "offer:1", "terms": opening}],
        }
    ]
    agent = AnalyticalAgent(store=Store(tmp_path / "cap.sqlite"))
    agent.start(case, {"sup:1": events})
    th = agent.threads["sup:1"]
    candidates = agent.candidates(case, th, opening)
    assert any(t["volume_per_year"] == need and t["contract_months"] == 24 for t in candidates)
    p = th.beliefs.particles[0]
    full = {**opening, "volume_per_year": need}
    assert th.beliefs.probabilities(full, p, 100)["accept"] < th.beliefs.probabilities(opening, p, 100)["accept"]
    th.last_terms = {**full, "unit_price": 95}
    th.last_price = 95
    for offer in agent.candidates(case, th, {**opening, "unit_price": 96}):
        delta = agent.weighted(
            th, [th.beliefs.value(offer, p) - th.beliefs.value(th.last_terms, p) for p in th.beliefs.particles]
        )
        assert delta >= -0.01


def test_supplier_signals_adjust_priors_without_overriding_score():
    case, ref, sup = sample()
    normal = Beliefs(case, ref, sup, seed=11)
    signals = {"cash_short": True, "spare_capacity": True,
               "approval_ladder": True, "wants_partnership": True}
    targeted = Beliefs(case, ref, sup, seed=11, signals=signals)
    assert targeted.summary()["supplier_signals"] == signals
    assert max(p.b_pay for p in targeted.particles) > max(p.b_pay for p in normal.particles)
    assert max(p.b_capacity for p in targeted.particles) < max(p.b_capacity for p in normal.particles)
    assert targeted.walk_pressure > normal.walk_pressure
    assert targeted.walk_repeat > normal.walk_repeat
    assert sum(p.weight for p in targeted.particles) == pytest.approx(1)


def test_candidate_shortlist_keeps_capacity_coverage(tmp_path):
    case, ref, _ = sample()
    case["type"] = "capacity"
    need = case["buyer"]["need_per_year"]
    case["negotiable"] = ["unit_price", "volume_per_year", "contract_months"]
    for field in case["negotiable"]:
        case.get("fixed_terms", {}).pop(field, None)
    case["term_options"] = {
        "volume_per_year": [int(need * 0.7), need],
        "contract_months": [12, 24, 36],
    }
    case["buyer"]["must_haves"] = [{"field": "volume_per_year", "op": ">=", "value": need}]
    opening = {**ref, "volume_per_year": need, "contract_months": 12}
    events = [{"from": "supplier", "status": "open", "body": "Offer",
               "term_sheets": [{"term_sheet_id": "offer:1", "terms": opening}]}]
    agent = AnalyticalAgent(store=Store(tmp_path / "capacity.sqlite"), router=Router(enabled=False))
    agent.start(case, {"sup:1": events})
    candidates = agent.candidates(case, agent.threads["sup:1"], opening)
    assert candidates
    assert any(t["volume_per_year"] == need and t["contract_months"] >= 24 for t in candidates)
