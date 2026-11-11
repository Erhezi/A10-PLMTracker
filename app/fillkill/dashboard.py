"""Fill/Kill Dashboard (plan v2 §5.4): trends for the chosen dates and sites. Read-only.

The functions above ``build`` are pure (plain rows in, figures out) so they can be tested
without a database; ``build`` gathers the rows.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median

from . import queries, rollup

TOP_ITEMS = 10


def _day(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _moment(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def series_by_day(rows, start: date, end: date) -> dict:
    """{days: [...], series: {name: [lines per day]}}, with every day in the range on the axis."""
    days = date_range(start, end)
    index = {day: i for i, day in enumerate(days)}
    series: dict[str, list[int]] = {}
    for row in rows:
        name = row["series"] if row["series"] not in (None, "") else "No comment"
        counts = series.setdefault(name, [0] * len(days))
        day = _day(row["day"])
        if day in index:
            counts[index[day]] += int(row["lines"] or 0)
    ordered = dict(sorted(series.items(), key=lambda item: -sum(item[1])))
    return {"days": days, "series": ordered}


def _created_in(sub, start: date, end: date) -> bool:
    return start <= _day(sub["create_dt"]) <= end


def review_hours(subs, history, start: date, end: date) -> list[float]:
    """For subs added inside the dates: hours from being added to their first review."""
    first_review: dict[int, datetime] = {}
    for row in history:
        if row["action"] == "status" and row["entity_id"] not in first_review:
            first_review[row["entity_id"]] = _moment(row["acted_at"])
    hours = []
    for sub in subs:
        reviewed = first_review.get(sub["sub_id"])
        if reviewed and _created_in(sub, start, end):
            hours.append(max(0.0, (reviewed - _moment(sub["create_dt"])).total_seconds() / 3600))
    return hours


def weekly_new_subs(subs, start: date, end: date) -> dict:
    """Subs added per week (weeks start on Monday), by source. Not on the Dashboard for now (2026-10-21)."""
    first_monday = start - timedelta(days=start.weekday())
    weeks = []
    week = first_monday
    while week <= end:
        weeks.append(week)
        week += timedelta(days=7)
    index = {w: i for i, w in enumerate(weeks)}
    series: dict[str, list[int]] = defaultdict(lambda: [0] * len(weeks))
    for sub in subs:
        if not _created_in(sub, start, end):
            continue
        day = _day(sub["create_dt"])
        series[sub["source"]][index[day - timedelta(days=day.weekday())]] += 1
    return {"weeks": weeks, "series": dict(series)}


def rejected_groups(subs, history) -> list[dict]:
    """Subs rejected now, grouped by vendor (most first), with who rejected each, when, and comments.
    A sub's vendors are its vendor items' (2026-10-20); one rejected before any was added has none.
    Not on the Dashboard for now (2026-10-21)."""
    rejected_by: dict[int, dict] = {}
    comments: dict[int, list] = defaultdict(list)
    for row in history:
        if row["action"] == "status" and row["to_value"] == "rejected":
            rejected_by[row["entity_id"]] = row  # the latest rejection wins
        elif row["action"] == "comment":
            comments[row["entity_id"]].append({"actor": row["actor"], "acted_at": row["acted_at"], "comment": row["comment"]})
    groups: dict[str, list] = defaultdict(list)
    for sub in subs:
        if sub["status"] != "rejected":
            continue
        who = rejected_by.get(sub["sub_id"], {})
        vendors = " / ".join(sorted({item["vendor"] for item in sub.get("vendor_items") or []}))
        groups[vendors or "No vendor item"].append({
            "sub_id": sub["sub_id"], "medline_item": sub["medline_item"], "reference_sku": sub["reference_sku"],
            "rejected_by": who.get("actor"), "rejected_at": who.get("acted_at"), "comments": comments.get(sub["sub_id"], []),
        })
    return [
        {"vendor": vendor, "count": len(items), "subs": sorted(items, key=lambda s: str(s["rejected_at"] or ""), reverse=True)}
        for vendor, items in sorted(groups.items(), key=lambda g: (-len(g[1]), g[0].lower()))
    ]


def _hours(earlier: datetime, later: datetime) -> float:
    return max(0.0, (later - earlier).total_seconds() / 3600)


def _median(values) -> float | None:
    return round(median(values), 1) if values else None


def flow_hours(first_kill: dict, subs, orders) -> dict:
    """How fast killed items move (2026-10-19), as medians in hours over the Medline items killed
    in the dates: from the first kill to a sub (0 when one was already on file), from that sub to
    the item's first order since the kill, and from the kill to that order. Items still waiting
    aren't in a median; the counts say how many are. An item ordered before it had a sub (a vendor
    item without one, as SCM directs, 2026-11-02) counts in kill to order only."""
    first_sub: dict[str, datetime] = {}
    for sub in subs:
        created = _moment(sub["create_dt"])
        if sub["medline_item"] not in first_sub or created < first_sub[sub["medline_item"]]:
            first_sub[sub["medline_item"]] = created
    order_times: dict[str, list[datetime]] = defaultdict(list)
    for order in orders:
        order_times[order["medline_item"]].append(_moment(order["ordered_dt"]))
    kill_to_sub, sub_to_order, kill_to_order = [], [], []
    for item, killed in first_kill.items():
        killed = _moment(killed)
        after = [moment for moment in order_times.get(item, []) if moment >= killed]
        ordered = min(after) if after else None
        if ordered is not None:
            kill_to_order.append(_hours(killed, ordered))
        if item not in first_sub:
            continue
        entered = max(first_sub[item], killed)  # a sub already on file counts from the kill
        kill_to_sub.append(_hours(killed, entered))
        if ordered is not None and ordered >= entered:
            sub_to_order.append(_hours(entered, ordered))
    return {
        "items": len(first_kill),
        "kill_to_sub": _median(kill_to_sub), "items_with_sub": len(kill_to_sub),
        "sub_to_order": _median(sub_to_order), "items_sub_ordered": len(sub_to_order),
        "kill_to_order": _median(kill_to_order), "items_ordered": len(kill_to_order),
    }


def _short(row) -> bool:
    """Ordered, but fewer eaches than were killed (Main's "N EA short"), for the sites shown."""
    killed, ordered = row.get("killed_each"), row.get("sub_ordered_each")
    return row["ordering_status"] == "ordered" and killed is not None and ordered is not None and ordered < killed - 1e-9


def headline(rows, subs, hours, start: date, end: date) -> dict:
    items = len(rows)
    with_approved = sum(1 for r in rows if r["subs_status"].get("approved"))
    ordered = sum(1 for r in rows if r["ordering_status"] == "ordered")
    return {
        "items": items,
        "lines": sum(r["lines"] for r in rows),
        "items_with_approved_sub": with_approved,
        "items_ordered": ordered,
        # Per site through the site filter (the user, 2026-10-27); with every site, the totals.
        "items_ordered_short": sum(1 for r in rows if _short(r)),
        "share_with_approved_sub": round(100 * with_approved / items) if items else None,
        "share_ordered": round(100 * ordered / items) if items else None,
        "subs_added": sum(1 for s in subs if _created_in(s, start, end)),
        "subs_reviewed": len(hours),
        "median_review_hours": round(median(hours), 1) if hours else None,
    }


def build(scope: queries.Scope) -> dict:
    rows = rollup.build_main_rows(**queries.main_table_inputs(scope))
    subs = queries.all_subs()
    history = queries.sub_history(("status", "comment"))
    hours = review_hours(subs, history, scope.start, scope.end)
    status_counts = rollup.subs_status(subs)
    killed = queries.first_kills(scope)
    return {
        "scope": {"start": scope.start, "end": scope.end, "sites": scope.sites},
        "headline": headline(rows, subs, hours, scope.start, scope.end),
        "flow": flow_hours(killed, subs, queries.orders_since_start(scope, killed)),
        "by_reason": series_by_day(queries.lines_by_day(scope, "reason"), scope.start, scope.end),
        "by_site": series_by_day(queries.lines_by_day(scope, "site"), scope.start, scope.end),
        "top_items": rollup.most_killed(rows, TOP_ITEMS),
        "subs_by_status": status_counts,
        # Subs added per week (weekly_new_subs) and rejected subs by vendor (rejected_groups) are off
        # the Dashboard for now (the user, 2026-10-21); the functions stay, to bring them back.
    }
