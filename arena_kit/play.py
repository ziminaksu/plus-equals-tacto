"""Play cases with an agent against the arena over HTTP - the hosted arena (practice, sandbox,
final) or `arena-sim`, the local contract simulator. Both speak the same API.

An agent is any object with `decide(case, threads) -> {"supplier_id": ..., "message": {...}}`:
  threads: {supplier_id: [message, ...]} - every e-mail so far, both directions, in order;
           supplier attachments carry their text under "text" (see `docs.read_document`).
  message: subject, body, up to 3 term sheets, refs - or an "action" that closes the case:
           {"type": "accept", "term_sheet_id": ...} or {"type": "walk_away"}.
"""

import functools
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from .client import ArenaError
from .cost import must_haves_ok, total_cost
from .docs import read_document, standard_terms

log = logging.getLogger("arena")

ENDED = {"walked_away", "no_bid"}
# A message later than this after the supplier's last one counts as a timeout.
MOVE_LIMIT_S = 60
# In the Live Final, close this long before the wave's cap - or the slowest round of the case so far
# (your decision plus a supplier reply of up to about a minute) plus a margin, if that is longer.
CLOSE_BEFORE_CAP_S, ROUND_MARGIN_S = 90, 15
RUNNING = re.compile(r"one session per case in the final: (\S+)")
# Practice: the case list shows every practice case file; only those marked hosted can be played
# (a session on another is a 403). Without the marker every listed case counts as hosted.
HOSTED_FIELD = "hosted"


class RemoteTable:
    """The arena over HTTP: the practice arena, the final, or a hosted sandbox."""

    def __init__(self, client, case=None):
        self.client, self.session_id, self.case, self.done = client, None, case, None

    def open(self, case_id):
        try:
            r = self.client.open_session(case_id)
        except ArenaError as e:
            running = RUNNING.search(str(e.detail)) if e.status == 409 else None
            if not (running and self.case):
                raise
            return self.resume(running.group(1))
        self.session_id = r["session_id"]
        log.info("session %s", self.session_id)
        return r["case"], r["threads"]

    def resume(self, session_id):
        """Pick up a final session this team already started (e.g. after a crash): every thread
        so far, from the arena."""
        self.session_id = session_id
        log.info("resuming session %s", session_id)
        state = self.client.session(session_id)
        if state["status"] == "ended":
            self.done = self.result()
        return self.case, {s: self.client.thread(session_id, s)["messages"] for s in state["threads"]}

    def send(self, supplier_id, message):
        return self.client.send_message(self.session_id, supplier_id, message)

    def close(self, supplier_id, message):
        reply = self.client.send_message(self.session_id, supplier_id, message)
        return reply.get("result", reply)  # the supplier's last e-mail carries the result

    def attachment(self, attachment_id):
        return self.client.attachment(self.session_id, attachment_id)

    def missed(self, supplier_id, error):
        """After a 409: the result if the case has ended (e.g. at a wave's cap), else what the
        thread now says (a timeout answer, or the reason it ended)."""
        state = self.client.session(self.session_id)
        if state.get("status") == "ended":
            return {"result": state.get("result") or {"deal": False, "end_reason": state.get("end_reason")}}
        t = self.client.thread(self.session_id, supplier_id)
        last = (t.get("timeouts") or [{}])[-1]
        sheet = [{"term_sheet_id": t["offer_id"], "terms": last.get("terms", {})}]
        return {
            "from": "arena",
            "status": "walked_away" if t["closed"] else t["status"],
            "term_sheets": [] if t["closed"] else sheet,
            "body": f"({error.detail})",
            "missing_fields": last.get("missing_fields", []),
            "attachments": [],
        }

    def refresh(self, threads):
        """With several suppliers, a blocking send leaves the others unanswered for a minute: the arena
        answers their timeouts with new offers (lower, final) and closes a thread after repeated ones
        (free Gemini P05: Dralveck dropped to 28.50 by itself, then walked; we tried to accept its old
        31.00 id and crashed). Append every unseen timeout reply and closure; returns the new events."""
        seen = self.__dict__.setdefault("_seen", set())
        state = self.client.session(self.session_id)
        if state.get("status") == "ended":
            self.done = state.get("result") or {"deal": False, "end_reason": state.get("end_reason")}
            return []
        new = []
        for sid, info in (state.get("threads") or {}).items():
            if sid not in threads or latest(threads[sid]).get("status") in ENDED:
                continue
            known = {ts.get("term_sheet_id") for m in threads[sid] for ts in m.get("term_sheets") or []}
            if info.get("offer_id") in known and not info.get("closed"):
                continue
            t = self.client.thread(self.session_id, sid)
            for out in t.get("timeouts") or []:
                key = (sid, out.get("round"), out.get("offer_id"))
                if key in seen or (out.get("offer_id") and out["offer_id"] in known):
                    continue
                seen.add(key)
                sheets = [{"term_sheet_id": out["offer_id"], "terms": out.get("terms", {})}] if out.get("offer_id") else []
                sheets += [{"term_sheet_id": a.get("offer_id") or a.get("term_sheet_id"), "terms": a.get("terms", {})}
                           for a in out.get("alternatives") or [] if isinstance(a, dict)]
                event = {"from": "arena", "status": out.get("status") or t.get("status"), "term_sheets": sheets,
                         "body": out.get("text", ""), "missing_fields": out.get("missing_fields", []),
                         "attachments": [], "timeout_reply": True}
                threads[sid].append(event)
                new.append((sid, event))
            if t.get("closed") and latest(threads[sid]).get("status") not in ENDED:
                event = {"from": "arena", "status": "walked_away", "term_sheets": [],
                         "body": f"(the thread with {sid} has ended: {t['closed']})", "attachments": []}
                threads[sid].append(event)
                new.append((sid, event))
        return new

    def result(self):
        state = self.client.session(self.session_id)
        return state.get("result") or {"deal": False, "end_reason": state.get("end_reason"), **state}


def latest(events):
    """The supplier's latest message in a thread."""
    return next(m for m in reversed(events) if m.get("from") != "buyer")


def standing(events):
    """(term_sheet_id, terms) of the supplier's standing term sheet, or (None, {})."""
    sheets = latest(events).get("term_sheets") or []
    return (sheets[0]["term_sheet_id"], sheets[0]["terms"]) if sheets else (None, {})


def live_threads(threads):
    """Suppliers whose thread has not ended."""
    return [sid for sid, ev in threads.items() if latest(ev).get("status") not in ENDED]


def moves_left(case, events):
    """Messages you may still send in this thread (the round limit counts each of them)."""
    return case.get("round_limit", 10) - sum(m.get("from") == "buyer" for m in events)


def fetch_documents(table, message):
    """Download every attachment of a supplier message and add its text."""
    for att in message.get("attachments") or []:
        if att.get("attachment_id") and "text" not in att:
            try:
                att["text"] = read_document(att["name"], table.attachment(att["attachment_id"]))
            except (TimeoutError, httpx.TimeoutException):
                # A slow attachment must not consume the entire supplier-response window.
                att["read_error"] = "timeout"
                log.warning("attachment unavailable within move budget: continuing with received terms")
    return message


def closing_move(case, threads):
    """Accept the cheapest standing term sheet that keeps the must-haves and beats the alternative
    (C with each supplier's standard terms), else walk away - what to do when time runs out."""
    alt = case["buyer"].get("alternative") or {}
    c_alt = total_cost(case, alt["terms"]) if alt.get("terms", {}).get("unit_price") else float("inf")
    best = None
    for sid in live_threads(threads):
        sheet_id, terms = standing(threads[sid])
        std = standard_terms(threads[sid])
        if sheet_id and must_haves_ok(case, terms, std) and (c := total_cost(case, terms, std)) < c_alt:
            best = min(best or (c, sid, sheet_id), (c, sid, sheet_id))
    if best is None:
        return {"supplier_id": live_threads(threads)[0], "message": {"action": {"type": "walk_away"}}}
    return {"supplier_id": best[1], "message": {"action": {"type": "accept", "term_sheet_id": best[2]}}}


def play(table, case_id, agent, deadline=None):
    """Play one case to its end. `deadline` (time.time(), or a function returning it): a Live Final
    wave's cap - shortly before it, `closing_move` closes the case so it does not end without a deal."""
    case, threads = table.open(case_id)

    def finish(result):
        if hasattr(agent, "finish"):
            try:
                agent.finish(case, result)
            except Exception:
                log.exception("%s: post-result learning failed; preserving the actual Arena result", case_id)
        return result

    if hasattr(agent, "session_id") and hasattr(table, "session_id"):
        agent.session_id = table.session_id
    if hasattr(agent, "move_deadline"):
        agent.move_deadline = time.monotonic() + getattr(agent, "decision_budget_s", MOVE_LIMIT_S * 0.6)
    if getattr(table, "done", None):  # resumed a case that had already ended
        return finish(table.done)
    for events in threads.values():
        for m in events:
            fetch_documents(table, m)
    slowest = 0.0  # the longest round so far: decision + the supplier's reply
    rejected = 0  # accepts the arena refused in a row (stale offer id)
    failures = 0  # decisions that raised in a row
    while live_threads(threads):
        if getattr(table, "done", None) is not None:
            return finish(table.done)
        t0 = time.monotonic()
        cap = deadline() if callable(deadline) else deadline
        if cap and time.time() > cap - max(CLOSE_BEFORE_CAP_S, slowest + ROUND_MARGIN_S):
            log.info("%s: the wave's cap is near - closing", case_id)
            decision = agent.close_decision(case, threads) if getattr(agent, "final_authority", False) else (
                closing_move(case, threads)
            )
        else:
            if len(threads) > 1 and hasattr(table, "refresh"):
                try:
                    table.refresh(threads)
                except ArenaError as e:
                    log.warning("%s: thread refresh failed: %s", case_id, e.detail)
                if getattr(table, "done", None) is not None:
                    return finish(table.done)
                if not live_threads(threads):
                    break
            try:
                decision = agent.decide(case, threads)
                failures = 0
            except Exception as e:
                # One failed move must not abandon the case (wave test: P05 lost on a single expired budget).
                # Let the arena answer by timeout, look again and decide anew - at most three times in a row.
                failures += 1
                if failures > 3 or not hasattr(table, "refresh"):
                    raise
                log.warning("%s: decision failed (%s: %s) - waiting for the thread to move", case_id,
                            type(e).__name__, e)
                before = sum(len(ev) for ev in threads.values())
                for _ in range(15):
                    if cap and time.time() >= cap:
                        return finish(table.result())
                    time.sleep(min(5, max(0, cap - time.time())) if cap else 5)
                    try:
                        table.refresh(threads)
                    except ArenaError:
                        pass
                    if getattr(table, "done", None) is not None:
                        return finish(table.done)
                    if sum(len(ev) for ev in threads.values()) > before or not live_threads(threads):
                        break
                if sum(len(ev) for ev in threads.values()) == before and live_threads(threads):
                    raise RuntimeError("Recovery found no new supplier state; refusing a stale retry") from e
                if hasattr(agent, "move_deadline"):
                    agent.move_deadline = time.monotonic() + getattr(agent, "decision_budget_s", MOVE_LIMIT_S * 0.6)
                continue
        if (took := time.monotonic() - t0) > MOVE_LIMIT_S * 0.75:
            log.warning("decision took %.1fs - the limit is %ss per message", took, MOVE_LIMIT_S)
        sid, msg = decision["supplier_id"], decision["message"]
        try:
            if msg.get("action"):
                log.info("%s %s", sid, msg["action"])
                return finish(table.close(sid, msg))
            reply = table.send(sid, msg)
        except ArenaError as e:
            if e.status == 422 and msg.get("action") and hasattr(table, "refresh") and rejected < 2:
                # a stale offer id (the thread moved on while we waited): look again and decide again
                rejected += 1
                log.warning("%s: %s rejected (%s) - refreshing threads", sid, msg["action"], e.detail)
                table.refresh(threads)
                if hasattr(agent, "move_deadline"):
                    agent.move_deadline = time.monotonic() + getattr(agent, "decision_budget_s", MOVE_LIMIT_S * 0.6)
                continue
            if e.status != 409:
                raise
            log.info("%s: %s", sid, e.detail)
            reply = table.missed(sid, e)  # e.g. late, or the thread or the case has ended
            if msg.get("action") and "result" not in reply:  # the case goes on: decide again
                if hasattr(agent, "move_deadline"):
                    agent.move_deadline = time.monotonic() + getattr(agent, "decision_budget_s", MOVE_LIMIT_S * 0.6)
                threads[sid].append(fetch_documents(table, reply))
                continue
        if "result" in reply:  # Observe terminal behaviour before the next decide() disappears.
            if hasattr(agent, "receive_terminal"):
                try:
                    agent.receive_terminal(case, threads, sid, msg, reply)
                except Exception:
                    log.exception("%s: terminal observation failed; preserving the Arena result", case_id)
            return finish(reply["result"])
        if hasattr(agent, "move_deadline"):
            agent.move_deadline = time.monotonic() + getattr(agent, "decision_budget_s", MOVE_LIMIT_S * 0.6)
        rejected = 0
        threads[sid] += [{**msg, "from": "buyer"}, fetch_documents(table, reply)]
        slowest = max(slowest, time.monotonic() - t0)
        log.info("%s %s %s", sid, reply.get("status"), standing(threads[sid])[1])
    return finish(table.result())


def hosted(cases):
    """The cases you can play: those marked hosted, or all of them if the list has no marker."""
    if any(HOSTED_FIELD in c for c in cases):
        return [c for c in cases if c.get(HOSTED_FIELD)]
    return cases


def quota_used_up(error):
    """The practice quota's 429 ("practice limit: …"): retrying does not help before it resets."""
    return isinstance(error, ArenaError) and error.status == 429 and str(error.detail).startswith("practice limit")


def play_all(new_table, case_ids, new_agent, parallel=8):
    """Play many cases at once (e.g. every practice case). `new_table()` and `new_agent()` give
    each case its own table and agent. Once the practice quota is used up, no further case starts.
    Returns {case_id: result or the exception that stopped it}."""
    used_up = threading.Event()

    def one(case_id):
        if used_up.is_set():
            return case_id, ArenaError(429, "not started: the practice quota is used up")
        try:
            return case_id, play(new_table(), case_id, new_agent())
        except ArenaError as e:
            if quota_used_up(e):
                used_up.set()
                log.warning("practice quota used up: %s", e.detail)
            elif e.status == 403:
                log.warning("%s: %s", case_id, e.detail)  # e.g. not hosted for practice
            else:
                log.exception("%s failed", case_id)
            return case_id, e
        except Exception as e:  # one broken case must not stop the others
            log.exception("%s failed", case_id)
            return case_id, e

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        return dict(pool.map(one, case_ids))


def play_waves(client, new_agent, waves=5, parallel=10, poll=5.0):
    """The Live Final: wait for each wave, play its cases in parallel within the wave's cap, wait
    for the next. Keep it running from before the first wave until the last has closed; it returns
    after `waves` waves have closed and every case has finished: {case_id: result or exception}."""
    started, closed, caps = {}, set(), {}  # caps: wave -> its cap as time.time()

    def one(case, deadline):
        try:
            return play(RemoteTable(client, case), case["case_id"], new_agent(), deadline)
        except Exception as e:  # one broken case must not stop the others
            log.exception("%s failed", case["case_id"])
            return e

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        while len(closed) < waves or not all(f.done() for f in started.values()):
            try:
                cases = client.cases("final")
            except ArenaError as e:
                if e.status != 403:  # 403: no wave has started yet
                    raise
                cases = []
            for case in cases:
                if not case.get("open"):
                    closed.add(case["wave"])
                    continue
                if case.get("seconds_left") is not None:  # each wave has its own cap; follow an extension
                    caps[case["wave"]] = time.time() + case["seconds_left"]
                if case["case_id"] not in started and case.get("seconds_left"):
                    if case["wave"] not in {c["wave"] for c in cases if c["case_id"] in started}:
                        log.warning("wave %s started: %s", case["wave"], case.get("theme"))
                    started[case["case_id"]] = pool.submit(one, case, functools.partial(caps.get, case["wave"]))
            time.sleep(poll)
    return {case_id: f.result() for case_id, f in started.items()}
