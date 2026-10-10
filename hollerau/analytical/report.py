"""Render the local SQLite audit without contacting Arena or an LLM."""

import argparse
import html
import json
import sqlite3
from pathlib import Path


def render(db_path, run_id, output):
    db = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    events = db.execute(
        "SELECT case_id,supplier_id,kind,payload FROM events WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    parts = [
        f"<h1>Negotiation audit: {html.escape(run_id)}</h1>",
        "<p>Estimated beliefs and predictions are not verified supplier facts. "
        "Expand a record to inspect its inputs.</p>",
    ]
    for case, supplier, kind, payload in events:
        obj = json.loads(payload)
        # Keep candidate detail available while avoiding a wall of text on first view.
        if kind == "decision":
            action = obj.get("action", {}).get("message", {}).get("action", {}).get("type", "offer")
            title = f"{case} / {supplier} / decision: {action}"
        else:
            title = f"{case} / {supplier or 'case'} / {kind}"
        parts.append(
            "<details><summary>"
            + html.escape(title)
            + "</summary><pre>"
            + html.escape(json.dumps(obj, indent=2, ensure_ascii=False))
            + "</pre></details>"
        )
    doc = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Tacto audit</title>'
        "<style>body{font:16px system-ui;margin:40px auto;max-width:1100px;padding:0 20px;"
        "background:#f7faf7;color:#173b39}"
        "details{background:white;padding:15px;margin:10px 0;border-radius:8px}summary{cursor:pointer;font-weight:bold}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}</style><body>"
        + "".join(parts)
        + "</body></html>"
    )
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(doc)
    db.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="hollerau/logs/analytical.sqlite")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", default="hollerau/logs/audit.html")
    args = ap.parse_args()
    render(args.db, args.run_id, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
