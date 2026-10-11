"""Runner recovery protocol tests; no model, simulator, or network."""
import importlib
from types import SimpleNamespace

import pytest

from arena_kit.play import play


def setup():
    events = {'s': [{'from': 'supplier', 'status': 'open', 'term_sheets': []}]}
    calls = []
    def decide(*args):
        calls.append('decide')
        raise RuntimeError('provider failed')
    agent = SimpleNamespace(decide=decide)
    table = SimpleNamespace(open=lambda _: ({'case_id': 'x'}, events))
    return agent, table, calls


def test_terminal_refresh_finishes_without_another_model_call(monkeypatch):
    monkeypatch.setattr(importlib.import_module('arena_kit.play').time, 'sleep', lambda _: None)
    agent, table, calls = setup()
    def refresh(_):
        table.done = {'deal': False, 'end_reason': 'expired'}
    table.refresh = refresh
    assert play(table, 'x', agent) == table.done
    assert calls == ['decide']


def test_no_new_state_does_not_grant_a_new_move_budget(monkeypatch):
    monkeypatch.setattr(importlib.import_module('arena_kit.play').time, 'sleep', lambda _: None)
    agent, table, calls = setup()
    table.refresh = lambda _: []
    with pytest.raises(RuntimeError, match='no new supplier state'):
        play(table, 'x', agent)
    assert calls == ['decide']
