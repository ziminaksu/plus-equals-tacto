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
    assert len(r.calls) == 1  # unavailable small model alone does not justify an expensive escalation


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


def test_quoted_preferences_update_beliefs_once_and_preserve_uncertainty():
    case, ref, sup = sample()
    b = Beliefs(case, ref, sup)
    before = b.summary()["b_pay"]["mean"]
    signals = [{"kind": "early_payment", "quote": "We need earlier payment."}]
    assert b.apply_evidence(signals) == ["early_payment"]
    assert b.summary()["b_pay"]["mean"] > before
    weights = [p.weight for p in b.particles]
    assert not b.apply_evidence(signals)
    assert weights == [p.weight for p in b.particles]
    assert all(p.weight > 0 for p in b.particles)


def test_fixed_terms_cannot_be_reopened_by_supplier_hint():
    result = Router.validate(
        {
            "interpretations": [],
            "ambiguities": [],
            "signals": [{"kind": "early_payment", "source_id": "reply", "quote": "pay sooner"}],
        },
        {"reply": "Please pay sooner."},
        ["unit_price", "ppm_commitment"],
    )
    assert result["signals"] == []
    with pytest.raises(ValueError, match="unsupported signal"):
        Router.validate(
            {
                "interpretations": [],
                "ambiguities": [],
                "signals": [{"kind": "capacity_limit", "source_id": "reply", "quote": "invented"}],
            },
            {"reply": "Please pay sooner."},
        )


def test_alternative_sheets_are_compared_but_only_standing_id_is_accepted(tmp_path):
    case, ref, _ = sample()
    case["buyer"].update(fallback_unit_price=200, alternative=None)
    opening = {
        "from": "supplier",
        "status": "open",
        "term_sheets": [{"term_sheet_id": "opening", "terms": {**ref, "unit_price": 100}}],
    }
    agent = AnalyticalAgent(store=Store(tmp_path / "offers.sqlite"))
    agent.start(case, {"sup:1": [opening]})
    reply = {
        "from": "supplier",
        "status": "final_offer",
        "term_sheets": [
            {"term_sheet_id": "expensive", "terms": {**ref, "unit_price": 99}},
            {"term_sheet_id": "better", "terms": {**ref, "unit_price": 90}},
        ],
    }
    offers = agent.available(case, {"sup:1": [opening, reply]}, 1e12, include_indicative=True)
    assert [o[2] for o in offers] == ["better", "expensive"]
    action = agent.decide(case, {"sup:1": [opening, reply]})["message"]["action"]
    assert action["term_sheet_id"] == "expensive"  # indicative alternative is not an executable acceptance


def test_reply_interpretation_changes_beliefs_before_offer_ranking(tmp_path):
    case, ref, _ = sample()
    case["negotiable"] = ["unit_price", "payment_days"]
    case["fixed_terms"].pop("payment_days", None)
    case["term_options"]["payment_days"] = [14, 60]
    event = {
        "from": "supplier",
        "status": "open",
        "body": "Please pay sooner.",
        "term_sheets": [{"term_sheet_id": "opening", "terms": ref}],
    }

    class EvidenceRouter:
        enabled = True
        calls = []

        def analyse(self, *args, **kwargs):
            return {"signals": [{"kind": "early_payment", "quote": "pay sooner"}], "ambiguities": []}

    agent = AnalyticalAgent(store=Store(tmp_path / "coupling.sqlite"), router=EvidenceRouter())
    original = agent.rank
    observed = []

    def rank(*args):
        observed.append(args[1].beliefs.signal_counts.get("early_payment"))
        return original(*args)

    agent.rank = rank
    agent.decide(case, {"sup:1": [event]})
    assert observed == [1]


def test_search_includes_premiums_and_never_repeats_rejected_package(tmp_path):
    case, ref, _ = sample()
    case["negotiable"] = ["unit_price", "payment_days"]
    case["term_options"]["payment_days"] = [14, 60]
    case["fixed_terms"].pop("payment_days", None)
    event = {"from": "supplier", "status": "open", "term_sheets": [{"term_sheet_id": "x", "terms": ref}]}
    agent = AnalyticalAgent(store=Store(tmp_path / "search.sqlite"))
    agent.start(case, {"sup:1": [event]})
    th = agent.threads["sup:1"]
    candidates = agent.candidates(case, th, ref)
    assert any(t["unit_price"] > ref["unit_price"] for t in candidates)
    th.last_terms = candidates[0]
    th.last_outcome = "counter"
    assert th.last_terms not in agent.candidates(case, th, ref)


def test_regularised_learning_survives_restart(tmp_path):
    case, ref, sup = sample()
    b = Beliefs(case, ref, sup)
    before = b.accept_bias
    b.update("reply", [ref], "counter", ref["unit_price"])
    assert b.accept_bias < before
    path = tmp_path / "memory.sqlite"
    store = Store(path)
    store.save_learning("sup", "goal", b.export_learning())
    store.close()
    store = Store(path)
    fresh = Beliefs(case, ref, sup)
    fresh.import_learning(store.load_learning("sup", "goal"))
    assert b.accept_bias < fresh.accept_bias < 0  # shrink, do not blindly reuse
    assert fresh.memory_source == "supplier"
    other = Beliefs(case, ref, sup)
    other.import_learning(store.load_learning("unseen-supplier", "goal"))
    assert fresh.accept_bias < other.accept_bias < 0
    assert other.memory_source == "category"


def test_clear_analysis_is_cached_and_no_large_call_for_ambiguity_alone():
    calls = []

    def handler(req):
        calls.append(json.loads(req.content)["model"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "interpretations": [],
                                    "signals": [],
                                    "ambiguities": ["minor unclear wording"],
                                    "question": "",
                                }
                            )
                        }
                    }
                ]
            },
        )

    r = Router("test", httpx.MockTransport(handler))
    r.analyse({"x": "text"}, [], time.monotonic() + 20)
    second = r.analyse({"x": "text"}, [], time.monotonic() + 20)
    assert second["cache_hit"] and calls == [r.small]


def test_large_failure_circuit_protects_turn_budget():
    calls = []

    def handler(req):
        calls.append(1)
        raise httpx.ReadTimeout("timeout")

    r = Router("test", httpx.MockTransport(handler))
    for _ in range(3):
        r.resolve({}, {}, ["material trade"], time.monotonic() + 20)
    assert len(calls) == 2


def test_closing_preflight_rejects_unregistered_id_before_post(tmp_path):
    from hollerau.analytical.cli import LoggedTable

    class Client:
        def thread(self, *args):
            return {"offer_id": "offer:registered"}

        def send_message(self, *args):
            raise AssertionError("must not POST acceptance of an indicative offer")

    store = Store(tmp_path / "preflight.sqlite")
    table = LoggedTable(Client(), store, "run", None)
    table.session_id = "existing-session"
    with pytest.raises(ValueError, match="server-confirmed"):
        table.close("sup:1", {"action": {"type": "accept", "term_sheet_id": "offer:indicative"}})
