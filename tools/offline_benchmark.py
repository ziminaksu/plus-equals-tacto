"""Deterministic, in-process negotiation benchmark for CI comparison. Never calls Arena or a model.

Use identical generated cases, supplier RNG seeds and new isolated memory for every
agent. This is an engineering regression gate, not an Arena-score prediction.
"""
import argparse
import json
import random
import statistics

from arena_kit.agents.naive import NaiveAgent
from hollerau.analytical.agent import AnalyticalAgent
from hollerau.analytical.router import Router
from hollerau.analytical.storage import Store
from hollerau.cases import kit_cases
from hollerau.simulate import play_local


def score_case(case, seed, policy, risk_aversion=None):
    if policy == "naive":
        agent = NaiveAgent()
        return play_local(case, agent, seed=seed, log=True)
    store = Store(":memory:")
    try:
        agent = AnalyticalAgent(store=store, router=Router(enabled=False), run_id=f"offline-{seed}", risk_aversion=risk_aversion)
        return play_local(case, agent, seed=seed, log=True)
    finally:
        store.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seeds", type=int, nargs="+", default=[2, 5, 11, 17, 29])
    p.add_argument("--case-ids", nargs="*", default=None)
    p.add_argument("--risk-aversion", type=float, default=None)
    args = p.parse_args()
    cases = kit_cases(random.Random(99))
    if args.case_ids:
        cases = [c for c in cases if c["case_id"] in args.case_ids]
    rows = []
    for case in cases:
        for seed in args.seeds:
            our = score_case(case, seed, "analytical", args.risk_aversion)
            naive = score_case(case, seed, "naive")
            row = {
                "case": case["case_id"],
                "seed": seed,
                "ours": round(our["score"], 6),
                "naive": round(naive["score"], 6),
                "ours_rounds": our["rounds"],
                "ours_deal": our["deal"],
                "ours_rule_problems": our["problems"],
            }
            rows.append(row)
            print(json.dumps(row), flush=True)
    result = {
        "cases": len(cases),
        "games": len(rows),
        "risk_aversion": args.risk_aversion,
        "mean_ours": statistics.mean(row["ours"] for row in rows),
        "mean_naive": statistics.mean(row["naive"] for row in rows),
        "min_ours": min(row["ours"] for row in rows),
        "zero_deals": sum(not row["ours_deal"] for row in rows),
        "rules_broken": sum(bool(row["ours_rule_problems"]) for row in rows),
        "by_case": {
            case["case_id"]: round(statistics.mean(
                row["ours"] for row in rows if row["case"] == case["case_id"]
            ), 6)
            for case in cases
        },
    }
    print("BENCHMARK_SUMMARY " + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
