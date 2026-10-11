"""Transport/expiry regressions only: no Arena sessions or paid model calls."""
import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest

from hollerau.analytical.agent import AnalyticalAgent
from hollerau.analytical.director import FinalDecisionUnavailable
from hollerau.analytical.http_deadline import bounded_post
from hollerau.analytical.router import Router


def test_total_deadline_cancels_trickling_response():
    closed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                while True:
                    await asyncio.sleep(0.005)
                    yield b' '
            finally:
                closed.append(True)

    async def handler(request):
        return httpx.Response(200, stream=Stream())

    start = time.monotonic()
    with pytest.raises(httpx.ReadTimeout):
        bounded_post('https://example.test', deadline=start + 0.05,
                     transport=httpx.MockTransport(handler), json={})
    assert time.monotonic() - start < 0.5
    assert closed


@pytest.mark.parametrize('error,expected_calls', [('bad model', 1), ('json_schema unsupported', 2)])
def test_schema_retry_only_for_format_error(error, expected_calls):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(400, json={'error': error})
        return httpx.Response(200, json={'choices': [
            {'finish_reason': 'stop', 'message': {'content': '{}'}}]})

    router = Router(transport=httpx.MockTransport(handler), review_key='test')
    if expected_calls == 1:
        with pytest.raises(httpx.HTTPStatusError):
            router._chat_once('https://example.test', 'test', '', {}, 1, 'final_decision', {'type': 'object'})
    else:
        assert router._chat_once('https://example.test', 'test', '', {}, 1,
                                 'final_decision', {'type': 'object'}) == {}
    assert len(calls) == expected_calls


def test_truncated_json_cannot_be_a_success():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}))
    router = Router(transport=transport, review_key='test')
    with pytest.raises(ValueError, match='not complete'):
        router._chat_once('https://example.test', 'test', '', {}, 1, 'final_decision', None)
    assert router.calls[-1]['status'] != 'ok'


def test_expired_model_error_cannot_trigger_fallback(monkeypatch):
    import hollerau.analytical.agent as module

    def fail(*args):
        raise FinalDecisionUnavailable('late response')

    monkeypatch.setattr(module, 'astra_decide', fail)
    monkeypatch.setenv('ASTRA_SAFE', '1')
    agent = SimpleNamespace(move_deadline=time.monotonic() - 1, case_id='test', turn=0,
                            final_authority=True, closing_only=False,
                            observe=lambda *a: None, check_budget=lambda: None,
                            offline_move=lambda *a: pytest.fail('late fallback'))
    with pytest.raises(FinalDecisionUnavailable, match='deadline expired'):
        AnalyticalAgent.decide(agent, {'case_id': 'test'}, {})
    assert agent.decision_deadline is None


def test_provider_slot_never_exceeds_remaining_budget(monkeypatch):
    import hollerau.analytical.router as module
    monkeypatch.setenv('ASTRA_MODEL', 'primary,backup')
    router = Router(review_key='test')
    slots = []
    monkeypatch.setattr(module.time, 'monotonic', lambda: 10)
    def call(*args, **kwargs):
        slots.append(args[4])
        return {}
    monkeypatch.setattr(router, '_chat_once', call)
    router._call_astra_chat('https://example.test', '', {}, 3, 'final_decision', None)
    assert slots == [3]
