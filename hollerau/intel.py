"""The dossier: what the data says about a supplier and part, as numbers the strategy uses and as
arguments that will check out (ID + figure computed from facts.json, the arena's own source).

Arguments are only proposed when they help: an index that rose less than the asked increase, a
should-cost below the asked price, a short notice against the contract, a weak scorecard, a cheaper
quote. Each carries a `strength` so the strategy can spend the strong ones at the right time.
"""

import re
from dataclasses import dataclass, field

# Conservative priors: generic mentions of "cash" or "capacity" are NOT evidence.
# Explicit denials veto a positive signal in the same note.
CASH_WORDS = re.compile(
    r"cash (?:shortage|shortfall|crunch|pressure|constraints)|"
    r"(?:liquidity|working.capital) (?:shortage|shortfall|pressure|problem|constraint)|"
    r"(?:need|prefer|require|appreciate) (?:earlier|early|faster|advance) payment|"
    r"(?:payment|invoices?) within \d+ days|"
    r"(?:cash.flow|liquidity) (?:is|remains) (?:tight|strained)",
    re.I,
)
CASH_DENIAL = re.compile(
    r"(?:no|without|not experiencing|do not have|don't have) "
    r"(?:cash.flow|cash|liquidity|working.capital) "
    r"(?:issues?|problems?|shortages?|shortfalls?|constraints?|pressure)|"
    r"(?:cash.flow|liquidity) (?:is|remains) (?:healthy|stable|strong)",
    re.I,
)
CAPACITY_WORDS = re.compile(
    r"(?:spare|unused|idle|available|excess|free) capacity|"
    r"capacity (?:is|remains) (?:available|free|unused)|"
    r"(?:have|can offer|can provide) (?:a )?second shift|"
    r"(?:can|could|able to) (?:take|accept|supply|deliver) (?:more|additional|extra) "
    r"(?:volume|units|orders?)",
    re.I,
)
CAPACITY_DENIAL = re.compile(
    r"(?:no|without|lack of) (?:spare|unused|idle|available|excess|free) capacity|"
    r"capacity (?:is|remains) (?:fully booked|full|at (?:its |our )?limit|constrained|limited)|"
    r"(?:cannot|can't|unable to|not able to) (?:take|accept|supply|deliver) "
    r"(?:more|additional|extra) (?:volume|units|orders?)|"
    r"(?:fully booked|no room for additional volume)",
    re.I,
)


def supplier_signals_from_note(body):
    """Only explicit, non-contradicted claims may shift supplier priors."""
    return {
        "cash_short": bool(CASH_WORDS.search(body)) and not bool(CASH_DENIAL.search(body)),
        "spare_capacity": bool(CAPACITY_WORDS.search(body)) and not bool(CAPACITY_DENIAL.search(body)),
    }
STALE_COSTING = re.compile(r"spreadsheet|not followed|last updated|own figures|costing", re.I)
APPROVAL = re.compile(r"approval|committee|board|boss|head office|group", re.I)
PARTNER = re.compile(r"partnership|kept supplying|loyal|many years|relationship", re.I)


@dataclass
class Claim:
    kind: str
    refs: list
    sentence: str  # one argument per sentence, the ID and its figure in it
    strength: float
    figure: float | None = None


@dataclass
class Dossier:
    supplier: str
    part: str | None
    full_cost: float | None = None  # supplier's full cost per price unit (should-cost), if known
    cost_ref: str | None = None
    index_change_pct: float | None = None  # cost-driver weighted change over 12 months
    asked_pct: float | None = None
    cash_short: bool = False
    spare_capacity: bool = False
    stale_costing: bool = False
    approval_ladder: bool = False
    wants_partnership: bool = False
    notes: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    reference_prices: dict = field(default_factory=dict)  # our own recent order prices (anchors)


def _months_back(month, n):
    y, m = map(int, month.split("-"))
    k = y * 12 + m - 1 - n
    return f"{k // 12:04d}-{k % 12 + 1:02d}"


def _facts(package, case):
    facts = dict(package.facts) if package else {}
    facts.update(case.get("facts") or {})
    return facts


def index_change(facts, series, horizon=12):
    """(earlier_id, later_id, change %) over `horizon` months ending at the series' last month."""
    ids = sorted(k for k in facts if k.startswith(f"idx:{series}@"))
    if not ids:
        return None
    later = ids[-1]
    earlier = f"idx:{series}@{_months_back(later.split('@')[1], horizon)}"
    if earlier not in facts:
        return None
    v1, v2 = facts[earlier]["value"], facts[later]["value"]
    return earlier, later, round((v2 / v1 - 1) * 100, 1)


def index_peak_drop(facts, series, horizon=12):
    """(peak_id, latest_id, change %) from the series' highest point in the last `horizon` months
    to its latest value: two points of one series, at most 12 months apart, ending at the latest."""
    ids = sorted(k for k in facts if k.startswith(f"idx:{series}@"))
    if len(ids) < 2:
        return None
    later = ids[-1]
    start = _months_back(later.split("@")[1], horizon)
    window = [k for k in ids[:-1] if k.split("@")[1] >= start]
    if not window:
        return None
    peak = max(window, key=lambda k: facts[k]["value"])
    v1, v2 = facts[peak]["value"], facts[later]["value"]
    return peak, later, round((v2 / v1 - 1) * 100, 1)


def _query(package, sql, params=()):
    try:
        return package.query(sql, params) if package and package.db else []
    except Exception:
        return []


def build(case, supplier_id, package=None, asked_price=None):
    """The dossier for one supplier of the case. `asked_price`: its opening price."""
    facts = _facts(package, case)
    part = (case.get("parts") or [None])[0]
    d = Dossier(supplier=supplier_id, part=part)
    b = case["buyer"]
    current = b.get("current_unit_price")
    if asked_price and current:
        d.asked_pct = round((asked_price / current - 1) * 100, 1)

    # should-cost: the supplier's plant, no margin (error 5-15 %)
    if part and (sc := facts.get(f"cost:{part.split(':')[1]}")):
        plant = _query(package, "SELECT supplier_id FROM should_cost WHERE id = ?", (f"cost:{part.split(':')[1]}",))
        if not plant or plant[0]["supplier_id"] in (None, "", supplier_id):  # it models this supplier's plant
            d.full_cost, d.cost_ref = sc["unit_cost"], f"cost:{part.split(':')[1]}"

    # cost drivers -> weighted index change, and per-series arguments
    drivers = _query(package, "SELECT series_id, weight FROM cost_drivers WHERE part_id = ?", (part,))
    refs_series = {r.split("@")[0][4:] for r in case.get("refs", []) if r.startswith("idx:")}
    series = {r["series_id"]: r["weight"] for r in drivers} or {s: None for s in refs_series}
    weighted, wsum, index_claims = 0.0, 0.0, []
    for s, w in series.items():
        ch = index_change(facts, s)
        if not ch:
            continue
        e, l_, pct = ch
        if w:
            weighted += w * pct
            wsum += w
        index_claims.append((s, e, l_, pct, w or 0.0))
    if wsum:
        d.index_change_pct = round(weighted, 2)  # share of price that follows the drivers
    asked = d.asked_pct if d.asked_pct is not None else 0.0
    for s, e, l_, pct, w in sorted(index_claims, key=lambda x: x[3]):
        # only data that argues for us: a falling index, or one far below the asked increase
        if pct <= 0 or (asked >= 3 and pct < 0.4 * asked):
            sentence = f"The index {s} moved {pct:+.1f}% over the last twelve months ({e} to {l_})."
            d.claims.append(Claim("index", [e, l_], sentence, 0.5 + 0.5 * (w or 0.3) + 0.02 * (asked - pct), pct))

    # should-cost below the ask: a strong argument (only when it is clearly below)
    if d.full_cost and asked_price and d.full_cost * 1.06 < asked_price:
        d.claims.append(
            Claim(
                "should_cost",
                [d.cost_ref],
                f"Our bottom-up should-cost for this part is EUR {d.full_cost:.2f} per unit ({d.cost_ref}).",
                1.2,
                d.full_cost,
            )
        )

    # notice: the trigger letter against the contract
    trig = case.get("trigger_doc")
    if trig and (doc := facts.get(trig)) and doc.get("days") is not None:
        ctr = next(
            (k for k, v in facts.items() if k.startswith("ctr:") and "#" not in k and v.get("supplier") == supplier_id),
            None,
        )
        if ctr and facts[ctr].get("days") and doc["days"] < facts[ctr]["days"]:
            d.claims.append(
                Claim(
                    "notice",
                    [trig, ctr],
                    f"Your letter {trig} gives {doc['days']} days of notice, while our contract {ctr} "
                    f"requires {facts[ctr]['days']} days.",
                    1.3,
                    doc["days"],
                )
            )

    # scorecard: latest quarter
    scs = sorted(k for k in facts if k.startswith(f"sc:{supplier_id.split(':')[1]}@"))
    if scs:
        sc = facts[scs[-1]]
        goal = b.get("category_goal")
        if goal == "quality_first" and sc.get("ppm", 0) > 300:
            d.claims.append(Claim("quality", [scs[-1]], f"Your rolling defect rate is {sc['ppm']} ppm ({scs[-1]}).", 0.9, sc["ppm"]))
        elif sc.get("otd_pct", 100) < 92:
            d.claims.append(
                Claim("delivery", [scs[-1]], f"Your on-time delivery was {sc['otd_pct']}% ({scs[-1]}).", 0.7, sc["otd_pct"])
            )

    # quotes this case points to (refs or the alternative): price comparison
    alt = b.get("alternative") or {}
    quote_refs = [r for r in case.get("refs", []) if r.startswith("quote:")] + ([alt["ref"]] if alt.get("ref") else [])
    for q in dict.fromkeys(quote_refs):
        f = facts.get(q)
        if f and f.get("supplier") != supplier_id and asked_price and f.get("unit_price", 1e9) < asked_price:
            d.claims.append(Claim("quote", [q], f"We hold a quote at EUR {f['unit_price']:.2f} per unit ({q}).", 1.4, f["unit_price"]))

    # an index that fell from its 12-month peak: the cost driver is easing now (P18: AS-14404 -5.5 %)
    for s, w in series.items():
        drop = index_peak_drop(facts, s)
        if drop and drop[2] <= -2.0:
            e, l_, pct = drop
            d.claims.append(Claim("index_peak", [e, l_],
                                  f"The index {s} moved {pct:+.1f}% from its recent peak ({e} to {l_}).",
                                  1.1 + 0.5 * (w or 0.3), pct))

    # order history (2-8 PO lines of the part are checked by their order prices). Another supplier's
    # orders are NOT used: the arena rated them irrelevant for this supplier (P18).
    if asked_price:
        pos = sorted(
            ((k, v) for k, v in facts.items()
             if k.startswith("po:") and v.get("part") == part and v.get("unit_price") and v.get("date")),
            key=lambda kv: (kv[1]["date"], kv[0]),
        )
        horizon = _months_back(pos[-1][1]["date"][:7], 12) if pos else None
        mine = [(k, v) for k, v in pos if v.get("supplier") == supplier_id and v["date"][:7] >= horizon]
        if mine:
            last_id, last = mine[-1]
            before = [(k, v) for k, v in mine if v["unit_price"] < last["unit_price"] * 0.97]
            d.reference_prices["current_orders"] = last["unit_price"]
            if before and asked_price > last["unit_price"]:
                b_id, b = before[-1]
                d.reference_prices["before_raise"] = b["unit_price"]
                d.claims.append(Claim(
                    "price_already_raised", [b_id, last_id],
                    f"Our orders show your price already rose this year from EUR {b['unit_price']:.2f} ({b_id}) "
                    f"to EUR {last['unit_price']:.2f} ({last_id}).",
                    1.25, last["unit_price"]))
    # share of our business: a supplier that serves only part of a split-sourced part wants more of it
    # (P18: 20 % of the case part, 60 % of another bar; "focus on customers with volume", "our whole
    # range is at your disposal"). Part IDs are context, not checked claims; nothing here binds.
    split = _query(
        package,
        "SELECT s.part_id, p.description, s.quota_pct FROM sourcing s JOIN parts p ON p.id = s.part_id "
        "WHERE s.supplier_id = ? AND s.status = 'active' AND s.quota_pct < 100 ORDER BY s.quota_pct",
        (supplier_id,),
    )
    if split:
        names = ", ".join(f"{r['description']} ({r['part_id']})" for r in split[:2])
        d.claims.append(Claim(
            "share_of_business", [],
            f"Today you supply only part of our need for {names}; a competitive base price here would put "
            "you first in line for a larger share of that business.",
            1.15, None))

    # what the notes say (context, not checked)
    docs = _query(package, "SELECT id, kind, file FROM documents WHERE supplier_id = ? ORDER BY date", (supplier_id,))
    cash_denied = capacity_denied = False
    for row in docs[-12:]:
        try:
            text = package.document(row["id"])
        except Exception:
            continue
        body = text.split("\n", 4)[-1].strip()
        d.notes.append(f"{row['id']} ({row['kind']}): {body[:1600]}")
        signals = supplier_signals_from_note(body)
        cash_denied |= bool(CASH_DENIAL.search(body))
        capacity_denied |= bool(CAPACITY_DENIAL.search(body))
        d.cash_short |= signals["cash_short"]
        d.spare_capacity |= signals["spare_capacity"]
        d.stale_costing |= bool(STALE_COSTING.search(body))
        d.approval_ladder |= bool(APPROVAL.search(body))
        d.wants_partnership |= bool(PARTNER.search(body))
    # A later contradictory note makes spare capacity unknown, not available.
    # Financial metrics below can independently justify cash pressure.
    if cash_denied:
        d.cash_short = False
    if capacity_denied:
        d.spare_capacity = False
    intel = _query(package, "SELECT equity_ratio_pct, credit_index, credit_index_12m_ago FROM supplier_intel WHERE supplier_id = ?", (supplier_id,))
    if intel:
        i = intel[0]
        if (i.get("equity_ratio_pct") or 100) < 15 or (i.get("credit_index") or 0) - (i.get("credit_index_12m_ago") or 0) > 15:
            d.cash_short = True
    d.claims.sort(key=lambda c: -c.strength)
    return d


def estimate(case, dossier, standard, asked_price, params):
    """Our estimate of the supplier for supplier_value / relationship cost."""
    full = dossier.full_cost
    if not full and asked_price:
        full = asked_price / (1 + params.open_margin)
    return {
        "standard": standard,
        "full_cost": full or 0.0,
        "interest_rate": 0.18 if dossier.cash_short else 0.08,
        "usual_rate": 0.08,
    }
