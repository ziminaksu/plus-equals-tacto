"""Offline opening counteroffer regression tests. No Arena, model, or network calls."""
import copy

from arena_kit.cost import closing_terms, total_cost
from hollerau.analytical.agent import AnalyticalAgent
from hollerau.analytical.router import Router
from hollerau.analytical.storage import Store

from test_analytical_v5 import CASES


def prepare(case_id="case:P02", enabled=True):
    opened = copy.deepcopy(CASES[case_id]["opened"])
    case, threads = opened["case"], opened["threads"]
    agent = AnalyticalAgent(store=Store(":memory:"), router=Router(enabled=False), opening_probe=enabled)
    agent.start(case, threads)
    sid = next(iter(threads))
    th = agent.threads[sid]
    th.planning_moves = 5
    opening = closing_terms(case, th.reference, th.std)
    best = (agent.weighted(th, agent.cost_samples(case, th, opening)), sid,
            "offer:opening", opening)
    return case, threads, agent, sid, th, best


def test_first_counter_requires_real_buyer_tco_savings():
    case, threads, agent, sid, th, best = prepare()
    # Isolate the policy guard from uncertain opponent simulation. Never use
    # actual supplier private parameters or a case-ID rule.
    th.beliefs.probabilities = lambda terms, part, quote, repeats=0: {
        "accept": 0.4, "counter": 0.58, "walk": 0.02}
    candidate = agent.safe_opening_counter(case, threads, sid, th, best, agent.alternatives(case))
    assert candidate is not None
    assert candidate["terms"]["unit_price"] < best[3]["unit_price"]
    assert candidate["public_tco_saving"] > 0
    assert total_cost(case, candidate["terms"], th.std) < total_cost(case, best[3], th.std)
    assert {k: v for k, v in closing_terms(case, candidate["terms"], th.std).items() if k != "unit_price"} == {
        k: v for k, v in closing_terms(case, best[3], th.std).items() if k != "unit_price"}


def test_no_opening_probe_when_disabled_or_supplier_walk_high():
    case, threads, agent, sid, th, best = prepare(enabled=False)
    assert agent.safe_opening_counter(case, threads, sid, th, best, agent.alternatives(case)) is None
    agent.opening_probe = True
    th.beliefs.probabilities = lambda *args, **kwargs: {
        "accept": 0.10, "counter": 0.70, "walk": 0.20}
    assert agent.safe_opening_counter(case, threads, sid, th, best, agent.alternatives(case)) is None


def test_no_duplicate_first_probe_and_no_final_round_probe():
    case, threads, agent, sid, th, best = prepare()
    threads[sid].append({"from": "buyer", "term_sheets": []})
    assert agent.safe_opening_counter(case, threads, sid, th, best, agent.alternatives(case)) is None
    threads[sid].pop()
    th.planning_moves = 2
    assert agent.safe_opening_counter(case, threads, sid, th, best, agent.alternatives(case)) is None


def test_other_saved_opening_is_evaluated_without_case_special_casing():
    case, threads, agent, sid, th, best = prepare("case:P18")
    th.beliefs.probabilities = lambda *args, **kwargs: {
        "accept": 0.5, "counter": 0.49, "walk": 0.01}
    candidate = agent.safe_opening_counter(case, threads, sid, th, best, agent.alternatives(case))
    if candidate:
        assert candidate["terms"]["unit_price"] < best[3]["unit_price"]
        assert candidate["public_tco_saving"] > 0
