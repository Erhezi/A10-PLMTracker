"""The freshness note Fill/Kill's and Order Timing's pages show (app/utility/freshness.py): "Data as of"
(when Medline made the file) and "Last loaded"."""

from datetime import datetime

from app.utility.freshness import data_as_of, file_made_at

NOON = datetime(2026, 11, 16, 12, 0)
RAW = r"\\montefiore.org\centralfiles\data\Procurement PMO\dli2\Medline FillKill\Raw"


def test_the_last_feed_run_else_the_newest_line():
    assert data_as_of(datetime(2026, 11, 16, 11, 30), datetime(2026, 11, 16, 11, 45), NOON) == {
        "loaded_at": datetime(2026, 11, 16, 11, 30), "data_as_of": None, "file": None, "stale": False}
    assert data_as_of(None, "2026-11-16 11:45:00.253000", NOON)["loaded_at"] == datetime(2026, 11, 16, 11, 45, 0, 253000)
    assert data_as_of(None, None, NOON) == {"loaded_at": None, "data_as_of": None, "file": None, "stale": False}


def test_stale_after_90_minutes_in_the_feeds_hours():
    assert data_as_of(datetime(2026, 11, 16, 10, 29), None, NOON)["stale"] is True
    assert data_as_of(datetime(2026, 11, 16, 10, 31), None, NOON)["stale"] is False
    # Before 8am or from 11pm the feed doesn't run: old data is expected.
    assert data_as_of(datetime(2026, 11, 15, 22, 0), None, datetime(2026, 11, 16, 7, 59))["stale"] is False
    assert data_as_of(datetime(2026, 11, 16, 20, 0), None, datetime(2026, 11, 16, 23, 0))["stale"] is False
    assert data_as_of(datetime(2026, 11, 16, 6, 0), None, datetime(2026, 11, 16, 8, 0))["stale"] is True


def test_data_as_of_is_when_medline_made_the_file_in_new_york_time():
    loaded = datetime(2026, 11, 17, 14, 37, 7)
    data = data_as_of(loaded, None, datetime(2026, 11, 17, 15, 0), rf"{RAW}\MHS - FILL KILL REPORT-2026-11-17-01-04-00.xlsx")
    # 01-04-00 on a 12-hour clock, Central: 1:04 PM there, 2:04 PM here.
    assert data == {"loaded_at": loaded, "data_as_of": datetime(2026, 11, 17, 14, 4), "stale": False,
                    "file": "MHS - FILL KILL REPORT-2026-11-17-01-04-00.xlsx"}


def test_am_or_pm_by_the_load_time():
    # As O2 had them (2026-11-16 and 17): the file, when A13 loaded it, and when Medline made it.
    seen = [
        ("MHS - FILL KILL REPORT-2026-11-17-06-24-04.xlsx", datetime(2026, 11, 17, 7, 30, 7), datetime(2026, 11, 17, 7, 24, 4)),
        ("MHS - FILL KILL REPORT-2026-11-17-12-04-23.xlsx", datetime(2026, 11, 17, 13, 37, 7), datetime(2026, 11, 17, 13, 4, 23)),
        ("MHS - ORDER DETAIL REPORT-2026-11-17-09-08-27.xls", datetime(2026, 11, 17, 10, 16, 59), datetime(2026, 11, 17, 10, 8, 27)),
        ("MHS - FILL KILL REPORT-2026-11-16-07-08-06.xlsx", datetime(2026, 11, 16, 20, 30, 11), datetime(2026, 11, 16, 20, 8, 6)),
        # 11:02 PM Central is past midnight here; no new file came in the night, so the 6:30 AM run
        # loaded it again.
        ("MHS - FILL KILL REPORT-2026-11-16-11-02-24.xlsx", datetime(2026, 11, 17, 6, 30, 8), datetime(2026, 11, 17, 0, 2, 24)),
    ]
    for name, loaded, made in seen:
        assert file_made_at(name, loaded) == made, name


def test_no_data_as_of_without_a_stamp_or_a_load_time():
    assert file_made_at("MHS - FILL KILL REPORT.xlsx", datetime(2026, 11, 17, 14, 0)) is None
    assert file_made_at("MHS - FILL KILL REPORT-2026-11-17-01-04-00.xlsx", None) is None
    assert file_made_at(None, datetime(2026, 11, 17, 14, 0)) is None
    # Made after the load (beyond a clock's few minutes): it can't be read.
    assert file_made_at("REPORT-2026-11-17-06-24-04.xlsx", datetime(2026, 11, 17, 7, 0)) is None
    # A few minutes ahead of our clock is still read.
    assert file_made_at("REPORT-2026-11-17-01-04-00.xlsx", datetime(2026, 11, 17, 14, 0)) == datetime(2026, 11, 17, 14, 4)
    # An hour past 12 is read as it is.
    assert file_made_at("REPORT-2026-11-17-13-04-00.xlsx", datetime(2026, 11, 17, 15, 0)) == datetime(2026, 11, 17, 14, 4)
    assert data_as_of(datetime(2026, 11, 17, 14, 0), None, NOON, "report.xlsx")["file"] is None
