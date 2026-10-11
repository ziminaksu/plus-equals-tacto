"""The runner never abandons a case on one bad move (Live Final wave test, 2026-10-11)."""
import sys

from arena_kit.play import play

play_mod = sys.modules["arena_kit.play"]  # the package re-exports play(), shadowing the module name


class Table:
    session_id = "s"

    def __init__(self):
        self.sent, self.refreshes = [], 0

    def open(self, case_id):
        case = {"case_id": case_id, "buyer": {}, "round_limit": 10}
        sheet = {"term_sheet_id": "offer:a-0", "terms": {"unit_price": 10}}
        return case, {"a": [{"from": "sales", "status": "open", "term_sheets": [sheet]}]}

    def refresh(self, threads):
        self.refreshes += 1
        threads["a"].append({"from": "arena", "status": "open", "timeout_reply": True,
                             "term_sheets": [{"term_sheet_id": f"offer:a-{self.refreshes}", "terms": {"unit_price": 9}}]})
        return [("a", threads["a"][-1])]

    def close(self, sid, msg):
        self.sent.append(msg)
        return {"deal": True, "offer_id": msg["action"]["term_sheet_id"]}

    def send(self, sid, msg):
        raise AssertionError("no counter expected")

    def result(self):
        return {"deal": False}


class Agent:
    def __init__(self):
        self.calls = 0

    def decide(self, case, threads):
        self.calls += 1
        if self.calls <= 2:
            raise RuntimeError("model crashed")
        if self.calls == 3:
            return {"supplier_id": "ghost", "message": {}}  # malformed -> closing_move
        raise AssertionError("closing_move should have closed the case")


def test_failed_and_malformed_decisions_do_not_abandon_the_case(monkeypatch):
    monkeypatch.setattr(play_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(play_mod, "closing_move", lambda case, threads: {
        "supplier_id": "a", "message": {"action": {"type": "accept", "term_sheet_id": "offer:a-2"}}})
    table, agent = Table(), Agent()
    result = play(table, "case:X", agent)
    assert result["deal"] and table.sent and agent.calls == 3 and table.refreshes >= 2
