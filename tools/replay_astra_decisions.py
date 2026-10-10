"""Replay one saved decision per P02/P18; no Arena client, starts, sends or scores.

Use a pre-run learning snapshot. Only --live-model permits OpenAI calls (at most
one proposal and one final decision per case). Reports stay in ignored logs.
"""

import argparse
import copy
import json
import os
import sqlite3
import time
from pathlib import Path

from arena_kit.cli import load_env
from arena_kit.data import DataPackage
from hollerau.analytical.agent import AnalyticalAgent
from hollerau.analytical.director import FinalDecisionUnavailable, build_board
from hollerau.analytical.router import Router
from hollerau.analytical.storage import Store


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live-model", action="store_true")
    ap.add_argument("--cases", nargs="+", choices=["case:P02", "case:P18"], default=["case:P02", "case:P18"])
    ap.add_argument("--source-db", default="hollerau/logs/analytical.sqlite")
    ap.add_argument("--memory-db", default="hollerau/logs/v51-before-learning.sqlite")
    ap.add_argument("--source-run", default="ehl-v51-astra-two-20261010")
    ap.add_argument("--output", default="hollerau/logs/v6-replay")
    args = ap.parse_args()
    if len(args.cases) != len(set(args.cases)):
        ap.error("each case may be replayed once")
    load_env()
    package = DataPackage(os.environ.get("ARENA_DATA", "data/package"))
    package.lookup("")
    source = sqlite3.connect(f"file:{Path(args.source_db).resolve()}?mode=ro", uri=True)
    memory = sqlite3.connect(f"file:{Path(args.memory_db).resolve()}?mode=ro", uri=True)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    summary = []
    for cid in args.cases:
        opened = source.execute("SELECT id,timestamp,payload FROM events WHERE run_id=? AND case_id=? "
                                "AND kind='opened' ORDER BY id LIMIT 1", (args.source_run, cid)).fetchone()
        if not opened:
            raise ValueError("missing recorded opening")
        state = json.loads(opened[2])
        case, threads = state["case"], copy.deepcopy(state["threads"])
        store = Store(":memory:")
        memory.backup(store.db)
        # No current-run outcomes can enter retrieval or the learned-model snapshot.
        if store.db.execute("SELECT 1 FROM events WHERE timestamp>=? LIMIT 1", (opened[1],)).fetchone():
            raise ValueError("memory snapshot is not strictly earlier than the replayed run")
        router = Router(enabled=args.live_model, primary="astra", reviewer="astra")
        agent = AnalyticalAgent(package=package, store=store, router=router, run_id="private-v6-replay")
        agent.start(case, threads)
        received = source.execute("SELECT kind,supplier_id,payload FROM events WHERE run_id=? AND case_id=? "
                                  "AND kind IN ('sent','received') ORDER BY id", (args.source_run, cid)).fetchall()
        for kind, sid, payload in received:
            message = json.loads(payload)
            if kind == "sent":
                if message.get("action"):
                    break
                threads[sid].append({**message, "from": "buyer"})
                sheets = message.get("term_sheets", [])
                if sheets:
                    agent.threads[sid].last_terms = sheets[0]["terms"]
                    agent.threads[sid].last_price = sheets[0]["terms"]["unit_price"]
            else:
                threads[sid].append(message)
                break  # exactly the first response, before the old closing shortcut
        started = time.monotonic()
        result = {"case_id": cid, "arena_sessions": 0, "live_model": args.live_model}
        if args.live_model:
            try:
                result["decision"] = agent.decide(case, threads)
                result["status"] = "authorized"
            except FinalDecisionUnavailable:
                result["status"] = "not_authorized"
        else:
            board = build_board(agent, case, threads, {s: agent.sources(s, e) for s, e in threads.items()},
                                {s: agent.threads[s].episodes for s in threads})
            result["status"] = "board_only"
            store.log(agent.run_id, "final_board", board, cid)
        result["seconds"] = round(time.monotonic() - started, 3)
        events = [{"kind": k, "payload": json.loads(p)} for k, p in store.db.execute(
            "SELECT kind,payload FROM events WHERE run_id=? ORDER BY id", (agent.run_id,)).fetchall()]
        decisions = [e["payload"] for e in events if e["kind"] == "decision"]
        result["model_calls"] = decisions[-1]["llm_calls"] if decisions else router.calls
        result["selection"] = decisions[-1].get("selection") if decisions else None
        assert len(result["model_calls"]) <= 2
        (output / (cid.replace(":", "-") + ".json")).write_text(json.dumps({**result, "audit": events}, indent=2))
        summary.append(result)
        print(json.dumps({k: result[k] for k in ("case_id", "status", "seconds", "selection")}), flush=True)
        router.close()
        store.close()
    (output / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
