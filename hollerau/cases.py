"""Practice-like cases for the simulator, built from the data package.

Sources:
  kit        the kit's sim cases S01-S03 (real case-file shape)
  letters    the price letters in the data (doc:...-P01 etc.): part, supplier, asked price, notice
  random     any (part, supplier) from the source list, with a random type, goal and levers
  cached     case files saved from the arena (`hollerau/cases/*.json`, written by `cache_case`)
Each comes with an opening quote (stated + standard terms) so a SimSupplier can play it.
"""

import json
import random
from pathlib import Path

from arena_kit.sim import load_cases

CACHE = Path(__file__).with_name("cases")
GOAL_RATES = {  # fallback risk %, index risk %
    "stabilise": (8, 2),
    "secure_supply": (12, 2),
    "quality_first": (5, 1),
    "leverage": (3, 1),
    "routine": (5, 2),
}
PAYMENT = [14, 30, 45, 60, 90]
LEAD = [21, 28, 35, 42, 49, 56]


def _q(package, sql, params=()):
    return package.query(sql, params)


def _supplier_ctx(package, sid):
    ctr = _q(package, "SELECT id, payment_days, incoterm, notice_days FROM contracts WHERE supplier_id = ?", (sid,))
    return ctr[0] if ctr else {"id": None, "payment_days": 30, "incoterm": "FCA", "notice_days": 90}


def _need(package, part):
    fc = _q(package, "SELECT qty_next_12m FROM forecasts WHERE part_id = ? ORDER BY snapshot_month DESC LIMIT 1", (part,))
    return int(fc[0]["qty_next_12m"]) if fc else 5000


def _price(package, part, sid):
    rows = _q(
        package,
        "SELECT price FROM price_conditions WHERE part_id = ? AND supplier_id = ? ORDER BY valid_from DESC LIMIT 1",
        (part, sid),
    )
    if rows:
        return rows[0]["price"]
    rows = _q(package, "SELECT standard_price FROM parts WHERE id = ?", (part,))
    return rows[0]["standard_price"] if rows else 100.0


def make_case(package, rng, part, suppliers, ctype, goal=None, asked_pct=None, trigger=None, cid=None):
    """A case file in the arena's shape, plus `_openings` {sid: (stated, standard)} for the sim."""
    goal = goal or rng.choice(list(GOAL_RATES))
    sid0 = suppliers[0]
    current = _price(package, part, sid0)
    need = _need(package, part)
    horizon = rng.choice([1, 2, 2, 3])
    fr, ir = GOAL_RATES[goal]
    levers_pool = ["payment_days", "contract_months", "lead_time_days", "incoterm"]
    if ctype in ("renewal", "bundling"):
        levers_pool.append("volume_per_year")
    k = rng.randint(1, 3)
    negotiable = ["unit_price"] + rng.sample(levers_pool, k)
    ctx = _supplier_ctx(package, sid0)
    freight = {"EXW": round(current * 0.03, 2), "FCA": round(current * 0.02, 2), "DAP": 0.0}
    term_options = {
        "payment_days": PAYMENT,
        "contract_months": sorted({12, 24, 12 * horizon, 36} & {12, 24, 36}),
        "lead_time_days": LEAD,
        "incoterm": ["EXW", "FCA", "DAP"],
        "volume_per_year": sorted({need, int(need * 0.8), int(need * 1.2)}),
    }
    term_options = {f: term_options[f] for f in negotiable if f in term_options}
    fixed = {
        "lead_time_days": 42,
        "volume_per_year": need,
        "contract_months": 12 * horizon,
        "index_clause": None,
        "incoterm": ctx["incoterm"] or "FCA",
        "tooling_eur": 0,
        "payment_days": ctx["payment_days"] or 30,
    }
    fixed = {f: v for f, v in fixed.items() if f not in negotiable}
    spend = need * current
    buyer = {
        "need_per_year": need,
        "horizon_years": horizon,
        "current_unit_price": current,
        "fallback_unit_price": round(current * rng.uniform(1.10, 1.20), 2),
        "interest_rate": 0.08,
        "reference_payment_days": 60,
        "need_lead_time_days": 42,
        "category_goal": goal,
        "fallback_risk_pct": fr,
        "index_risk_pct": ir,
        "late_cost_per_day": 200,
        "cost_per_defect": 50,
        "freight_eur_per_unit": freight,
        "index_paths": {},
        "must_haves": [],
        "alternative": {"kind": "none", "ref": None, "terms": {}},
    }
    if goal in ("stabilise", "secure_supply"):
        buyer["sustainable_margin_pct"] = rng.choice([6, 8, 10])
        buyer["relationship_eur_per_point"] = round(spend * rng.uniform(0.002, 0.006), 0)
    if "lead_time_days" in negotiable and rng.random() < 0.5:
        buyer["must_haves"].append({"field": "lead_time_days", "op": "<=", "value": 42})
    asked_pct = asked_pct if asked_pct is not None else rng.uniform(2, 10)
    openings = {}
    for i, sid in enumerate(suppliers):
        base = _price(package, part, sid) if ctype != "rfq" else current * rng.uniform(0.92, 1.08)
        std = {
            "payment_days": rng.choice([30, 30, 45, 60]),
            "lead_time_days": rng.choice([35, 42, 49]),
            "contract_months": 12,
            "incoterm": rng.choice(["FCA", "FCA", "EXW", "DAP"]),
            "volume_per_year": need,
        }
        stated = {f: std.get(f, fixed.get(f)) for f in negotiable if f != "unit_price"}
        for f in list(stated):
            opts = term_options.get(f)
            if opts and stated[f] not in opts:
                stated[f] = opts[0]
        stated["unit_price"] = round(base * (1 + asked_pct / 100) * (1 + 0.02 * i), 2)
        openings[sid] = (stated, {f: v for f, v in std.items() if f in negotiable or f in ("payment_days", "incoterm")})
    if rng.random() < 0.4:
        first = openings[sid0][0]
        alt_price = round(first["unit_price"] * rng.uniform(1.00, 1.08), 2)
        buyer["alternative"] = {
            "kind": "quote",
            "ref": None,
            "terms": {"unit_price": alt_price, "payment_days": 30, "lead_time_days": 42, "incoterm": "DAP"},
        }
    title = _q(package, "SELECT description FROM parts WHERE id = ?", (part,))
    title = title[0]["description"] if title else part
    drivers = _q(package, "SELECT series_id FROM cost_drivers WHERE part_id = ?", (part,))
    refs = [f"sc:{s.split(':')[1]}@2026Q3" for s in suppliers]
    return {
        "case_id": cid or f"case:X{rng.randrange(10**6):06d}",
        "set": "local",
        "type": ctype,
        "title": f"{title}: {ctype.replace('_', ' ')}",
        "briefing": f"Local case. You buy {part} from {', '.join(suppliers)}.",
        "trigger_doc": trigger,
        "parts": [part],
        "suppliers": suppliers,
        "negotiable": negotiable,
        "fixed_terms": fixed,
        "term_options": term_options,
        "buyer": buyer,
        "round_limit": 10,
        "refs": refs + [f"idx:{d['series_id']}@2026-08" for d in drivers],
        "_openings": openings,
    }


def letter_cases(package, rng):
    """One case per price letter in the data (the practice triggers -P01, -P02, ...)."""
    out = []
    rows = _q(package, "SELECT id, supplier_id, part_ids, asked_pct FROM documents WHERE asked_pct IS NOT NULL")
    for r in rows:
        part = r["part_ids"].split(";")[0]
        out.append(make_case(package, rng, part, [r["supplier_id"]], "price_increase", asked_pct=r["asked_pct"],
                             trigger=r["id"], cid=f"case:L{r['id'][-3:]}"))
    return out


def random_cases(package, rng, n):
    pairs = _q(package, "SELECT part_id, supplier_id, status FROM sourcing")
    by_part = {}
    for p in pairs:
        by_part.setdefault(p["part_id"], []).append(p["supplier_id"])
    out = []
    for _ in range(n):
        part = rng.choice(sorted(by_part))
        sups = by_part[part]
        ctype = rng.choice(["price_increase", "renewal", "rfq"] if len(sups) > 1 else ["price_increase", "renewal"])
        chosen = rng.sample(sups, min(len(sups), rng.randint(2, 3))) if ctype == "rfq" else [sups[0]]
        out.append(make_case(package, rng, part, chosen, ctype))
    return out


def kit_cases(rng):
    out = []
    for case in load_cases().values():
        b = case["buyer"]
        openings = {}
        for i, sid in enumerate(case["suppliers"]):
            price = round((b.get("current_unit_price") or b["fallback_unit_price"]) * (1.10 + 0.02 * i), 2)
            std = {f: (case["term_options"].get(f) or [None])[0] for f in case["negotiable"][1:]}
            stated = {**std, "unit_price": price}
            openings[sid] = (stated, std)
        out.append({**case, "_openings": openings})
    return out


def cached_cases():
    return [json.loads(p.read_text()) for p in sorted(CACHE.glob("*.json"))] if CACHE.is_dir() else []


def cache_case(case, threads):
    """Save an arena case file with its opening quotes, to replay it locally later."""
    from arena_kit.docs import standard_terms
    from arena_kit.play import standing

    CACHE.mkdir(exist_ok=True)
    openings = {sid: (standing(ev)[1], standard_terms(ev)) for sid, ev in threads.items()}
    path = CACHE / f"{case['case_id'].replace(':', '_')}.json"
    path.write_text(json.dumps({**case, "_openings": openings}, indent=1, default=str))


def suite(package, seed=0, n_random=40):
    rng = random.Random(seed)
    return cached_cases() + kit_cases(rng) + letter_cases(package, rng) + random_cases(package, rng, n_random)
