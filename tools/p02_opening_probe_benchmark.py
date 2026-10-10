"""Matched-seed local buyer policy comparison. No Arena or model API calls."""
import argparse
import json
import random
import statistics

from hollerau.analytical.agent import AnalyticalAgent
from hollerau.analytical.router import Router
from hollerau.analytical.storage import Store
from hollerau.cases import kit_cases
from hollerau.simulate import play_local


def evaluate(case, seed, probe=False):
    db = Store(":memory:")
    try:
        agent = AnalyticalAgent(
            store=db, router=Router(enabled=False),
            run_id=f"p02-probe-{seed}", opening_probe=probe,
        )
        return play_local(case, agent, seed=seed, log=True)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", nargs="+", type=int, default=[2,5,11,17,29,42])
    opts = parser.parse_args()
    rows = []
    for case in kit_cases(random.Random(99)):
        for seed in opts.seeds:
            base = evaluate(case, seed)
            candidate = evaluate(case, seed, probe=True)
            row = {
                "case": case["case_id"], "seed": seed,
                "base": base["score"], "candidate": candidate["score"],
                "candidate_deal": candidate["deal"],
                "candidate_problems": candidate["problems"],
                "delta": candidate["score"] - base["score"],
            }
            print(json.dumps(row), flush=True)
            rows.append(row)
    mean = lambda name: statistics.mean(row[name] for row in rows)
    result = {
        "games": len(rows), "mean_base": mean("base"),
        "mean_candidate": mean("candidate"),
        "minimum_candidate": min(row["candidate"] for row in rows),
        "improved": sum(r["delta"] > 1e-8 for r in rows),
        "regressed": sum(r["delta"] < -1e-8 for r in rows),
        "tied": sum(abs(r["delta"]) <= 1e-8 for r in rows),
        "zero_candidate_deals": sum(not r["candidate_deal"] for r in rows),
        "rule_problems": sum(bool(r["candidate_problems"]) for r in rows),
        "by_case": {case["case_id"]: {
            "base": statistics.mean(r["base"] for r in rows if r["case"] == case["case_id"]),
            "candidate": statistics.mean(r["candidate"] for r in rows if r["case"] == case["case_id"]),
        } for case in kit_cases(random.Random(99))},
    }
    print("P02_PROBE_SUMMARY " + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
