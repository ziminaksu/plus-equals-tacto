"""Explicit five-session maximum, durable reservation before every remote start."""

import argparse
import json
import os
from pathlib import Path

from arena_kit.cli import load_env
from arena_kit.client import ArenaClient
from arena_kit.data import DataPackage
from arena_kit.play import RemoteTable, hosted, play

from .agent import AnalyticalAgent
from .router import Router
from .storage import Store


class LoggedTable(RemoteTable):
    def __init__(self, client, store, run, agent):
        super().__init__(client)
        self.store, self.run, self.agent = store, run, agent
        self.case_id = None

    def open(self, case_id):
        self.case_id = case_id
        result = super().open(case_id)
        self.agent.session_id = self.session_id
        self.store.status(self.run, case_id, "opened", self.session_id)
        self.store.log(self.run, "opened", {"case": result[0], "threads": result[1]}, case_id, session=self.session_id)
        return result

    def send(self, supplier_id, message):
        self.store.log(self.run, "sent", message, self.case_id, supplier_id, self.session_id)
        result = super().send(supplier_id, message)
        self.store.log(self.run, "received", result, self.case_id, supplier_id, self.session_id)
        return result

    def close(self, supplier_id, message):
        self.store.log(self.run, "sent", message, self.case_id, supplier_id, self.session_id)
        result = super().close(supplier_id, message)
        self.store.log(self.run, "result", result, self.case_id, supplier_id, self.session_id)
        return result


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", nargs="+", required=True)
    ap.add_argument("--max-sessions", type=int, default=5)
    ap.add_argument("--run-id", required=True, help="reuse the same ID on restart; reserved attempts count")
    ap.add_argument("--db", default="hollerau/logs/analytical.sqlite")
    ap.add_argument("--offline-llm", action="store_true", help="explicit template-only test mode")
    args = ap.parse_args(argv)
    if (
        not 1 <= args.max_sessions <= 5
        or len(args.cases) > args.max_sessions
        or len(set(args.cases)) != len(args.cases)
    ):
        ap.error("choose distinct cases, at most five and within --max-sessions")
    if not args.offline_llm and not os.environ.get("HF_TOKEN"):
        ap.error("HF_TOKEN is required; no Arena session started")
    package = DataPackage(os.environ.get("ARENA_DATA", "data/package"))
    package.lookup("")
    store = Store(args.db)
    router = Router(enabled=not args.offline_llm)
    client = ArenaClient(retries=0)  # never retry an ambiguous session start automatically
    available = {c["case_id"] for c in hosted(client.cases("practice"))}
    if not set(args.cases) <= available:
        ap.error("one or more cases are not hosted practice cases")
    rows = []
    for case_id in args.cases:
        # Persist BEFORE the HTTP request; an unknown outcome still consumes this allowance.
        store.reserve(args.run_id, case_id, args.max_sessions)
        agent = AnalyticalAgent(package, store, router, args.run_id)
        table = LoggedTable(client, store, args.run_id, agent)
        try:
            print("START", case_id, flush=True)
            result = play(table, case_id, agent)
            store.status(args.run_id, case_id, "completed", table.session_id)
            row = {"case_id": case_id, "session_id": table.session_id, "result": result}
            store.log(args.run_id, "completed", row, case_id, session=table.session_id)
            print(
                "DONE",
                case_id,
                json.dumps({k: result.get(k) for k in ("score", "deal", "c_open", "c_deal", "c_alt", "end_reason")}),
                flush=True,
            )
            rows.append(row)
        except Exception as exc:
            store.status(args.run_id, case_id, "error", table.session_id)
            store.log(args.run_id, "error", {"type": type(exc).__name__}, case_id, session=table.session_id)
            print("STOP", case_id, type(exc).__name__, "No replacement session will be started.", flush=True)
            raise
    Path("hollerau/logs").mkdir(exist_ok=True)
    Path("hollerau/logs/practice-results.json").write_text(json.dumps(rows, indent=2))
    router.close()
    store.close()
    client.http.close()


if __name__ == "__main__":
    main()
