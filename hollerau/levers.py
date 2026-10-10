"""Term-sheet packages and prices: every number the strategy needs, from the published cost function.

A package is a value for every negotiable field except the price. For a package we solve:
  price_for_cost   the unit price that makes C (buyer cost) hit a target
  floor_price      the unit price at which a supplier's margin on cash (supplier_value) hits a level
"""

import itertools
import math

from arena_kit.cost import complete_offer, must_haves_ok, supplier_value, total_cost

MAX_PACKAGES = 600


def lever_fields(case):
    return [f for f in case["negotiable"] if f != "unit_price"]


def field_options(case, field, standard):
    opts = list(case.get("term_options", {}).get(field) or [])
    if standard.get(field) is not None and standard[field] not in opts:
        opts.append(standard[field])  # the supplier's standard value is always allowed
    return opts or [complete_offer(case, {}).get(field)]


def packages(case, standard):
    """Every combination of allowed lever values (capped), each a dict without unit_price."""
    names = lever_fields(case)
    combos = itertools.product(*(field_options(case, f, standard) for f in names))
    return [dict(zip(names, c, strict=True)) for c in itertools.islice(combos, MAX_PACKAGES)]


def sheet(case, package, price):
    return complete_offer(case, {**package, "unit_price": round(max(price, 0.01), 2)})


def cost(case, package, price, standard, supplier=None):
    return total_cost(case, {**package, "unit_price": price}, standard, supplier)


def price_for_cost(case, package, target, standard, supplier=None, lo=0.01, hi=None):
    """The highest unit price whose C stays at or below `target`. C rises with the price except
    where the relationship term (supplier margin below sustainable) falls faster: C is convex in
    the price there, so find its minimum first and search above it."""
    hi = hi or 10 * (case["buyer"].get("current_unit_price") or case["buyer"]["fallback_unit_price"])
    if supplier is not None and case["buyer"].get("relationship_eur_per_point"):
        a, b = lo, hi
        for _ in range(60):  # golden-section search for the price with the lowest C
            m1, m2 = a + (b - a) * 0.382, a + (b - a) * 0.618
            if cost(case, package, m1, standard, supplier) <= cost(case, package, m2, standard, supplier):
                b = m2
            else:
                a = m1
        lo = (a + b) / 2
    if cost(case, package, lo, standard, supplier) > target:
        return None
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cost(case, package, mid, standard, supplier) <= target else (lo, mid)
    return math.floor(lo * 100) / 100


def floor_price(case, package, supplier, margin):
    """The unit price at which the supplier's margin on cash is exactly `margin` (a fraction).
    supplier_value is linear in the price, so two points give it."""
    v0 = supplier_value(case, {**package, "unit_price": 0.0}, supplier)
    v1 = supplier_value(case, {**package, "unit_price": 1.0}, supplier)
    need = supplier["full_cost"] / (1 - margin)
    return (need - v0) / (v1 - v0) if v1 != v0 else math.inf


def margin_of(case, terms, supplier):
    v = supplier_value(case, terms, supplier)
    return (v - supplier["full_cost"]) / v if v > 0 else -math.inf


def valid(case, package, price, standard):
    return must_haves_ok(case, {**package, "unit_price": price}, standard)


def best_deal(case, standard, supplier, margin, price_cap=None, grid=24):
    """The cheapest (C, package, price) a supplier with this estimate would accept: price at or
    above its floor, every valid lever; with a relationship term C may be lowest above the floor."""
    best = (math.inf, None, None)
    for pkg in packages(case, standard):
        p0 = floor_price(case, pkg, supplier, margin)
        if not math.isfinite(p0) or p0 <= 0:
            continue
        p1 = max(p0, price_cap or p0)
        for i in range(grid + 1 if p1 > p0 else 1):
            p = round(p0 + (p1 - p0) * i / grid, 2) + 0.0
            p = math.ceil(p0 * 100) / 100 if i == 0 else p
            if not valid(case, pkg, p, standard):
                break
            c = cost(case, pkg, p, standard, supplier)
            if c < best[0]:
                best = (c, pkg, p)
    return best
