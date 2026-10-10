"""Scripted probe of one arena case: send a fixed sequence of packages and arguments, print replies.

Used to map how a supplier responds to specific moves (one session per run), so the agent's
strategy rests on observed behaviour instead of guesses.

    uv run python tools/probe_p18.py scenario.json
scenario.json: {"case": "case:P18", "supplier": "sup:70740",
                "steps": [{"terms": {...}, "claims": ["kind", ...], "text": "...",
                           "accept_if_below": 5.3}, ...]}
Each step is sent only while the thread is open; a final_offer or the last step is accepted when it
beats the alternative. Claims are taken from hollerau.intel by kind (checked IDs and figures).
"""

import json
import os
import sys

from arena_kit.cli import load_env
from arena_kit.client import ArenaClient
from arena_kit.cost import total_cost
from arena_kit.data import DataPackage

from hollerau import intel


def describe(t):
    clause = t.get("index_clause")
    idx = f"index on {clause['series']} with deadband {clause['deadband_pct']}%" if clause else "no index clause"
    return (f"EUR {t['unit_price']:.2f} per unit, payment {t['payment_days']} days net, "
            f"{t['contract_months']} months, {idx}")


def main(path):
    load_env()
    sc = json.load(open(path))
    pkg = DataPackage(os.environ.get("ARENA_DATA", "data/package"))
    pkg.lookup("")
    client = ArenaClient()
    opened = client.open_session(sc["case"])
    sid_session, case = opened["session_id"], opened["case"]
    sup = sc["supplier"]
    first = opened["threads"][sup][0]
    asked = first["term_sheets"][0]["terms"]["unit_price"]
    dossier = intel.build(case, sup, pkg, asked)
    claims = {c.kind: c for c in dossier.claims}
    from hollerau.analytical.retrieval import retrieve  # forecast evidence (team module)

    try:
        _, extra, _ = retrieve(pkg, case, sup)
        for c in extra:
            claims.setdefault(c.kind, c)
    except Exception as e:  # probe still runs without it
        print("retrieval unavailable:", e)
    alt = case["buyer"]["alternative"]["terms"]
    c_alt = total_cost(case, alt)
    std = {"payment_days": 30, "contract_months": 12, "index_clause": None}
    print("session", sid_session, "asked", asked)
    status, standing = "open", first["term_sheets"][0]
    for i, step in enumerate(sc["steps"]):
        if status in ("final_offer", "agreed"):
            break
        used = [claims[k] for k in step.get("claims", []) if k in claims]
        body = "\n\n".join(
            ["Dear Mr Seidl,", step.get("text", "Thank you for your reply.")]
            + [c.sentence for c in used]
            + step.get("extra", [])
            + [f"We propose: {describe(step['terms'])}.", "Kind regards, Purchasing, Hollerau Pumpenwerke"]
        )
        sheets = step.get("sheets") or [step["terms"]]
        if len(sheets) > 1:
            body = body.replace(f"We propose: {describe(step['terms'])}.",
                                "We propose either of these packages: "
                                + " | ".join(f"Option {j + 1}: {describe(t)}" for j, t in enumerate(sheets)) + ".")
        msg = {"subject": "Re: " + case["title"], "body": body, "term_sheets": [{"terms": t} for t in sheets]}
        reply = client.send_message(sid_session, sup, msg)
        status = reply.get("status")
        standing = (reply.get("term_sheets") or [standing])[0]
        t = standing["terms"]
        print(f"\n[{i + 1}] US {describe(step['terms'])} | claims {[c.kind for c in used]}")
        for alt_sheet in (reply.get("term_sheets") or [])[1:]:
            a = alt_sheet["terms"]
            print(f"    (alt) {a.get('unit_price')} {a.get('payment_days')}d "
                  f"db{(a.get('index_clause') or {}).get('deadband_pct', '-')} {a.get('contract_months')}m")
        print(f"    SUP {status}: {t.get('unit_price')} {t.get('payment_days')}d "
              f"db{(t.get('index_clause') or {}).get('deadband_pct', '-')} {t.get('contract_months')}m "
              f"| checks {[r['result'] for r in reply.get('claim_results') or []]}")
        print("    " + (reply.get("body") or "").replace("\n", " ")[:700])
    c = total_cost(case, standing["terms"], std)
    if c < c_alt:
        res = client.send_message(sid_session, sup, {"action": {"type": "accept",
                                                                "term_sheet_id": standing["term_sheet_id"]}})
        r = res.get("result", res)
        print("\nRESULT score", r.get("score"), "c_deal", r.get("c_deal"), "terms", standing["terms"])
    else:
        print("\nno accept: standing costs", c, ">= alternative", c_alt)


if __name__ == "__main__":
    main(sys.argv[1])
