from hollerau.analytical.trade_menu import trade_candidates


def test_trade_menu_preserves_price_and_chooses_distinct_affordable_levers():
    last = {'unit_price': 10, 'payment_days': 90, 'contract_months': 12}
    def row(cost, **changes):
        return {'supplier_id': 's', 'terms': {**last, **changes}, 'expected_total_eur': cost}
    packages = {
        'payment': row(103, payment_days=60),
        'too_costly': row(120, payment_days=30),
        'contract': row(100, contract_months=24),
        'unilateral': row(99, payment_days=120),
        'price_change': row(100, unit_price=11, contract_months=36),
        'other_supplier': {**row(90, contract_months=24), 'supplier_id': 'other'},
    }
    assert trade_candidates(packages, 's', last, 105) == ['contract', 'payment']
    assert trade_candidates(packages, 's', last, 99) == []
