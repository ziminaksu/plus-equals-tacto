"""Explicit five-session maximum, durable reservation before every remote start."""

import argparse
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path

import httpx

from arena_kit.cli import load_env
from arena_kit.client import ArenaClient, ArenaError
from arena_kit.data import DataPackage
from arena_kit.play import REFRESH_BUDGET_S, RemoteTable, hosted, play

from .agent import DECISION_BUDGET_S, POLICY_VERSION, AnalyticalAgent
from .director import standing_sheet
from .experiment import fingerprint
from .router import Router
from .storage import Store


class LoggedTable(RemoteTable):
    def __init__(self, client, store, run, agent):
        super().__init__(client)
        self.store, self.run, self.agent = store, run, agent
        self.case_id = None
        self.standing_ids = {}
        self.live_ids = {}
        self.offer_terms = {}

    def remember_standing(self, supplier_id, events):
        sheet = standing_sheet(events)
        self.standing_ids[supplier_id] = sheet.get("term_sheet_id") if sheet else None
        # Track received sheets for exact-term comparison; only the standing ID is acceptable.
        self.live_ids[supplier_id] = {x.get("term_sheet_id") for x in ((events[-1].get("term_sheets") or []) if events else [])}
        for event in events:
            for ts in event.get("term_sheets") or []:
                if ts.get("term_sheet_id"):
                    self.offer_terms[ts["term_sheet_id"]] = ts.get("terms")

    def open(self, case_id):
        self.case_id = case_id
        result = super().open(case_id)
        self.agent.move_deadline = time.monotonic() + DECISION_BUDGET_S
        self.agent.session_id = self.session_id
        for sid, events in result[1].items():
            self.remember_standing(sid, events)
        self.store.status(self.run, case_id, "opened", self.session_id)
        self.store.log(self.run, "opened", {"case": result[0], "threads": result[1]}, case_id, session=self.session_id)
        return result

    def send(self, supplier_id, message):
        active = getattr(self.agent.threads.get(supplier_id), "active_plan", None)
        if active:
            self.agent.log("decision_dispatch", {"decision_id": active["decision_id"],
                                                 "status": "dispatch_attempt", "message": message}, supplier_id)
        self.store.log(self.run, "send_attempt", message, self.case_id, supplier_id, self.session_id)
        try:
            result = super().send(supplier_id, message)
        except Exception as exc:
            self.store.log(self.run, "send_unconfirmed", {"error_type": type(exc).__name__},
                           self.case_id, supplier_id, self.session_id)
            raise
        self.store.log(self.run, "sent", message, self.case_id, supplier_id, self.session_id)
        if "result" not in result:
            self.remember_standing(supplier_id, [result])
        self.agent.move_deadline = time.monotonic() + DECISION_BUDGET_S
        self.store.log(self.run, "received", result, self.case_id, supplier_id, self.session_id)
        return result

    def attachment(self, attachment_id):
        remaining = min(8, (self.agent.move_deadline or 0) - time.monotonic() - 5)
        if remaining < 1:
            raise TimeoutError("attachment budget exhausted")
        return self.client.attachment(
            self.session_id, attachment_id,
            timeout=httpx.Timeout(connect=remaining / 10, pool=remaining / 20,
                                  write=remaining / 20, read=remaining * 0.8),
        )

    def close(self, supplier_id, message):
        action = message.get("action", {})
        if action.get("type") == "accept":
            # The server validates the ID atomically on accept. A redundant read here
            # could itself exceed the move window; only received standing IDs are chosen.
            if not action.get("term_sheet_id") or action["term_sheet_id"] != self.standing_ids.get(supplier_id):
                raise ValueError("accept requires the received server-confirmed standing offer ID")
        active = getattr(self.agent.threads.get(supplier_id), "active_plan", None)
        if active:
            self.agent.log("decision_dispatch", {"decision_id": active["decision_id"],
                                                 "status": "dispatch_attempt", "message": message}, supplier_id)
        self.store.log(self.run, "send_attempt", message, self.case_id, supplier_id, self.session_id)
        try:
            try:
                result = super().close(supplier_id, message)
            except ArenaError as e:
                retry = self.reissued_accept(supplier_id, message, e)
                if not retry:
                    raise
                self.store.log(self.run, "send_attempt", retry, self.case_id, supplier_id, self.session_id)
                result = super().close(supplier_id, retry)
                message = retry
        except Exception as exc:
            self.store.log(self.run, "send_unconfirmed", {"error_type": type(exc).__name__},
                           self.case_id, supplier_id, self.session_id)
            raise
        self.store.log(self.run, "sent", message, self.case_id, supplier_id, self.session_id)
        self.store.log(self.run, "result", result, self.case_id, supplier_id, self.session_id)
        return result

    def reissued_accept(self, supplier_id, message, error):
        retry = reissued_accept(self.client, self.session_id, supplier_id, message, error, self.offer_terms)
        if retry:
            self.standing_ids[supplier_id] = retry["action"]["term_sheet_id"]
        return retry

    def refresh(self, threads, deadline=None):
        new = super().refresh(threads, deadline=deadline)
        for supplier_id, event in new:
            self.remember_standing(supplier_id, threads[supplier_id])
            self.store.log(self.run, "received", event, self.case_id, supplier_id, self.session_id)
        return new

    def missed(self, supplier_id, error):
        result = super().missed(supplier_id, error)
        if "result" not in result:
            self.remember_standing(supplier_id, [result])
        return result


def reissued_accept(client, session_id, supplier_id, message, error, known_terms=None):
    """A timeout repeats the supplier's offer under a NEW id (P05: Astra accepted Dralveck's 28.00 as
    offer:70210-2, the thread had timed out to -3 and -4 with the same terms, the accept got 422 and the
    run crashed). Returns one retry with the live id, only if its terms equal the ones we chose."""
    action = message.get("action") or {}
    if getattr(error, "status", None) != 422 or action.get("type") != "accept":
        return None
    if "standing offer" not in str(error.detail):
        return None
    deadline = time.monotonic() + REFRESH_BUDGET_S
    state = client.session(session_id, deadline=deadline)
    if state.get("status") == "ended":
        return None
    live = (state.get("threads") or {}).get(supplier_id) or {}
    new_id = live.get("offer_id")
    if not new_id or new_id == action.get("term_sheet_id") or live.get("closed"):
        return None
    thread = client.thread(session_id, supplier_id, deadline=deadline)
    # GET /threads omits term_sheet_id on sheets (round 2 P05: the retry found no old terms and the
    # 422 crashed the case) - use the terms the table recorded when it received each offer.
    terms = dict(known_terms or {})
    for m in thread.get("messages", []):
        for ts in m.get("term_sheets") or []:
            if ts.get("term_sheet_id"):
                terms[ts["term_sheet_id"]] = ts.get("terms")
    for t in thread.get("timeouts") or []:
        terms[t.get("offer_id")] = t.get("terms")
    for mv in state.get("moves") or []:
        reply = mv.get("reply") or {}
        if mv.get("supplier_id") == supplier_id and reply.get("offer_id"):
            terms[reply["offer_id"]] = reply.get("terms")
    old, new = terms.get(action["term_sheet_id"]), terms.get(new_id)
    if not old or old != new:
        return None
    return {"action": {"type": "accept", "term_sheet_id": new_id}}


class SafeRemoteTable(RemoteTable):
    """The kit's table plus the reissued-id accept retry - for the Live Final runner."""

    def __init__(self, client, case=None):
        super().__init__(client, case)
        self.offer_terms = {}

    def _record(self, events):
        for event in events:
            for ts in event.get("term_sheets") or []:
                if ts.get("term_sheet_id"):
                    self.offer_terms[ts["term_sheet_id"]] = ts.get("terms")

    def open(self, case_id):
        case, threads = super().open(case_id)
        for events in threads.values():
            self._record(events)
        return case, threads

    def send(self, supplier_id, message):
        reply = super().send(supplier_id, message)
        self._record([reply])
        return reply

    def refresh(self, threads, deadline=None):
        new = super().refresh(threads, deadline=deadline)
        self._record([event for _, event in new])
        return new

    def close(self, supplier_id, message):
        try:
            return super().close(supplier_id, message)
        except ArenaError as e:
            retry = reissued_accept(self.client, self.session_id, supplier_id, message, e, self.offer_terms)
            if not retry:
                raise
            return super().close(supplier_id, retry)


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", nargs="+", required=True)
    ap.add_argument("--max-sessions", type=int, default=5)
    ap.add_argument("--run-id", required=True, help="reuse the same ID on restart; reserved attempts count")
    ap.add_argument("--db", default="hollerau/logs/analytical.sqlite")
    ap.add_argument("--stop-file", type=Path, help="finish the current session, then stop if this file exists")
    ap.add_argument("--hypothesis", default="unspecified; exploratory run")
    ap.add_argument("--offline-llm", action="store_true", help="explicit template-only test mode")
    ap.add_argument("--primary", choices=["astra", "qwen"], default=os.environ.get("ANALYTICAL_PRIMARY", "astra"))
    ap.add_argument("--reviewer", choices=["astra", "primary"], default=os.environ.get("STRATEGIC_REVIEWER", "astra"))
    ap.add_argument("--price-pressure", type=float, default=0.0, help="experimental offer-ranking reward, 0..0.4")
    ap.add_argument("--max-spend-usd", type=float, help="enable one-call GPT-6 mode with a shared spending cap")
    ap.add_argument("--spend-ledger", type=Path, help="reuse this ledger across every case in the improvement round")
    ap.add_argument("--openai-model", choices=["gpt-6-astra", "gpt-6-sol"], default="gpt-6-astra")
    args = ap.parse_args(argv)
    if args.max_spend_usd is not None:
        if not math.isfinite(args.max_spend_usd) or args.max_spend_usd <= 0 or not args.spend_ledger:
            ap.error("a positive cap and --spend-ledger are both required")
        if args.primary != "astra" or os.environ.get("ASTRA_BASE_URL") or args.offline_llm:
            ap.error("budget mode uses direct OpenAI final decisions; remove ASTRA_BASE_URL")
        os.environ.update(LLM_MAX_SPEND_USD=str(args.max_spend_usd), LLM_SPEND_LEDGER=str(args.spend_ledger),
                          BUDGET_OPENAI_MODEL=args.openai_model)
    elif args.spend_ledger:
        ap.error("--spend-ledger requires --max-spend-usd")
    if (
        not 1 <= args.max_sessions <= 5
        or len(args.cases) > args.max_sessions
        or len(set(args.cases)) != len(args.cases)
    ):
        ap.error("choose distinct cases, at most five and within --max-sessions")
    if not math.isfinite(args.price_pressure) or not 0 <= args.price_pressure <= 0.4:
        ap.error("--price-pressure must be between 0 and 0.4; no Arena session started")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.run_id):
        ap.error("run-id must contain only letters, digits, underscore or hyphen")
    openai_ready = os.environ.get("LLM_PROVIDER") == "openai" and bool(os.environ.get("LLM_API_KEY"))
    ready = bool(os.environ.get("OPENAI_API_KEY")) if args.primary == "astra" else (
        bool(os.environ.get("HF_TOKEN")) or openai_ready
    )
    if not args.offline_llm and not ready:
        ap.error("configure credentials for the selected primary model; no Arena session started")
    if not args.offline_llm and args.reviewer == "astra" and not os.environ.get("OPENAI_API_KEY"):
        ap.error("Astra reviewer requires OPENAI_API_KEY; no Arena session started")
    package = DataPackage(os.environ.get("ARENA_DATA", "data/package"))
    package.lookup("")
    store = Store(args.db)
    code_hash = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))).hexdigest()
    reproducibility = fingerprint(package, store)
    stop_file = args.stop_file or Path(f"hollerau/logs/stop-{args.run_id}")
    store.log(
        args.run_id,
        "experiment",
        {
            "policy": POLICY_VERSION,
            "hypothesis": args.hypothesis,
            "reproducibility": reproducibility,
            "stop_file": str(stop_file),
            "code_sha256": code_hash,
            "cases": args.cases,
            "max_sessions": args.max_sessions,
            "price_pressure": args.price_pressure,
            "primary": args.primary,
            "reviewer": args.reviewer,
            "spending_cap_usd": args.max_spend_usd,
            "spending_ledger": str(args.spend_ledger) if args.spend_ledger else None,
            "budget_model": args.openai_model if args.max_spend_usd is not None else None,
        },
    )
    router = Router(enabled=not args.offline_llm, primary=args.primary, reviewer=args.reviewer)
    if router.spend:
        try:
            router.check_budget_connection()
        except Exception:
            store.log(args.run_id, "billing_check_failed", {"llm_calls": router.calls,
                                                           "spending": router.spend.snapshot()})
            router.close()
            store.close()
            ap.error("OpenAI billing/budget check failed; no Arena session started. Inspect the private run log.")
        store.log(args.run_id, "billing_check", {"llm_calls": router.calls, "spending": router.spend.snapshot()})
        router.calls = []
    client = ArenaClient(retries=0)  # never retry an ambiguous session start automatically
    available = {c["case_id"] for c in hosted(client.cases("practice"))}
    if not set(args.cases) <= available:
        ap.error("one or more cases are not hosted practice cases")
    rows = []
    for case_id in args.cases:
        if router.spend and (router.spend.snapshot()["blocked"] or router.spend.snapshot()["remaining_usd"] <= 0):
            print("STOP spending allowance exhausted; no new Arena session.", flush=True)
            break
        if stop_file.exists():
            store.log(args.run_id, "batch_stopped", {"before_case": case_id,
                                                    "reason": "stop file present; no new reservation"})
            print("STOP requested; no further session starts.", flush=True)
            break
        # Persist BEFORE the HTTP request; an unknown outcome still consumes this allowance.
        store.reserve(args.run_id, case_id, args.max_sessions)
        # A transient failure in one supplier session must not disable the reviewer
        # for the next case. Each case still has a two-failure circuit, no retries.
        router.review_failures = 0
        router.large_failures = 0
        agent = AnalyticalAgent(package, store, router, args.run_id, price_pressure=args.price_pressure)
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
    Path(f"hollerau/logs/practice-{args.run_id}.json").write_text(json.dumps(rows, indent=2))
    router.close()
    store.close()
    client.http.close()


if __name__ == "__main__":
    main()
