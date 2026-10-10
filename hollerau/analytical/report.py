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
    decoded = [json.loads(payload) for _, _, kind, payload in events if kind == "decision_record"]
    outcomes = {p["decision_id"]: p for _, _, k, raw in events if k == "plan_outcome" for p in [json.loads(raw)]}
    if decoded:
        calls = [c for row in decoded for c in row["model_calls"]]
        ok = sum(c.get("status") == "ok" for c in calls)
        parts.append(f"<p><strong>{len(decoded)} traceable decisions; {ok}/{len(calls)} model calls succeeded.</strong> "
                     "A successful call is not proof of a correct strategy.</p>")
        for row in decoded:
            plan = row["plan"]
            outcome = outcomes.get(row["decision_id"], {})
            fields = {
                "Phase": row["phase"], "Action": row["selection"]["action_id"],
                "Reason": row["selection"]["rationale"], "Evidence / assumption": plan["basis"],
                "Expected response": plan["expected_response"],
                "Actual response": outcome.get("observed_response", "No response recorded"),
                "Prediction matched": outcome.get("response_matched"),
                "Expected price range": [plan["expected_price_low"], plan["expected_price_high"]],
                "If counteroffer": plan["if_counteroffer"], "If unchanged": plan["if_unchanged"],
                "If accepted": plan["if_accepted"], "If walkout": plan["if_walkout"],
                "Revised plan": plan["revision_from_previous"],
                "Stop condition": row["selection"]["continuation_review"]["stop_condition"],
                "Decision seconds": row["timing"]["total_decision_seconds"],
            }
            cells = ''.join('<tr><th>' + html.escape(k) + '</th><td>' +
                            html.escape(str(v)) + '</td></tr>' for k, v in fields.items())
            parts.append('<section><h2>' + html.escape(row["decision_id"]) + '</h2><table>' + cells + '</table></section>')
        parts.append('<h2>Underlying records</h2>')
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
        "section{background:white;padding:20px;margin:20px 0;border-radius:8px}th,td{text-align:left;vertical-align:top;padding:7px}th{min-width:180px}h2{font-size:16px;overflow-wrap:anywhere}"
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
