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
        """)
        self.db.commit()

    def log(self, run, kind, payload, case=None, supplier=None, session=None):
        self.db.execute(
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

    def episodes(self, supplier, case, session=None, run=None, limit=10):
        """Retrieve actual exchanges, never outcomes, scores or hidden benchmark data.

        Only the same supplier AND case qualify. Old quotes are evidence of a route,
        not live offers. Include the preceding buyer request to explain each reply.
        """
        excluded_run = run if session is None else None
        rows = self.db.execute(
            "SELECT id,timestamp,run_id,session_id,payload FROM events "
            "WHERE supplier_id=? AND case_id=? AND kind IN ('received','exchange') "
            "AND (? IS NULL OR session_id IS NULL OR session_id!=?) "
            "AND (? IS NULL OR run_id!=?) ORDER BY id DESC LIMIT 160",
            (supplier, case, session, session, excluded_run, excluded_run),
        ).fetchall()
        episodes, seen = [], set()
        for event_id, timestamp, old_run, old_session, payload in rows:
            data = json.loads(payload)
            reply = data.get("supplier_reply", data)
            body = reply.get("body", "")
            sheets = [{"terms": s.get("terms", {})} for s in reply.get("term_sheets", [])]
            signature = json.dumps([body, sheets], sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            previous = self.db.execute(
                "SELECT payload FROM events WHERE run_id=? AND session_id IS ? AND case_id=? "
                "AND supplier_id=? AND kind='sent' AND id<? ORDER BY id DESC LIMIT 1",
                (old_run, old_session, case, supplier, event_id),
            ).fetchone()
            request = data.get("buyer_request") or (json.loads(previous[0]) if previous else {})
            episodes.append({
                "source_id": f"history:{event_id}", "timestamp": timestamp, "case_id": case,
                "session_id": old_session, "status_then": reply.get("status"),
                "buyer_request": request.get("body", "")[:1600],
                "buyer_terms": [s.get("terms", {}) for s in request.get("term_sheets", [])],
                "supplier_reply": body[:2500], "quoted_packages_then": sheets,
                "currently_executable": False,
            })
        # Preserve earlier priced alternatives instead of letting repeated price-only
        # replies push them out. Keep half the budget for the newest exchanges too.
        special = [e for e in episodes if len(e["quoted_packages_then"]) > 1 or any(
            word in e["supplier_reply"].lower() for word in ("rebas", "recalculat", "approval", "breakdown")
        )]
        selected = {e["source_id"]: e for e in special[:limit // 2] + episodes[:limit]}
        return list(selected.values())[:limit]
