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
