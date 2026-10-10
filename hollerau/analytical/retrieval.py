"""Bounded case-specific evidence, including answers to supplier requests.

Public facts are exposed even when they do not support a price reduction. Supplier
text selects retrieval topics; it cannot inject SQL or expand access beyond this case.
"""

import json
import re

from ..intel import Claim, index_change


def retrieve(package, case, supplier_id, latest_body=""):
    if package is None:
        return {}, [], {"status": "no_public_data_package", "topics": []}
    parts = case.get("parts", [])
    wants_forecast = bool(re.search(r"forecast|volume|commit|call.off|schedule", latest_body, re.I))
    sources, claims, topics, failures = {}, [], [], []

    def query(sql, params):
        try:
            return package.query(sql, params)
        except (ValueError, TypeError, OSError) as exc:
            failures.append(type(exc).__name__)
            return []
        except Exception as exc:
            # Absence must remain 'lookup unavailable', never 'there is no forecast'.
            failures.append(type(exc).__name__)
            return []

    for part in parts:
        forecasts = query("SELECT * FROM forecasts WHERE part_id=? ORDER BY snapshot_month DESC LIMIT 1", (part,))
        for row in forecasts:
            ref = row["id"]
            fact = package.facts.get(ref, {})
            lines = query("SELECT target_month,qty FROM forecast_lines WHERE fc_id=? ORDER BY target_month", (ref,))
            shared = bool(row.get("shared_with_suppliers"))
            payload = {"topic": "demand_forecast", "source_id": ref, "record": row,
                       "citable_fact": fact, "shareable": shared,
                       "monthly_rows": lines if wants_forecast else [],
                       "monthly_sum": sum(x["qty"] for x in lines) if lines else None,
                       "caution": "Planning forecast is not an extra binding commitment. Keep case fixed volume. "
                                  "Forecast dates may differ from contract dates. Do not infer the time basis of "
                                  "change_pct; compare named snapshots explicitly if needed."}
            sources[ref] = json.dumps(payload, ensure_ascii=False)
            topics.append({"topic": "forecast", "source_id": ref, "found": True, "shareable": shared,
                           "requested_in_latest_reply": wants_forecast})
            quantity = row.get("qty_next_12m")
            # Only offer externally citable claims whose key quantity matches facts.json.
            if shared and quantity is not None and fact.get("volume_per_year") == quantity:
                period = f"{lines[0]['target_month']} through {lines[-1]['target_month']}" if lines else (
                    f"the next {row['horizon_months']} months")
                text = (f"Our shared forecast snapshot {row['snapshot_month']} plans {quantity} {row['uom']} "
                        f"for {period} ({ref}); this is planning evidence, with binding volume and delivery "
                        "obligations limited to the case terms")
                claims.append(Claim("forecast", [ref], text + ".", 1.0, quantity))
        if not forecasts:
            topics.append({"topic": "forecast", "part": part, "found": False,
                           "status": "lookup_unavailable" if failures else "not_found_in_public_package"})
        drivers = query("SELECT series_id,weight,source FROM cost_drivers WHERE part_id=?", (part,))
        rows = []
        for driver in drivers:
            change = index_change(package.facts, driver["series_id"])
            if not change:
                rows.append({**driver, "change": "period unavailable"})
                continue
            earlier, later, pct = change
            rows.append({**driver, "earlier": {"id": earlier, **package.facts[earlier]},
                         "later": {"id": later, **package.facts[later]}, "change_pct": pct})
            # A rising input argues for the supplier (P18: +5.9 % / +12.3 % on the board); it stays in
            # the sources as context, only a flat or falling input is offered as a citable argument.
            if pct > 0:
                continue
            claims.append(Claim("index_context", [earlier, later],
                                f"The {driver['series_id']} index changed {pct:+.1f}% between the named observations "
                                f"({earlier} to {later}); this is an input movement, not a whole-product price change.",
                                0.5, pct))
        if rows:
            sources[f"drivers:{part}"] = json.dumps({"topic": "cost_drivers", "rows": rows,
                "covered_weight": sum(r.get("weight") or 0 for r in drivers),
                "caution": "Weights are category-team estimates, not audited supplier cost shares. Series dates "
                           "can differ; remaining costs are unmodelled. A rise can support the supplier's case."})
            topics.append({"topic": "cost_drivers", "part": part, "found": True})
    return sources, claims, {"status": "partial" if failures else "complete", "topics": topics,
                            "lookup_errors": failures,
                            "supplier_id": supplier_id,
                            "rule": "Never claim evidence is absent merely because an earlier message omitted it."}
