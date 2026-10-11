"""RFQ: timeout replies of the suppliers we did not answer reach the agent before its next decision."""
from arena_kit.play import RemoteTable, latest, live_threads


class FakeClient:
    def session(self, session_id, *, deadline=None):
        return {"status": "open", "threads": {
            "a": {"offer_id": "offer:a-3", "closed": None},
            "b": {"offer_id": None, "closed": "walked_away"},
            "c": {"offer_id": "offer:c-0", "closed": None}}}

    def thread(self, session_id, supplier_id, *, deadline=None):
        return {"a": {"status": "final_offer", "closed": None, "timeouts": [
                    {"offer_id": "offer:a-2", "round": 2, "status": "open", "terms": {"unit_price": 28.5}, "text": "x"},
                    {"offer_id": "offer:a-3", "round": 3, "status": "final_offer", "terms": {"unit_price": 28.5}}]},
                "b": {"status": "walked_away", "closed": "walked_away", "timeouts": [
                    {"offer_id": None, "round": 4, "status": "walked_away", "terms": {}}]}}[supplier_id]


def test_refresh_appends_timeout_offers_and_closures_once():
    table = RemoteTable(FakeClient())
    table.session_id = "s"
    sheet = lambda sid, n: {"from": "sales", "status": "open",  # noqa: E731
                            "term_sheets": [{"term_sheet_id": f"offer:{sid}-{n}", "terms": {"unit_price": 31}}]}
    threads = {"a": [sheet("a", 1)], "b": [sheet("b", 1)], "c": [sheet("c", 0)]}
    new = table.refresh(threads)
    assert latest(threads["a"])["status"] == "final_offer"
    assert latest(threads["a"])["term_sheets"][0]["term_sheet_id"] == "offer:a-3"
    assert live_threads(threads) == ["a", "c"]
    assert len(threads["c"]) == 1
    assert len(new) == 3
    assert table.refresh(threads) == []  # nothing is appended twice


def test_refresh_preserves_server_terminal_result():
    class EndedClient:
        def session(self, sid, *, deadline=None):
            return {'status': 'ended', 'result': {'deal': True, 'score': 0.7}}
        def thread(self, *args):
            raise AssertionError('must not read stale threads after session end')
    table = RemoteTable(EndedClient())
    table.session_id = 's'
    assert table.refresh({}) == []
    assert table.done == {'deal': True, 'score': 0.7}
