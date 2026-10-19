"""The Fill/Kill Dashboard: its figures (app/fillkill/dashboard.py) and its page and API."""

from datetime import date, datetime

from app.fillkill import dashboard
from conftest import add_view_rows, login, make_user

D = date(2026, 9, 28)


def sub(sub_id, status, created, source="manual", vendor="Owens", item="A"):
    return {"sub_id": sub_id, "medline_item": item, "vendor": vendor, "vendor_part": f"P{sub_id}",
            "status": status, "source": source, "create_dt": created}


def hist(sub_id, action, at, to_value=None, comment=None, actor="nurse@example.org"):
    return {"entity_id": sub_id, "action": action, "acted_at": at, "to_value": to_value, "comment": comment, "actor": actor}


def test_every_day_is_on_the_axis_and_busiest_series_first():
    rows = [{"day": "2026-09-28", "series": "MBO", "lines": 2},
            {"day": "2026-09-30", "series": "ALLOCATION", "lines": 5},
            {"day": "2026-09-30", "series": None, "lines": 1}]
    out = dashboard.series_by_day(rows, D, date(2026, 9, 30))
    assert out["days"] == [date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)]
    assert out["series"] == {"ALLOCATION": [0, 0, 5], "MBO": [2, 0, 0], "No comment": [0, 0, 1]}
    assert list(out["series"]) == ["ALLOCATION", "MBO", "No comment"]


def test_review_hours_count_subs_added_in_the_dates_until_their_first_review():
    subs = [sub(1, "approved", datetime(2026, 9, 28, 8)), sub(2, "rejected", datetime(2026, 9, 29, 8)),
            sub(3, "pending_review", datetime(2026, 9, 29, 9)), sub(4, "approved", datetime(2026, 9, 1, 8))]
    history = [hist(1, "status", datetime(2026, 9, 28, 10), "hold"), hist(1, "status", datetime(2026, 9, 29, 10), "approved"),
               hist(2, "status", datetime(2026, 9, 29, 14), "rejected"), hist(4, "status", datetime(2026, 9, 2, 8), "approved")]
    assert sorted(dashboard.review_hours(subs, history, D, date(2026, 9, 30))) == [2.0, 6.0]


def test_new_subs_per_week_by_source():
    subs = [sub(1, "approved", datetime(2026, 9, 28, 8)), sub(2, "approved", datetime(2026, 10, 6, 8), source="medline_pbo"),
            sub(3, "approved", datetime(2026, 8, 1, 8))]
    out = dashboard.weekly_new_subs(subs, D, date(2026, 10, 7))
    assert out["weeks"] == [date(2026, 9, 28), date(2026, 10, 5)]
    assert out["series"] == {"manual": [1, 0], "medline_pbo": [0, 1]}


def test_rejected_subs_grouped_by_vendor_with_who_and_comments():
    subs = [sub(1, "rejected", datetime(2026, 9, 28), vendor="Owens"), sub(2, "rejected", datetime(2026, 9, 28), vendor="Owens"),
            sub(3, "rejected", datetime(2026, 9, 28), vendor="Cardinal"), sub(4, "approved", datetime(2026, 9, 28), vendor="Cardinal")]
    history = [hist(1, "status", datetime(2026, 9, 29, 9), "rejected", actor="a@x"),
               hist(1, "comment", datetime(2026, 9, 29, 9), comment="latex"),
               hist(2, "status", datetime(2026, 9, 30, 9), "rejected", actor="b@x"),
               hist(3, "status", datetime(2026, 9, 30, 9), "rejected")]
    groups = dashboard.rejected_groups(subs, history)
    assert [(g["vendor"], g["count"]) for g in groups] == [("Owens", 2), ("Cardinal", 1)]
    assert [s["rejected_by"] for s in groups[0]["subs"]] == ["b@x", "a@x"]  # newest first
    assert groups[0]["subs"][1]["comments"][0]["comment"] == "latex"


def test_headline():
    rows = [{"lines": 3, "subs_status": {"approved": 1}, "ordering_status": "ordered"},
            {"lines": 1, "subs_status": {"approved": 0}, "ordering_status": "no order"}]
    out = dashboard.headline(rows, [sub(1, "approved", datetime(2026, 9, 28))], [1.0, 3.0, 8.0], D, D)
    assert out == {"items": 2, "lines": 4, "items_with_approved_sub": 1, "items_ordered": 1,
                   "share_with_approved_sub": 50, "share_ordered": 50, "subs_added": 1, "subs_reviewed": 3,
                   "median_review_hours": 3.0}


def test_dashboard_page_and_api(sqlite_app):
    add_view_rows(sqlite_app, "vw_MedlineFillKillQtyAgg", [
        {"Order Date": f"2026-09-{d:02d}", "Sold-To": "S1", "Sold-To Name": "WHITE PLAINS", "Medline Item": "A", "UM": "EA",
         "Total Ordered Qty": 5, "Total Filled Qty": 0, "Total Killed Qty": 5, "Total PO Line Count": 1}
        for d in range(1, 31)
    ])
    add_view_rows(sqlite_app, "vw_MedlineFillKill", [
        {"Order Date": f"2026-09-{d:02d}", "Sold-To": "S1", "Sold-To Name": "WHITE PLAINS", "Item": "A",
         "Order Qty": 5, "Filled Qty": 0, "Reason": "MBO", "Sales Order #": str(d), "Order Line #": "1"}
        for d in range(1, 31)
    ])
    make_user(sqlite_app, "viewer@example.org", plm=None, fillkill=("viewer",))
    c = sqlite_app.test_client()
    login(c, "viewer@example.org")

    page = c.get("/fillkill/dashboard").get_data(as_text=True)
    assert 'aria-current="page">Dashboard</a>' in page
    assert '"start": "2026-09-01"' in page and '"end": "2026-09-30"' in page  # last 30 days of data

    data = c.get("/fillkill/api/dashboard", headers={"X-Requested-With": "fetch"}).get_json()
    assert data["scope"] == {"start": "2026-09-01", "end": "2026-09-30", "sites": []}
    assert data["headline"]["items"] == 1 and data["headline"]["lines"] == 30
    assert len(data["by_reason"]["days"]) == 30 and data["by_reason"]["series"]["MBO"] == [1] * 30
    assert data["by_site"]["series"] == {"WHITE PLAINS": [1] * 30}
    assert data["subs_by_status"] == {"approved": 0, "hold": 0, "pending_review": 0, "rejected": 0}
    assert data["flow"] == {"items": 1, "kill_to_sub": None, "items_with_sub": 0, "sub_to_order": None,
                            "kill_to_order": None, "items_ordered": 0}


def test_flow_medians_from_kill_to_sub_to_order():
    first_kill = {"A": datetime(2026, 9, 28, 8), "B": datetime(2026, 9, 28, 8), "C": datetime(2026, 9, 29, 8),
                  "D": datetime(2026, 9, 29, 8)}
    subs = [{**sub(1, "approved", datetime(2026, 9, 28, 12), item="A")},   # A: 4 h to a sub
            {**sub(2, "approved", datetime(2026, 9, 28, 20), item="A")},   # (a later one doesn't count)
            {**sub(3, "approved", datetime(2026, 9, 1, 8), item="B")},     # B: one already on file: 0 h
            {**sub(4, "approved", datetime(2026, 9, 30, 8), item="C")}]    # C: 24 h; D: no sub yet
    orders = [{"medline_item": "A", "ordered_dt": datetime(2026, 9, 28, 18)},  # A: 6 h after its sub, 10 after the kill
              {"medline_item": "B", "ordered_dt": datetime(2026, 9, 27, 8)},   # before B's kill: not this one
              {"medline_item": "B", "ordered_dt": datetime(2026, 9, 28, 10)}]  # B: 2 h
    assert dashboard.flow_hours(first_kill, subs, orders) == {
        "items": 4, "kill_to_sub": 4.0, "items_with_sub": 3,
        "sub_to_order": 4.0, "kill_to_order": 6.0, "items_ordered": 2,
    }
