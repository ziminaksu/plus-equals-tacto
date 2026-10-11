"""Free transport, budget and received-state regressions. No Arena simulation."""
import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from hollerau.analytical.director import execute, normalize_selection, validate_selection
from hollerau.analytical.lean_decision import lean_board
from hollerau.analytical.router import Router
from hollerau.analytical.spending import SpendLedger, SpendLimitReached
from tests.test_astra_authority import board_for, setup


def choose(board, aid, packages=()):
    action = board['actions'][aid]
    closing = action['kind'] in ('accept', 'walk_away')
    return {'action_id': aid, 'package_ids': list(packages), 'question_id': '', 'evidence_ids': [],
            'tone': 'cooperative', 'rationale': 'Compare complete costs and the live offer.',
            'reply_text': '' if closing else 'Please consider the attached alternatives.',
            'continuation_review': {'target_package_id': next(iter(packages), ''),
                                    'walkout_probability_low': 0.1, 'walkout_probability_high': 0.3,
                                    'risk_reason': 'A further concession is uncertain.',
                                    'information_needed': '', 'stop_condition': 'Close on a final offer.'},
            'plan': {'expected_response': 'closed' if closing else 'counteroffer',
                     'expected_price_low': None, 'expected_price_high': None, 'basis_source_ids': [],
                     'basis': 'Assumption: a reciprocal trade may improve the offer.',
                     'if_counteroffer': 'Compare total cost.', 'if_unchanged': 'Close on a final offer.',
                     'if_accepted': 'Confirm the complete terms.', 'if_walkout': 'Use live alternatives only.',
                     'rejected_alternative_id': '', 'why_not_alternative': 'A better trade is still plausible.',
                     'revision_from_previous': 'Use the latest supplier response.'}}


def payload(model='gpt-6-astra'):
    return {'model': model, 'input': 'hi', 'service_tier': 'default', 'max_output_tokens': 2048}


def test_shared_atomic_limit_and_restart(tmp_path):
    path = tmp_path / 'spend.sqlite'
    ledger = SpendLedger(path, 0.2)
    def reserve(_):
        try:
            return SpendLedger(path, 0.2).reserve(payload())
        except SpendLimitReached:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len([x for x in pool.map(reserve, range(2)) if x]) == 1
    assert ledger.snapshot()['accounted_usd'] <= 0.2
    assert SpendLedger(path, 0.2).snapshot() == ledger.snapshot()
    with pytest.raises(ValueError, match='cannot change'):
        SpendLedger(path, 1)


def test_unknown_usage_keeps_reservation_known_usage_reconciles(tmp_path):
    ledger = SpendLedger(tmp_path / 'spend.sqlite', 1)
    first = ledger.reserve(payload())
    reserved = ledger.snapshot()['accounted_usd']
    ledger.settle(first, {})
    assert ledger.snapshot()['unknown_outcome_reserve_usd'] == reserved
    second = ledger.reserve(payload())
    ledger.settle(second, {'input_tokens': 1000, 'output_tokens': 500})
    assert ledger.snapshot()['accounted_usd'] == pytest.approx(reserved + 0.0375)
    assert ledger.snapshot()['unknown_outcome_reserve_usd'] == reserved


def budget_router(monkeypatch, tmp_path, transport, cap=1):
    monkeypatch.delenv('ASTRA_BASE_URL', raising=False)
    monkeypatch.setenv('LLM_SPEND_LEDGER', str(tmp_path / 'spend.sqlite'))
    monkeypatch.setenv('LLM_MAX_SPEND_USD', str(cap))
    return Router(primary='astra', reviewer='astra', review_key='test', transport=transport)


def test_no_dispatch_without_money(monkeypatch, tmp_path):
    router = budget_router(monkeypatch, tmp_path,
                           httpx.MockTransport(lambda r: pytest.fail('must not dispatch')), 0.001)
    with pytest.raises(SpendLimitReached):
        router.call_astra('', {}, time.monotonic() + 10, role='final_decision')


def test_timeout_is_accounted_and_no_retry(monkeypatch, tmp_path):
    calls = []
    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout('test')
    router = budget_router(monkeypatch, tmp_path, httpx.MockTransport(timeout))
    with pytest.raises(httpx.ReadTimeout):
        router.call_astra('', {}, time.monotonic() + 10, role='final_decision')
    assert len(calls) == 1
    assert router.spend.snapshot()['unknown_outcome_reserve_usd'] > 0


def test_usage_is_accounted_even_for_truncated_output(monkeypatch, tmp_path):
    def truncated(request):
        assert json.loads(request.content)['service_tier'] == 'default'
        return httpx.Response(200, json={'status': 'incomplete',
                                        'usage': {'input_tokens': 1000, 'output_tokens': 2048}})
    router = budget_router(monkeypatch, tmp_path, httpx.MockTransport(truncated))
    with pytest.raises(ValueError, match='incomplete'):
        router.call_astra('', {}, time.monotonic() + 10, role='final_decision')
    assert router.spend.snapshot()['accounted_usd'] == 0.1149
    assert router.spend.snapshot()['unknown_outcome_reserve_usd'] == 0


def test_definitive_credit_rejection_blocks_calls_without_claiming_a_charge(monkeypatch, tmp_path):
    calls = []
    def reject(request):
        calls.append(request)
        return httpx.Response(429, json={'error': {'code': 'credit_balance_exhausted',
                                                  'type': 'insufficient_quota'}})
    router = budget_router(monkeypatch, tmp_path, httpx.MockTransport(reject))
    for _ in range(2):
        with pytest.raises(SpendLimitReached):
            router.check_budget_connection()
    assert len(calls) == 1
    assert router.spend.snapshot()['accounted_usd'] == 0
    assert router.spend.snapshot()['blocked']


def test_billing_preflight_fails_before_arena_client_is_created(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from hollerau.analytical import cli
    monkeypatch.delenv('ASTRA_BASE_URL', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'test')
    monkeypatch.setattr(cli, 'load_env', lambda: None)
    monkeypatch.setattr(cli, 'DataPackage', lambda *a: SimpleNamespace(lookup=lambda *a: None))
    monkeypatch.setattr(cli, 'fingerprint', lambda *a: {})
    monkeypatch.setattr(cli, 'ArenaClient', lambda **kw: pytest.fail('must not open Arena'))
    transport = httpx.MockTransport(lambda r: httpx.Response(
        429, json={'error': {'code': 'credit_balance_exhausted'}}))
    monkeypatch.setattr(cli, 'Router', lambda **kw: Router(transport=transport, **kw))
    with pytest.raises(SystemExit) as exc:
        cli.main(['--cases', 'case:P18', '--max-sessions', '1', '--run-id', 'budget-test',
                  '--db', str(tmp_path / 'events.sqlite'), '--max-spend-usd', '1',
                  '--spend-ledger', str(tmp_path / 'spend.sqlite')])
    assert exc.value.code == 2


def test_budget_exhaustion_closes_instead_of_launching_unpaid_bargaining(monkeypatch, tmp_path):
    agent, case, threads, sid = setup(reply=False)
    agent.router.spend = SpendLedger(tmp_path / 'spend.sqlite', 0.001)
    def no_budget(*args):
        raise SpendLimitReached('no money')
    monkeypatch.setattr(agent.router, 'final_decision', no_budget)
    monkeypatch.setattr(agent, 'offline_move', lambda *a: pytest.fail('must close, not counter'))
    decision = agent.decide(case, threads)
    assert decision['message']['action']['type'] in ('accept', 'walk_away')
    row = agent.store.db.execute("SELECT payload FROM events WHERE kind='decision'").fetchone()
    assert json.loads(row[0])['authority'] == 'budget_close'


def test_lean_context_keeps_all_selectable_terms_costs_and_current_evidence():
    agent, case, threads, sid = setup('case:P02', reply=False)
    board = board_for(agent, case, threads)
    original = copy.deepcopy(board)
    small = lean_board(board)
    assert board == original
    assert small['actions'] == board['actions']
    assert small['evidence'] == board['evidence']
    assert small['suppliers'][sid]['sources'] == board['suppliers'][sid]['sources']
    for action in board['actions'].values():
        for pid in action.get('package_ids', []) + ([action['package_id']] if action.get('package_id') else []):
            assert small['packages'][pid]['terms'] == board['packages'][pid]['terms']
            assert small['packages'][pid]['expected_total_eur'] == board['packages'][pid]['expected_total_eur']
    assert len(json.dumps(small)) < len(json.dumps(board)) * 0.5


def test_selected_offers_are_not_filtered_by_direct_cost():
    agent, case, threads, sid = setup('case:P02', reply=False)
    board = board_for(agent, case, threads)
    ids = board['actions'][f'{sid}:counter']['package_ids'][:2]
    assert len(ids) == 2
    # A relationship-aware alternative can have a higher direct cost. Neither
    # the renderer nor normalizer is allowed to change the model's selection.
    board['packages'][ids[0]]['direct_cost_eur'] = 100
    board['packages'][ids[1]]['direct_cost_eur'] = 200
    sel = choose(board, f'{sid}:counter', ids)
    sent = execute(agent, case, threads, board, sel)['message']['term_sheets']
    assert sent == [{'terms': board['packages'][p]['terms']} for p in ids]


def test_invalid_counter_is_corrected_not_silently_pruned():
    agent, case, threads, sid = setup(reply=False)
    board = board_for(agent, case, threads)
    pid = board['actions'][f'{sid}:counter']['package_ids'][0]
    sel = normalize_selection(board, choose(board, f'{sid}:counter', [pid, 'other-supplier:package']))
    assert sel['package_ids'] == [pid, 'other-supplier:package']
    with pytest.raises(ValueError, match='validated packages'):
        validate_selection(board, sel)


def test_repeated_ask_id_preserves_strategy_without_paid_correction(monkeypatch, tmp_path):
    agent, case, threads, sid = setup('case:P18', reply=False)
    board = board_for(agent, case, threads)
    aid = f'{sid}:index_rebase'
    sel = choose(board, aid)
    sel['question_id'] = board['actions'][aid]['question_id']
    sel['reply_text'] = 'Please clarify the pricing for the index alternative.'
    sel['continuation_review']['information_needed'] = 'Compare the complete indexed and fixed-price terms.'
    original = copy.deepcopy(sel)
    agent.router.spend = SpendLedger(tmp_path / 'spend.sqlite', 1)
    calls = []
    def respond(*args, **kwargs):
        calls.append(args)
        assert len(calls) == 1, 'a redundant identical ID must not need a paid repair'
        agent.router.calls.append({})
        return copy.deepcopy(sel)
    monkeypatch.setattr(agent.router, 'call_astra', respond)
    chosen = agent.router.final_decision(board, time.monotonic() + 50)
    assert chosen == original
    decision = execute(agent, case, threads, board, chosen)
    assert decision['message']['term_sheets'] == []
    assert decision['message']['body'] == original['reply_text']
    assert agent.threads[sid].pending['request'] == board['questions'][sel['question_id']]
    # Even another valid question for this supplier must not change the ask.
    sel['question_id'] = f'{sid}:payment_quotes'
    with pytest.raises(ValueError, match='question belongs'):
        validate_selection(board, sel)


def test_one_final_call_preserves_audit_and_skips_proposer(monkeypatch, tmp_path):
    agent, case, threads, sid = setup(reply=False)
    agent.router.spend = SpendLedger(tmp_path / 'spend.sqlite', 1)
    monkeypatch.setattr(agent, 'interpret', lambda *a: pytest.fail('duplicate proposer'))
    calls = []
    def final(board, deadline):
        calls.append(board)
        pid = board['actions'][f'{sid}:counter']['package_ids'][0]
        return choose(board, f'{sid}:counter', [pid])
    monkeypatch.setattr(agent.router, 'final_decision', final)
    decision = agent.decide(case, threads)
    assert len(calls) == 1
    assert decision['message']['term_sheets']
    assert agent.store.db.execute("SELECT COUNT(*) FROM events WHERE kind='decision_record'").fetchone()[0] == 1
