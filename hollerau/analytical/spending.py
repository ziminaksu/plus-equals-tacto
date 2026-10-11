"""Restart-safe upper-bound reservations for standard OpenAI Responses calls.

Rates checked 2026-10-11 against the official model pages. No tools, priority
tier, third-party endpoint, retries, or automatic model substitution are covered.
Unknown outcomes keep their entire reservation; concurrent runs share one ledger.
"""

import json
import math
import sqlite3
import time
from contextlib import contextmanager
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

# USD per million tokens. Input includes the documented 1.25x cache-write rate;
# ignoring cache discounts makes reconciled usage a conservative cost estimate.
RATES = {"gpt-6-astra": (Decimal("12.5"), Decimal("50")),
         "gpt-6-sol": (Decimal("2.5"), Decimal("10"))}


class SpendLimitReached(RuntimeError):
    """No further paid call is authorized by this ledger."""


def micro_cost(model, input_tokens, output_tokens):
    incoming, outgoing = RATES[model]
    return int((input_tokens * incoming + output_tokens * outgoing).to_integral_value(rounding=ROUND_CEILING))


class SpendLedger:
    def __init__(self, path, limit_usd):
        cap = Decimal(str(limit_usd))
        if not cap.is_finite() or cap <= 0:
            raise ValueError("spending limit must be positive and finite")
        self.cap = int((cap * 1_000_000).to_integral_value())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS spending_limit (id INTEGER PRIMARY KEY, micro_usd INTEGER, blocked INTEGER);
                CREATE TABLE IF NOT EXISTS charges (id INTEGER PRIMARY KEY, created REAL, model TEXT,
                    reserved INTEGER, charged INTEGER, status TEXT, input_tokens INTEGER, output_tokens INTEGER);
            """)
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO spending_limit VALUES(1,?,0)", (self.cap,))
            if db.execute("SELECT micro_usd FROM spending_limit WHERE id=1").fetchone()[0] != self.cap:
                raise ValueError("cannot change an existing spending ledger's limit")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def snapshot(self):
        with self.connect() as db:
            spent = db.execute("SELECT COALESCE(SUM(charged),0) FROM charges").fetchone()[0]
            held = db.execute("SELECT COALESCE(SUM(charged),0) FROM charges WHERE status='reserved'").fetchone()[0]
            blocked = db.execute("SELECT blocked FROM spending_limit WHERE id=1").fetchone()[0]
        return {"limit_usd": self.cap / 1e6, "accounted_usd": spent / 1e6,
                "unknown_outcome_reserve_usd": held / 1e6,
                "remaining_usd": max(0, self.cap - spent) / 1e6, "blocked": bool(blocked)}

    def reserve(self, payload):
        model = payload["model"]
        if model not in RATES or payload.get("tools") or payload.get("service_tier") != "default":
            raise ValueError("spending guard requires a priced model, standard tier and no tools")
        # UTF-8 byte length bounds text BPE tokens without a tokenizer download.
        # Count the ENTIRE request, including the schema, plus framing headroom.
        incoming = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 2048
        if incoming > 100_000:
            raise ValueError("budget mode requires a compact short-context request")
        reserve = micro_cost(model, incoming, payload["max_output_tokens"])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            spent = db.execute("SELECT COALESCE(SUM(charged),0) FROM charges").fetchone()[0]
            blocked = db.execute("SELECT blocked FROM spending_limit WHERE id=1").fetchone()[0]
            if blocked or spent + reserve > self.cap:
                raise SpendLimitReached("insufficient reserved budget for another complete response")
            row = db.execute("INSERT INTO charges VALUES(NULL,?,?,?,?, 'reserved',NULL,NULL)",
                             (time.time(), model, reserve, reserve))
            return row.lastrowid

    def settle(self, reservation, usage):
        counts = [usage.get("input_tokens"), usage.get("output_tokens")]
        if any(type(x) is not int or x < 0 or not math.isfinite(x) for x in counts):
            return  # No trustworthy usage: hold the whole reservation, including after a timeout.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            model, reserved, status = db.execute(
                "SELECT model,reserved,status FROM charges WHERE id=?", (reservation,)).fetchone()
            if status != "reserved":
                raise ValueError("reservation already settled")
            charge = micro_cost(model, *counts)
            if charge > reserved:
                # Fail closed if the provider violates the assumed token bound.
                db.execute("UPDATE spending_limit SET blocked=1 WHERE id=1")
            db.execute("UPDATE charges SET charged=?,status='usage',input_tokens=?,output_tokens=? WHERE id=?",
                       (charge, *counts, reservation))

    def block(self):
        with self.connect() as db:
            db.execute("UPDATE spending_limit SET blocked=1 WHERE id=1")

    def reject_for_billing(self, reservation, code):
        """Only a definitive pre-inference credit rejection releases a reservation."""
        if code not in ("credit_balance_exhausted", "insufficient_quota"):
            raise ValueError("not a definitive billing rejection")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE spending_limit SET blocked=1 WHERE id=1")
            db.execute("UPDATE charges SET charged=0,status='billing_rejected' WHERE id=? AND status='reserved'",
                       (reservation,))
