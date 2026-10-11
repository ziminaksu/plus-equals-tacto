"""Received-state/transport regressions; no paid model calls or Arena sessions."""
import asyncio
import copy
import time
from types import SimpleNamespace

import httpx
import pytest

from arena_kit.client import ArenaClient
from arena_kit.play import RemoteTable, latest, live_threads, standing
from hollerau.analytical.cli import LoggedTable, SafeRemoteTable
from hollerau.analytical.director import compact_board, execute, validate_selection
from hollerau.analytical.lean_decision import lean_board
from hollerau.analytical.storage import Store
from tests.test_astra_authority import board_for, selection, setup


def test_concurrent_refresh_cancels_slow_reads_and_invalidates_changed_offers():
    cancelled, paths = [], []
    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                while True:
                    await asyncio.sleep(0.005)
                    yield b' '
            finally:
                cancelled.append(True)
    async def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/sessions/s'):
            return httpx.Response(200, json={'status': 'open', 'threads': {
                sid: {'offer_id': f'{sid}:new', 'closed': None} for sid in ('a', 'b')}})
        return httpx.Response(200, stream=Slow())
    client = ArenaClient('https://arena.example', 'test', transport=httpx.MockTransport(handle), rate=10000)
    table = RemoteTable(client)
    table.session_id = 's'
    threads = {sid: [{'from': 'supplier', 'status': 'open', 'term_sheets': [
        {'term_sheet_id': f'{sid}:old', 'terms': {'unit_price': 10}}]}] for sid in ('a', 'b')}
    started = time.monotonic()
    table.refresh(threads, deadline=started + 0.10)
    assert time.monotonic() - started < 0.5
    assert len(cancelled) == 2
    assert len(paths) == 3  # one session read plus both parallel threads, no retries
    assert all(standing(t) == (None, {}) and latest(t)['state_uncertain'] for t in threads.values())
    client.http.close()


def test_rate_limit_wait_is_inside_refresh_deadline():
    client = ArenaClient('https://arena.example', transport=httpx.MockTransport(
        lambda r: pytest.fail('must not dispatch after the read budget')), rate=1)
    client._next = time.monotonic() + 5
    with pytest.raises(httpx.ReadTimeout, match='rate limit'):
        client.session('s', deadline=time.monotonic() + 0.02)
    client.http.close()


def test_final_runner_refresh_uses_bounded_reads_without_an_agent_attribute():
    def handle(request):
        return httpx.Response(200, json={'status': 'open', 'threads': {
            'a': {'offer_id': None, 'closed': 'walked_away'}}})
    client = ArenaClient('https://arena.example', transport=httpx.MockTransport(handle), rate=10000)
    table = SafeRemoteTable(client)
    table.session_id = 's'
    threads = {'a': [{'from': 'supplier', 'status': 'open', 'term_sheets': []}]}
    table.refresh(threads)
    assert not live_threads(threads)
    client.http.close()


def test_early_confirmation_compares_a_real_option_but_does_not_force_continuation():
    agent, case, threads, sid = setup()
    board = board_for(agent, case, threads)
    aid = next(k for k, a in board['actions'].items() if a['kind'] == 'confirm')
    choice = selection(aid)
    with pytest.raises(ValueError, match='must compare'):
        validate_selection(board, choice)
    context = board['suppliers'][sid]['continuation_comparison']
    choice['plan']['rejected_alternative_id'] = context['available_comparison_ids'][0]
    assert validate_selection(board, choice)['kind'] == 'confirm'
    for compact in (lean_board(board), compact_board(board)):
        review = compact['suppliers'][sid]['continuation_comparison']
        assert all(k in compact['actions'] or k in compact['packages']
                   for k in review['available_comparison_ids'])
        assert compact['exit_context']['walk_away_ends_entire_case']
    message = execute(agent, case, threads, board, choice)['message']
    assert 'not an acceptance or purchase order' in message['body']
    assert not message.get('action')


def test_failed_render_rolls_back_learning_and_evidence(monkeypatch):
    import hollerau.analytical.director as module
    agent, case, threads, sid = setup(reply=False)
    board = board_for(agent, case, threads)
    pid = board['actions'][f'{sid}:counter']['package_ids'][0]
    choice = selection(f'{sid}:counter', [pid])
    th = agent.threads[sid]
    before = {k: copy.deepcopy(getattr(th, k)) for k in ('used', 'last_terms', 'pending', 'asked_quotes')}
    monkeypatch.setattr(module.compliance, 'problems', lambda *a, **k: ['rejected'])
    with pytest.raises(ValueError, match='violates constraints'):
        execute(agent, case, threads, board, choice)
    assert {k: getattr(th, k) for k in before} == before
    assert agent.store.db.execute("SELECT COUNT(*) FROM events WHERE kind='decision'").fetchone()[0] == 0


def test_unconfirmed_send_is_not_recorded_as_sent():
    def fail(*args):
        raise httpx.ReadTimeout('unknown outcome')
    store = Store(':memory:')
    table = LoggedTable(SimpleNamespace(send_message=fail), store, 'r', SimpleNamespace(threads={}))
    table.case_id, table.session_id = 'case:P18', 's'
    with pytest.raises(httpx.ReadTimeout):
        table.send('a', {'body': 'a request'})
    kinds = [r[0] for r in store.db.execute('SELECT kind FROM events')]
    assert kinds == ['send_attempt', 'send_unconfirmed']
    store.close()


def test_model_evidence_limit_matches_rendering_and_schema():
    from hollerau.analytical.contracts import final_schema
    agent, case, threads, sid = setup(reply=False)
    board = board_for(agent, case, threads)
    pid = board['actions'][f'{sid}:counter']['package_ids'][0]
    assert final_schema(board)['properties']['evidence_ids']['maxItems'] == 2
    board['evidence'] = {f'{sid}:e{i}': {'supplier_id': sid, 'kind': 'verified_test', 'refs': [],
                                      'text': text} for i, text in enumerate((
        'Our order history supports a review.', 'Our forecast supports a planned commitment.',
        'Delivery performance supports this request.'))}
    choice = selection(f'{sid}:counter', [pid], evidence=list(board['evidence']))
    assert len(choice['evidence_ids']) == 3
    with pytest.raises(ValueError, match='invalid evidence selection'):
        validate_selection(board, choice)


@pytest.mark.parametrize('include_sheet', [False, True])
def test_refresh_never_keeps_old_terms_when_new_quote_has_no_timeout(include_sheet):
    old = {'from': 'supplier', 'status': 'open', 'term_sheets': [
        {'term_sheet_id': 'old', 'terms': {'unit_price': 10}}]}
    current = {'from': 'supplier', 'status': 'open', 'body': 'Revised quotation', 'term_sheets': [
        {'term_sheet_id': 'new', 'terms': {'unit_price': 11}}]}
    def handle(request):
        if request.url.path.endswith('/sessions/s'):
            return httpx.Response(200, json={'status': 'open', 'threads': {'a': {'offer_id': 'new'}}})
        return httpx.Response(200, json={'offer_id': 'new', 'status': 'open', 'closed': None,
                                        'messages': [current] if include_sheet else [], 'timeouts': []})
    client = ArenaClient('https://arena.example', transport=httpx.MockTransport(handle), rate=10000)
    table = RemoteTable(client)
    table.session_id = 's'
    threads = {'a': [old]}
    table.refresh(threads)
    assert standing(threads['a']) == (('new', {'unit_price': 11}) if include_sheet else (None, {}))
    assert table.refresh(threads) == []
    client.http.close()


@pytest.mark.parametrize('new_price', [10, 11])
def test_accept_retry_requires_identical_terms_and_shares_a_read_deadline(new_price):
    from arena_kit.client import ArenaError
    from hollerau.analytical.cli import reissued_accept
    deadlines = []
    def session(sid, *, deadline):
        deadlines.append(deadline)
        return {'status': 'open', 'threads': {'a': {'offer_id': 'new', 'closed': None}}}
    def thread(sid, supplier, *, deadline):
        deadlines.append(deadline)
        return {'timeouts': [{'offer_id': 'new', 'terms': {'unit_price': new_price}}]}
    retry = reissued_accept(SimpleNamespace(session=session, thread=thread), 's', 'a',
                            {'action': {'type': 'accept', 'term_sheet_id': 'old'}},
                            ArenaError(422, 'accept requires the standing offer'),
                            {'old': {'unit_price': 10}})
    assert deadlines[0] == deadlines[1]
    assert 0 < deadlines[0] - time.monotonic() <= 6
    assert retry == ({'action': {'type': 'accept', 'term_sheet_id': 'new'}} if new_price == 10 else None)


def test_unconfirmed_closure_is_not_recorded_as_sent_or_result():
    def fail(*args):
        raise httpx.ReadTimeout('unknown outcome')
    store = Store(':memory:')
    table = LoggedTable(SimpleNamespace(send_message=fail), store, 'r', SimpleNamespace(threads={}))
    table.case_id, table.session_id = 'case:P18', 's'
    with pytest.raises(httpx.ReadTimeout):
        table.close('a', {'action': {'type': 'walk_away'}})
    assert [r[0] for r in store.db.execute('SELECT kind FROM events')] == ['send_attempt', 'send_unconfirmed']
    store.close()


def test_known_indicative_sheet_becoming_standing_still_refreshes():
    current = {'from': 'supplier', 'status': 'open', 'term_sheets': [
        {'term_sheet_id': 'alternative', 'terms': {'unit_price': 9}}]}
    reads = []
    def session(sid, *, deadline):
        return {'status': 'open', 'threads': {'a': {'offer_id': 'alternative'}}}
    def thread(sid, supplier, *, deadline):
        reads.append(supplier)
        return {'offer_id': 'alternative', 'messages': [current]}
    table = RemoteTable(SimpleNamespace(session=session, thread=thread))
    table.session_id = 's'
    threads = {'a': [{'from': 'supplier', 'status': 'open', 'term_sheets': [
        {'term_sheet_id': 'old', 'terms': {'unit_price': 10}}, *current['term_sheets']]}]}
    table.refresh(threads)
    assert reads == ['a']
    assert standing(threads['a']) == ('alternative', {'unit_price': 9})


@pytest.mark.parametrize('model,cap_key,cap', [('gpt-5-mini', 'max_completion_tokens', 8192),
                                             ('test-chat', 'max_tokens', 4096)])
def test_call_record_matches_actual_provider_token_settings(model, cap_key, cap):
    import json

    from hollerau.analytical.router import Router
    bodies = []
    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]})
    router = Router('test', transport=httpx.MockTransport(handle), review_key='private-test')
    router._chat_once('https://provider.example', model, '', {}, 1, 'final_decision', None)
    settings = router.calls[-1]['request_settings']
    assert settings[cap_key] == cap
    assert all(bodies[0][k] == v for k, v in settings.items())
    assert 'private-test' not in json.dumps(router.calls)
    router.close()


def test_missed_move_does_not_pair_new_id_with_previous_timeout_terms():
    from arena_kit.client import ArenaError
    def session(sid, *, deadline):
        return {'status': 'open'}
    def thread(sid, supplier, *, deadline):
        return {'offer_id': 'new', 'status': 'open', 'closed': None,
                'timeouts': [{'offer_id': 'old', 'terms': {'unit_price': 10}}]}
    table = RemoteTable(SimpleNamespace(session=session, thread=thread))
    table.session_id = 's'
    result = table.missed('a', ArenaError(409, 'move expired'))
    assert result['term_sheets'] == [] and result['state_uncertain']


def test_new_ksu_contract_priority_preserves_both_approved_claims():
    agent, case, threads, sid = setup(reply=False)
    board = board_for(agent, case, threads)
    board['evidence'] = {
        'volume': {'supplier_id': sid, 'kind': 'forecast', 'refs': [], 'text': 'Forecast argument.'},
        'contract': {'supplier_id': sid, 'kind': 'contract_index', 'refs': [], 'text': 'Contract argument.'}}
    pid = board['actions'][f'{sid}:counter']['package_ids'][0]
    choice = selection(f'{sid}:counter', [pid], evidence=['volume', 'contract'])
    message = execute(agent, case, threads, board, choice)['message']
    assert message['body'].index('Contract argument.') < message['body'].index('Forecast argument.')
    assert message['term_sheets'][0]['terms'] == board['packages'][pid]['terms']


def test_new_ksu_contract_and_note_claims_keep_their_source_ids():
    from hollerau.intel import build
    notes = {'doc:calculation': 'The owner offered to walk through our calculation of hourly rates and material.',
             'doc:volume': 'Our sales director says we focus on customers with volume.',
             'doc:committee': 'The key account manager explained that larger changes need the pricing committee.'}
    facts = {k: {} for k in notes}
    facts['ctr:example#3.2'] = {'supplier': 'sup:test', 'type': 'index', 'series': 'PPI-EXAMPLE', 'material_share': 0.8}
    def query(sql, params):
        return ([{'id': k, 'date': '2026-10-10', 'kind': 'meeting_note'} for k in notes]
                if 'FROM documents' in sql else [])
    package = SimpleNamespace(facts=facts, db=True, query=query, document=lambda k: notes[k])
    dossier = build({'buyer': {}}, 'sup:test', package)
    claims = {c.kind: c for c in dossier.claims}
    assert claims['contract_index'].refs == ['ctr:example#3.2']
    assert claims['calculation_offer'].refs == ['doc:calculation']
    assert claims['volume_focus'].refs == ['doc:volume']
    assert claims['approval_threshold'].refs == ['doc:committee']
    assert 'multi-year commitment' not in claims['approval_threshold'].sentence


@pytest.mark.parametrize('outside,expected', [(0, {'accept', 'walk_away'}), (1e12, {'accept'})])
def test_two_agreements_override_concession_rule_and_preserve_outside_option(monkeypatch, outside, expected):
    agent, case, threads, sid = setup(reply=False)
    quote = copy.deepcopy(threads[sid][0])
    for i, status in enumerate(('agreed', 'open', 'agreed', 'open')):
        reply = copy.deepcopy(quote)
        reply['status'] = status
        reply['term_sheets'][0]['term_sheet_id'] = f'current:{i}'
        reply['term_sheets'][0]['terms']['unit_price'] *= 1.06 - i * 0.02
        threads[sid].extend([{'from': 'buyer', 'body': 'Please review the complete package.'}, reply])
    monkeypatch.setattr(agent, 'alternatives', lambda case: outside)
    board = board_for(agent, case, threads)
    assert {a['kind'] for a in board['actions'].values()} == expected
    assert not board['suppliers'][sid]['continuation_comparison']['review_before_early_close']
