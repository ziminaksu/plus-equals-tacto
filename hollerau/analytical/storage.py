"""Append-only audit events plus a transactional, restart-safe practice allowance."""

import json
import sqlite3
import time
from pathlib import Path


def clean(value):
    import math

    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


class Store:
    def __init__(self, path="hollerau/logs/analytical.sqlite"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=20)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, timestamp REAL NOT NULL, run_id TEXT NOT NULL,
          session_id TEXT, case_id TEXT, supplier_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS events_run ON events(run_id, kind);
        CREATE TABLE IF NOT EXISTS allowances (run_id TEXT PRIMARY KEY, cap INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts (
          id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, case_id TEXT NOT NULL,
          session_id TEXT, status TEXT NOT NULL, UNIQUE(run_id, case_id));
        CREATE TABLE IF NOT EXISTS cost_feedback (
          supplier_id TEXT, case_id TEXT, session_id TEXT, payload TEXT NOT NULL,
          PRIMARY KEY(supplier_id,case_id,session_id));
        """)
        self.db.commit()

    def log(self, run, kind, payload, case=None, supplier=None, session=None):
        cursor = self.db.execute(
            "INSERT INTO events VALUES(NULL,?,?,?,?,?,?,?)",
            (
                time.time(),
                run,
                session,
                case,
                supplier,
                kind,
                json.dumps(clean(payload), allow_nan=False, ensure_ascii=False),
            ),
        )
        self.db.commit()
        return cursor.lastrowid

    def reserve(self, run, case, cap):
        if not 1 <= cap <= 5:
            raise ValueError("practice cap must be between 1 and 5")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT cap FROM allowances WHERE run_id=?", (run,)).fetchone()
            if row and row[0] != cap:
                raise ValueError("cannot change a run's practice cap")
            self.db.execute("INSERT OR IGNORE INTO allowances VALUES(?,?)", (run, cap))
            n = self.db.execute("SELECT COUNT(*) FROM attempts WHERE run_id=?", (run,)).fetchone()[0]
            if n >= cap:
                raise ValueError("practice budget exhausted; no session started")
            self.db.execute("INSERT INTO attempts VALUES(NULL,?,?,NULL,'reserved')", (run, case))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def status(self, run, case, status, session=None):
        self.db.execute(
            "UPDATE attempts SET status=?,session_id=COALESCE(?,session_id) WHERE run_id=? AND case_id=?",
            (status, session, run, case),
        )
        self.db.commit()

    def close(self):
        self.db.close()

    def save_cost_feedback(self, case, observation):
        if not observation or not observation.get("supplier_id"):
            return
        self.db.execute("INSERT OR REPLACE INTO cost_feedback VALUES(?,?,?,?)",
                        (observation["supplier_id"], case, observation["session_id"],
                         json.dumps(clean(observation), allow_nan=False)))
        self.db.commit()

    def cost_feedback(self, supplier, case, current_session=None):
        """Migrate completed practice observations without exposing scores/benchmarks.

        Require a completed hosted attempt and its original public case. No inference
        from messages, unfinished runs or Live Final outcomes is treated as a cost label.
        """
        from .sustainability import practice_observation

        case_id = case["case_id"]
        if not case_id.startswith("case:P"):
            return []
        rows = self.db.execute(
            "SELECT e.run_id,e.session_id,e.payload FROM events e JOIN attempts a "
            "ON a.run_id=e.run_id AND a.case_id=e.case_id AND a.session_id=e.session_id "
            "WHERE e.case_id=? AND e.kind='result' AND a.status='completed' "
            "AND (? IS NULL OR e.session_id!=?) ORDER BY e.id DESC LIMIT 100",
            (case_id, current_session, current_session),
        ).fetchall()
        for run, session, payload in rows:
            result = json.loads(payload)
            if result.get("supplier_id") != supplier:
                continue
            old = self.db.execute("SELECT payload FROM events WHERE run_id=? AND case_id=? "
                                  "AND kind='case' ORDER BY id LIMIT 1", (run, case_id)).fetchone()
            if not old:
                continue
            old_case = json.loads(old[0])["case"]
            last = self.db.execute("SELECT payload FROM events WHERE run_id=? AND case_id=? "
                                   "AND kind='final_board' ORDER BY id DESC LIMIT 1", (run, case_id)).fetchone()
            estimate = {}
            if last:
                standing = json.loads(last[0]).get("suppliers", {}).get(supplier, {}).get("standing", {})
                if all(result.get("terms", {}).get(k) == v for k, v in standing.get("terms", {}).items()):
                    estimate = standing.get("expected_breakdown_eur", {})
            observation = practice_observation(old_case, result, session, estimate)
            self.save_cost_feedback(case_id, observation)
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT payload FROM cost_feedback WHERE supplier_id=? AND case_id=? "
            "AND (? IS NULL OR session_id!=?) ORDER BY rowid DESC LIMIT 30",
            (supplier, case_id, current_session, current_session))]

    def save_learning(self, supplier, goal, model):
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS learned_models "
            "(supplier TEXT, goal TEXT, model TEXT, PRIMARY KEY(supplier,goal))"
        )
        self.db.execute(
            "INSERT OR REPLACE INTO learned_models VALUES(?,?,?)",
            (supplier, goal, json.dumps(clean(model), allow_nan=False)),
        )
        self.db.commit()

    def load_learning(self, supplier, goal):
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS learned_models "
            "(supplier TEXT, goal TEXT, model TEXT, PRIMARY KEY(supplier,goal))"
        )
        row = self.db.execute(
            "SELECT model FROM learned_models WHERE supplier=? AND goal=?", (supplier, goal)
        ).fetchone()
        if row:
            return {"source": "supplier", "models": [json.loads(row[0])]}
        rows = self.db.execute(
            "SELECT model FROM learned_models WHERE goal=? ORDER BY supplier LIMIT 10", (goal,)
        ).fetchall()
        return {"source": "category", "models": [json.loads(r[0]) for r in rows]}

    def behavior_history(self, supplier, case, current_session=None):
        """Reconstruct same-context hosted observations; ignore legacy learned labels.

        Return raw message evidence only. Terminal result/score/benchmark fields are
        excluded. No counterfactual supplier or LLM calls occur during reconstruction.
        """
        from .sustainability import context_id

        rows = self.db.execute(
            "SELECT e.id,e.run_id,e.session_id,e.payload FROM events e JOIN attempts a "
            "ON a.run_id=e.run_id AND a.case_id=e.case_id AND a.session_id=e.session_id "
            "WHERE e.case_id=? AND e.supplier_id=? AND e.kind IN ('received','exchange') "
            "AND a.status='completed' AND (? IS NULL OR e.session_id!=?) ORDER BY e.id",
            (case["case_id"], supplier, current_session, current_session)).fetchall()
        sessions, seen, observations = {}, set(), []
        for event_id, run, session, payload in rows:
            if session not in sessions:
                opened = self.db.execute(
                    "SELECT payload FROM events WHERE run_id=? AND session_id=? AND kind='opened' "
                    "ORDER BY id LIMIT 1", (run, session)).fetchone()
                opening = json.loads(opened[0]) if opened else {}
                if not opening or context_id(opening["case"]) != context_id(case):
                    sessions[session] = None
                else:
                    events = opening.get("threads", {}).get(supplier, [])
                    sessions[session] = next((e for e in reversed(events) if e.get("from") != "buyer"), {})
            previous = sessions[session]
            if previous is None:
                continue
            data = json.loads(payload)
            raw = data.get("supplier_reply", data)
            reply = {k: raw[k] for k in ("message_id", "from", "status", "body", "term_sheets",
                                        "standing_offer_id") if k in raw}
            sent = self.db.execute(
                "SELECT payload FROM events WHERE run_id=? AND session_id=? AND supplier_id=? "
                "AND kind='sent' AND id<? ORDER BY id DESC LIMIT 1",
                (run, session, supplier, event_id)).fetchone()
            request = data.get("buyer_request") or (json.loads(sent[0]) if sent else {})
            signature = (session, reply.get("message_id") or json.dumps([request, reply], sort_keys=True))
            if not request or request.get("action") or signature in seen:
                continue
            seen.add(signature)
            sheets = previous.get("term_sheets") or []
            active = previous.get("standing_offer_id")
            old_sheet = next((s for s in sheets if s.get("term_sheet_id") == active), {}) if active else (
                sheets[0] if sheets else {})
            observations.append({"event_id": f"recorded:{event_id}", "session_id": session,
                                 "request": request, "reply": reply,
                                 "previous": old_sheet.get("terms", {}),
                                 "previous_status": previous.get("status")})
            sessions[session] = reply
        return observations

    def _episode_context(self, run, session, case, supplier, sent_id):
        """State before the historical request, never its eventual private outcome."""
        if sent_id is None:
            return {"stage": "unknown", "buyer_message_number": None,
                    "supplier_status_before": None, "standing_terms_before": {}}
        previous = self.db.execute(
            "SELECT payload FROM events WHERE run_id=? AND session_id IS ? AND case_id=? "
            "AND supplier_id=? AND kind IN ('received','exchange') AND id<? ORDER BY id DESC LIMIT 1",
            (run, session, case, supplier, sent_id),
        ).fetchone()
        opened = self.db.execute(
            "SELECT payload FROM events WHERE run_id=? AND session_id IS ? AND case_id=? "
            "AND kind='opened' AND id<? ORDER BY id LIMIT 1", (run, session, case, sent_id),
        ).fetchone()
        opening = json.loads(opened[0]) if opened else {}
        if previous:
            data = json.loads(previous[0])
            reply = data.get("supplier_reply", data)
        else:
            reply = next((e for e in reversed(opening.get("threads", {}).get(supplier, []))
                          if e.get("from") != "buyer"), {})
        number = self.db.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? AND session_id IS ? AND case_id=? "
            "AND supplier_id=? AND kind='sent' AND id<=?", (run, session, case, supplier, sent_id),
        ).fetchone()[0] if opened else None
        status = reply.get("status")
        stage = ("after_final_warning" if status == "final_offer" else "opening" if number == 1
                 else "negotiating" if number is not None else "unknown")
        sheets = reply.get("term_sheets") or []
        active = reply.get("standing_offer_id")
        sheet = next((s for s in sheets if s.get("term_sheet_id") == active), {}) if active else (
            sheets[0] if sheets else {})
        return {"stage": stage, "buyer_message_number": number,
                "supplier_status_before": status, "standing_terms_before": sheet.get("terms", {})}

    def episodes(self, supplier, case, session=None, run=None, limit=10):
        """Retrieve actual exchanges, never outcomes, scores or hidden benchmark data.

        Only the same supplier AND case qualify. Old quotes are evidence of a route,
        not live offers. Include the preceding buyer request to explain each reply.
        """
        if limit <= 0:
            return []
        excluded_run = run if session is None else None
        rows = self.db.execute(
            "SELECT id,timestamp,run_id,session_id,payload FROM events "
            "WHERE supplier_id=? AND case_id=? AND kind IN ('received','exchange') "
            "AND (? IS NULL OR session_id IS NULL OR session_id!=?) "
            "AND (? IS NULL OR run_id!=?) ORDER BY id DESC LIMIT 160",
            (supplier, case, session, session, excluded_run, excluded_run),
        ).fetchall()
        episodes, seen, contexts = [], set(), {}
        for event_id, timestamp, old_run, old_session, payload in rows:
            data = json.loads(payload)
            reply = data.get("supplier_reply", data)
            body = reply.get("body", "")
            sheets = [{"terms": s.get("terms", {})} for s in reply.get("term_sheets", [])]
            previous = self.db.execute(
                "SELECT id,payload FROM events WHERE run_id=? AND session_id IS ? AND case_id=? "
                "AND supplier_id=? AND kind='sent' AND id<? ORDER BY id DESC LIMIT 1",
                (old_run, old_session, case, supplier, event_id),
            ).fetchone()
            request = data.get("buyer_request") or (json.loads(previous[1]) if previous else {})
            sent_id = previous[0] if previous else None
            # The runner adds `from: buyer` when embedding the sent message in history.
            # Ignore that transport field; any content mismatch means unknown prior state.
            if previous and data.get("buyer_request"):
                recorded = json.loads(previous[1])
                if ({k: v for k, v in request.items() if k != "from"}
                        != {k: v for k, v in recorded.items() if k != "from"}):
                    sent_id = None
            context_key = (old_run, old_session, sent_id)
            if context_key not in contexts:
                contexts[context_key] = self._episode_context(old_run, old_session, case, supplier, sent_id)
            context = contexts[context_key]
            buyer_terms = [s.get("terms", {}) for s in request.get("term_sheets", [])]
            # Identical replies to different buyer moves must not erase those moves.
            # Collapse duplicate received/exchange records, not the action-response link.
            signature = json.dumps([request.get("body", ""), buyer_terms, context,
                                    reply.get("status"), body, sheets], sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            episodes.append({
                "source_id": f"history:{event_id}", "timestamp": timestamp, "case_id": case,
                "session_id": old_session, "status_then": reply.get("status"),
                "buyer_request": request.get("body", "")[:1600],
                "buyer_terms": buyer_terms, "context_before": context,
                "supplier_reply": body[:2500], "quoted_packages_then": sheets,
                "currently_executable": False,
            })
        # Reserve part of the historical budget for distinct opening actions. Choose
        # by recency and terms, never score; repeated outcomes cannot consume every slot.
        protected, opening_keys = {}, set()
        opening_limit = min(limit // 2, max(1, limit // 3))
        for episode in episodes:
            if len(protected) >= opening_limit:
                break
            if episode["context_before"]["stage"] != "opening" or not episode["buyer_terms"]:
                continue
            key = tuple(sorted(json.dumps(terms, sort_keys=True) for terms in episode["buyer_terms"]))
            if key not in opening_keys:
                opening_keys.add(key)
                protected[episode["source_id"]] = episode
        # Fill the rest of the protected half with priced alternatives/evidence routes.
        # At least half the budget remains available for the newest exchanges.
        special = [e for e in episodes if len(e["quoted_packages_then"]) > 1 or any(
            word in e["supplier_reply"].lower() for word in ("rebas", "recalculat", "approval", "breakdown")
        )]
        for episode in special:
            if len(protected) >= limit // 2:
                break
            protected.setdefault(episode["source_id"], episode)
        selected = {**protected, **{e["source_id"]: e for e in episodes[:limit]}}
        return list(selected.values())[:limit]
