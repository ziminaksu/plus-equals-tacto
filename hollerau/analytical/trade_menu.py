"""Small, optional non-price exchanges beside the existing price schedule."""


def trade_candidates(packages, supplier_id, last_terms, ceiling, limit=2):
    """Retain one-field payment/commitment exchanges within the scheduled buyer cost.

    Direction suggests a supplier benefit; it is not a calibrated acceptance prediction.
    All packages have already passed the normal complete-offer validation.
    """
    eligible = []
    for pid, row in packages.items():
        if row['supplier_id'] != supplier_id:
            continue
        terms = row['terms']
        changed = {key for key in terms.keys() | last_terms.keys() if terms.get(key) != last_terms.get(key)}
        if changed not in ({'payment_days'}, {'contract_months'}):
            continue
        field = next(iter(changed))
        old, new = last_terms.get(field), terms.get(field)
        if not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
            continue
        beneficial = new < old if field == 'payment_days' else new > old
        cost = row.get('expected_total_eur')
        if beneficial and isinstance(cost, (int, float)) and cost <= ceiling:
            eligible.append((cost, pid, field))
    # Keep different levers; don't fill the menu with payment-day variants alone.
    chosen, fields = [], set()
    for _, pid, field in sorted(eligible):
        if field not in fields:
            chosen.append(pid)
            fields.add(field)
        if len(chosen) >= limit:
            break
    return chosen
