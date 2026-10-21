"""The item view kept in memory (app/fillkill/queries.py, 2026-10-21): read once, and again only when
the kill lines' "as of" moves, after ITEM_CACHE_SECONDS, or for a Medline item it hasn't got. SQL
Server is played here: no database is touched."""

import pytest

from app.fillkill import queries


@pytest.fixture
def view(monkeypatch):
    state = {"reads": 0, "as_of": "10:00", "now": 1000.0, "rows": [{"Medline Item": "A", "Infor Item": "1"}]}

    def read():
        state["reads"] += 1
        return [dict(row) for row in state["rows"]]

    monkeypatch.setattr(queries, "_is_mssql", lambda: True)
    monkeypatch.setattr(queries, "_read_item_view", read)
    monkeypatch.setattr(queries, "last_load", lambda: {"last_success": state["as_of"], "last_line_update": None})
    monkeypatch.setattr(queries, "monotonic", lambda: state["now"])
    queries.clear_item_cache()
    yield state
    queries.clear_item_cache()


def test_the_item_view_is_read_once_until_the_kill_lines_load_again(view):
    first = queries.item_view_rows()
    assert queries.item_view_rows(must_have={"A"}) is first and view["reads"] == 1
    assert queries.infor_items_of(["A"]) == {"A": "1"} and view["reads"] == 1
    view["as_of"] = "11:00"  # the hourly load
    queries.item_view_rows()
    assert view["reads"] == 2


def test_an_item_killed_since_or_old_rows_have_it_read_again(view):
    queries.item_view_rows()
    view["rows"].append({"Medline Item": "B", "Infor Item": "1"})
    assert [row["Medline Item"] for row in queries.item_view_rows(must_have={"B"})] == ["A", "B"]
    assert view["reads"] == 2
    view["now"] += queries.ITEM_CACHE_SECONDS  # Infor's item data may have changed
    queries.item_view_rows()
    assert view["reads"] == 3


def test_family_rows_come_from_the_rows_given_once_each():
    rows = [{"Medline Item": "A", "UM": "EA", "Customer Item #": "1", "Infor Item": "1", "Item Description": "x"},
            {"Medline Item": "A", "UM": "EA", "Customer Item #": "1", "Infor Item": "1", "Item Description": "y"},
            {"Medline Item": "B", "UM": "BX", "Customer Item #": "B", "Infor Item": "1"},
            {"Medline Item": "C", "UM": "EA", "Customer Item #": "C", "Infor Item": "2"}]
    assert queries.family_rows(["1", None], rows) == [
        {"Medline Item": "A", "UM": "EA", "Customer Item #": "1", "Infor Item": "1"},
        {"Medline Item": "B", "UM": "BX", "Customer Item #": "B", "Infor Item": "1"}]
