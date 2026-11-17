"""The "Data as of" note Fill/Kill's and Order Timing's Main both show (app/utility/freshness.py)."""

from datetime import datetime

from app.utility.freshness import data_as_of

NOON = datetime(2026, 11, 16, 12, 0)


def test_the_last_feed_run_else_the_newest_line():
    assert data_as_of(datetime(2026, 11, 16, 11, 30), datetime(2026, 11, 16, 11, 45), NOON) == {
        "as_of": datetime(2026, 11, 16, 11, 30), "source": "feed", "stale": False}
    assert data_as_of(None, "2026-11-16 11:45:00.253000", NOON) == {
        "as_of": datetime(2026, 11, 16, 11, 45, 0, 253000), "source": "lines", "stale": False}
    assert data_as_of(None, None, NOON) == {"as_of": None, "source": "lines", "stale": False}


def test_stale_after_90_minutes_in_the_feeds_hours():
    assert data_as_of(datetime(2026, 11, 16, 10, 29), None, NOON)["stale"] is True
    assert data_as_of(datetime(2026, 11, 16, 10, 31), None, NOON)["stale"] is False
    # Before 8am or from 11pm the feed doesn't run: old data is expected.
    assert data_as_of(datetime(2026, 11, 15, 22, 0), None, datetime(2026, 11, 16, 7, 59))["stale"] is False
    assert data_as_of(datetime(2026, 11, 16, 20, 0), None, datetime(2026, 11, 16, 23, 0))["stale"] is False
    assert data_as_of(datetime(2026, 11, 16, 6, 0), None, datetime(2026, 11, 16, 8, 0))["stale"] is True
