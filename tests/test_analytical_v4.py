"""Offline behavioural checks for the receding-horizon buyer; no score overrides."""

import copy

import pytest

from arena_kit.sim import load_cases
from hollerau.analytical.agent import AnalyticalAgent
from hollerau.analytical.beliefs import Beliefs
from hollerau.analytical.offers import echoed_proposal, equivalent_alternative
from hollerau.analytical.planning import counter_costs
from hollerau.analytical.storage import Store


def setup():
    case = copy.deepcopy(next(iter(load_cases().values())))
    case = {k: v for k, v in case.items() if not k.startswith("_")}
    case["buyer"]["must_haves"] = []
    case["buyer"]["fallback_unit_price"] = 120
    case["buyer"]["alternative"] = {"kind": "none", "terms": {}}
    case["negotiable"] = ["unit_price", "payment_days"]
    case["fixed_terms"].pop("payment_days", None)
    case["term_options"] = {"payment_days": [14, 30, 60, 90]}
    ref = {"unit_price": 100, "payment_days": 30}
    event = {"from": "supplier", "status": "open", "term_sheets": [{"term_sheet_id": "one", "terms": ref}]}
    store = Store(":memory:")
    agent = AnalyticalAgent(store=store)
    threads = {"sup:a": [copy.deepcopy(event)], "sup:b": [copy.deepcopy(event)]}
    threads["sup:b"][0]["term_sheets"][0]["term_sheet_id"] = "two"
    agent.start(case, threads)
    return case, agent, threads, agent.threads["sup:a"]


def test_payment_prior_has_monthly_currency_units():
    case, agent, _, th = setup()
    b = Beliefs(case, th.reference, th.sup, signals={"cash_short": True})
    # 30% annual financing on EUR100 is EUR2.50 for thirty days, not EUR30.
    assert max(p.b_pay for p in b.particles) <= 2.50
    agent.store.close()


def test_compensated_package_is_less_likely_to_trigger_walk():
    case, agent, _, th = setup()
    p = th.beliefs.particles[0]
    p.b_pay = 2
    ordinary = {"unit_price": 90, "payment_days": 30}
    earlier = {**ordinary, "payment_days": 14}
    assert th.beliefs.probabilities(earlier, p, 100)["walk"] < th.beliefs.probabilities(ordinary, p, 100)["walk"]
    agent.store.close()


def test_more_rounds_create_an_option_not_a_forced_commitment():
    case, agent, _, th = setup()
    terms = {"unit_price": 85, "payment_days": 30}
    fallback = agent.alternatives(case)

    def valid(t):
        return agent.valid(case, th, t)

    th.planning_moves = 2
    short = counter_costs(case, th, terms, th.reference, valid, fallback)
    th.planning_moves = 6
    longer = counter_costs(case, th, terms, th.reference, valid, fallback)
    assert len(short) == len(longer) == len(th.beliefs.particles)
    assert all(0 < long <= stop + 1e-7 for long, stop in zip(longer, short, strict=True))
    assert any(long < stop for long, stop in zip(longer, short, strict=True))
    agent.store.close()


def test_equivalent_package_respects_budget_and_fixed_fields():
    case, agent, _, th = setup()
    # Competing financing hypotheses make the alternative informative.
    for i, p in enumerate(th.beliefs.particles):
        p.b_pay = 0 if i % 2 else 3
    primary = {"unit_price": 90, "payment_days": 14}
    alternative = equivalent_alternative(agent, case, th, primary)
    assert alternative and alternative["payment_days"] != 14
    assert set(alternative) == set(case["negotiable"])
    assert agent.valid(case, th, alternative)
    assert agent.weighted(th, agent.cost_samples(case, th, alternative)) <= (
        agent.weighted(th, agent.cost_samples(case, th, primary)) * 1.001
    )
    agent.store.close()


def test_only_unambiguous_echoes_teach_preferences_once():
    case, agent, _, th = setup()
    early = {"unit_price": 90, "payment_days": 14}
    later = {"unit_price": 91, "payment_days": 90}
    assert echoed_proposal(case, th.std, [early, later], {**later, "unit_price": 96}) == later
    assert echoed_proposal(case, th.std, [early, later], {"unit_price": 96, "payment_days": 60}) is None
    assert echoed_proposal(case, th.std, [early, early], early) is None
    b = th.beliefs
    before = b.summary()["b_pay"]["mean"]
    assert b.learn_choice("choice", early, [early, later])
    assert b.summary()["b_pay"]["mean"] > before
    weights = [p.weight for p in b.particles]
    assert not b.learn_choice("choice", early, [early, later])
    assert [p.weight for p in b.particles] == weights
    agent.store.close()


def test_other_supplier_quote_backs_exploration_and_all_threads_are_checked(monkeypatch):
    case, agent, threads, _ = setup()
    seen = []

    def rank(case, th, current, continuation, fallback):
        seen.append((th.dossier.supplier, continuation, fallback))
        return [{"terms": current, "objective": continuation + 1, "scenario_costs": [continuation] * 64}]

    monkeypatch.setattr(agent, "rank", rank)
    decision = agent.decide(case, threads)
    assert {s[0] for s in seen} == set(threads)
    assert all(f == pytest.approx(c) for _, c, f in seen)
    assert decision["message"]["action"]["type"] == "accept"
    assert decision["message"]["action"]["term_sheet_id"] in ("one", "two")
    agent.store.close()
