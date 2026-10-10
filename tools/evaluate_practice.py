"""Summarise existing audit logs; never calls Arena or a model."""

import argparse
import json
import sqlite3
import statistics
from collections import Counter
from pathlib import Path


def summary(db, run_id):
    events = [
        (kind, json.loads(payload))
        for kind, payload in db.execute("SELECT kind,payload FROM events WHERE run_id=? ORDER BY id", (run_id,))
    ]
    results = []
    calls, seconds, briers = [], [], []
    signal_counts = Counter()
    for kind, value in events:
        if kind == "completed":
            result = value["result"]
            results.append(
                {
                    "case_id": value["case_id"],
                    "session_id": value["session_id"],
                    "recovered": value.get("recovered", False),
                    **{k: result.get(k) for k in ("score", "deal", "c_open", "c_deal")},
                    "replay": "https://arena.tacto.ai/replay/" + value["session_id"],
                }
            )
        if kind == "decision":
            calls.extend(value.get("llm_calls", []))
            if "seconds" in value:
                seconds.append(value["seconds"])
        if kind == "observation":
            briers.append(value["brier"])
        if kind in ("analysis", "escalation"):
            signal_counts.update(value.get("applied_signals", []))
    counts = Counter((call["model"], call["status"]) for call in calls)
    return {
        "run_id": run_id,
        "starts": db.execute("SELECT COUNT(*) FROM attempts WHERE run_id=?", (run_id,)).fetchone()[0],
        "completed": len(results),
        "results": results,
        "mean_score": statistics.mean(r["score"] for r in results) if results else None,
        "deals": sum(bool(r["deal"]) for r in results),
        "llm_calls": len(calls),
        "llm_timeouts": sum("Timeout" in c["status"] for c in calls),
        "llm_status": [{"model": m, "status": s, "count": n} for (m, s), n in sorted(counts.items())],
        "returned_usage_cost_usd": sum(c.get("usage", {}).get("estimated_cost", 0) or 0 for c in calls),
        "usage_note": "Returned usage only; timed-out calls may be billed. Excludes setup checks.",
        "mean_offer_generation_seconds": statistics.mean(seconds) if seconds else None,
        "max_offer_generation_seconds": max(seconds) if seconds else None,
        "mean_observed_brier": statistics.mean(briers) if briers else None,
        "observed_responses": len(briers),
        "signals_applied": dict(signal_counts),
        "experiments": [v for k, v in events if k == "experiment"],
        "recoveries": [v for k, v in events if k == "recovery"],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="hollerau/logs/analytical.sqlite")
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    # Open the existing file read-only: a misspelled path must not create an empty audit DB.
    db = sqlite3.connect(Path(args.db).resolve().as_uri() + "?mode=ro", uri=True)
    old, new = summary(db, args.baseline), summary(db, args.run_id)
    if new["starts"] != 5 or new["completed"] != 5:
        raise SystemExit("Expected exactly five starts and completions; no complete report written")
    result = {
        "baseline": old,
        "improved": new,
        "comparison_limitations": [
            "Same case IDs, different stochastic hosted sessions; one repeat per case.",
            "Multiple policy changes together; no causal attribution to a single component.",
            "P10 required same-session recovery from a rejected indicative offer ID; "
            "v2.1 closing checks were added before P11.",
            "Local regression checks and simulations are separate from the hosted evaluation.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: {f: v[f] for f in ("starts", "completed", "mean_score", "deals", "llm_calls", "llm_timeouts")}
                for k, v in (("baseline", old), ("improved", new))
            }
        )
    )
    db.close()


if __name__ == "__main__":
    main()
