"""Order Timing's Dashboard (2026-11-20): the whole picture of Medline's order feed in the days and
sites chosen. How many POs and lines Medline got from us, whether it confirmed them and how fast, when
they come in, which ones got their ship notice (ASN) that day, and what Medline rejected or short
shipped, per site. Read-only.

What O2 showed on 2026-11-20 (11/17 to 11/19, 748 POs), and why the page is laid out this way:
- Medline confirms most POs within minutes (Mins to Confirm is the same on every line of a PO). The
  slow ones were all received in the evening (19:00 to 22:00, Medline's clock): their sales orders
  weren't created until 2 to 5 AM. So the time to confirm is charted by the hour received.
- ASNs come in waves (11:00 to 12:00 and 15:00), and only POs created by about 9 AM had one. Medline's
  report covers each order day only (Report Date is the day Medline created the order, and each
  day's lines are as of that day's last file), so an ASN sent the next day never reaches the feed:
  "ASN" here means one sent on the order's own day.

The functions above ``build`` are pure (the queries' rows in, figures out), so they can be tested
without a database; ``build`` gathers the rows (queries.dashboard_*).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median

from . import queries

HOURS = 24
# How long Medline took to confirm a PO (its Mins to Confirm, as Main shows it), in bands: each
# band's key, label and upper limit in minutes, inclusive (None: no limit). A PO not confirmed yet
# has a band of its own.
CONFIRM_BANDS = (
    ("within_15", "Within 15 min", 15),
    ("within_60", "15 min to 1 hour", 60),
    ("within_240", "1 to 4 hours", 240),
    ("over_240", "Over 4 hours", None),
)
NOT_CONFIRMED = ("not_confirmed", "Not confirmed yet")
SLOW_MINUTES = 60  # the headline's "took over an hour"
SLOWEST = 8  # POs in the slowest-to-confirm list (as tall as the chart beside it)


def _moment(value) -> datetime | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _day(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _number(value) -> int:
    return int(value or 0)


def _median(values) -> float | None:
    return round(median(values), 1) if values else None


def _share(part: int, whole: int, digits: int = 0) -> float | None:
    """``part`` as a percentage of ``whole``; None when there's no whole."""
    if not whole:
        return None
    value = round(100 * part / whole, digits)
    return int(value) if digits == 0 else value


def date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


# --- each PO ----------------------------------------------------------------------------------

def order_figures(row: dict) -> dict:
    """A PO from queries.dashboard_orders: confirmed when every line has its 855 (as on Main), with
    Medline's minutes to confirm it (worked out from the times if Medline left them out), and the
    hours from Medline receiving it to its first ASN."""
    received, confirmed, asn = _moment(row["received_at"]), _moment(row["confirmed_at"]), _moment(row["asn_at"])
    rows = _number(row["line_rows"])
    is_confirmed = bool(rows) and _number(row["confirmed_lines"]) >= rows
    minutes = None
    if is_confirmed:
        minutes = row["mins_to_confirm"]
        if minutes is None and received and confirmed:
            minutes = max(0.0, (confirmed - received).total_seconds() / 60)
        minutes = float(minutes) if minutes is not None else None
    return {
        "order_no": row["order_no"], "po": row["po"], "site": row["site"], "site_name": row["site_name"],
        "report_date": _day(row["report_date"]) if row["report_date"] else None,
        "received_at": received, "created_at": _moment(row["created_at"]),
        "confirmed": is_confirmed, "confirmed_at": confirmed if is_confirmed else None, "minutes": minutes,
        "asn_at": asn,
        "asn_hours": round(max(0.0, (asn - received).total_seconds() / 3600), 2) if asn and received else None,
        "lines": _number(row["lines"]),
        "rejected_lines": _number(row["rejected_lines"]),
        "short_lines": _number(row["short_lines"]),
    }


def confirm_band(order: dict) -> str:
    """The CONFIRM_BANDS key for how long Medline took to confirm the PO, or NOT_CONFIRMED's."""
    if not order["confirmed"]:
        return NOT_CONFIRMED[0]
    minutes = order["minutes"] or 0
    for key, _label, limit in CONFIRM_BANDS:
        if limit is None or minutes <= limit:
            return key
    return CONFIRM_BANDS[-1][0]


# --- the figures ----------------------------------------------------------------------------------

def summary(orders: list[dict]) -> dict:
    """The headline's figures for these POs (every site, or one site's on the sites table): POs and
    lines; confirmed, and the median minutes to confirm (and how many took over an hour); with an
    ASN that day, and the median hours from receipt to it; and rejected and short-shipped lines."""
    confirmed = [o for o in orders if o["confirmed"]]
    minutes = [o["minutes"] for o in confirmed if o["minutes"] is not None]
    shipped = [o for o in orders if o["asn_at"]]
    lines = sum(o["lines"] for o in orders)
    rejected = sum(o["rejected_lines"] for o in orders)
    short = sum(o["short_lines"] for o in orders)
    return {
        "pos": len(orders),
        "lines": lines,
        "confirmed": len(confirmed),
        "not_confirmed": len(orders) - len(confirmed),
        "share_confirmed": _share(len(confirmed), len(orders)),
        "median_confirm_minutes": _median(minutes),
        "slow": sum(1 for m in minutes if m > SLOW_MINUTES),
        "asn": len(shipped),
        "share_asn": _share(len(shipped), len(orders)),
        "median_asn_hours": _median([o["asn_hours"] for o in shipped if o["asn_hours"] is not None]),
        "rejected_lines": rejected,
        "rejected_pos": sum(1 for o in orders if o["rejected_lines"]),
        "short_lines": short,
        "short_pos": sum(1 for o in orders if o["short_lines"]),
        "share_short": _share(short, lines, 1),
    }


def headline(orders: list[dict]) -> dict:
    return {**summary(orders), "sites": len({o["site"] for o in orders})}


def by_day(day_rows: list[dict], start: date, end: date) -> dict:
    """Lines per order day in each Line Status (Main's tabs' order; a status the view adds comes after
    them), and the short-shipped ones, with every day of the range on the axis."""
    days = date_range(start, end)
    index = {d: i for i, d in enumerate(days)}
    series = {code: [0] * len(days) for code, _ in queries.STATUSES}
    short = [0] * len(days)
    for row in day_rows:
        i = index.get(_day(row["day"]))
        if i is None:
            continue
        series.setdefault(row["status"] or "", [0] * len(days))[i] += _number(row["lines"])
        short[i] += _number(row["short_lines"])
    return {"days": days, "series": series, "short": short}


def by_hour_received(orders: list[dict]) -> dict:
    """POs by the hour Medline received them (its clock, as it sends it), in each confirm band."""
    series = {key: [0] * HOURS for key, _label, _limit in CONFIRM_BANDS}
    series[NOT_CONFIRMED[0]] = [0] * HOURS
    for order in orders:
        if order["received_at"]:
            series[confirm_band(order)][order["received_at"].hour] += 1
    return {"series": series}


def by_hour_created(orders: list[dict]) -> dict:
    """POs by the hour Medline created their sales order, with an ASN that day or without one."""
    series = {"asn": [0] * HOURS, "no_asn": [0] * HOURS}
    for order in orders:
        if order["created_at"]:
            series["asn" if order["asn_at"] else "no_asn"][order["created_at"].hour] += 1
    return {"series": series}


def by_site(orders: list[dict]) -> list[dict]:
    """Each Sold-To's summary, the most POs first, then by name."""
    groups: dict[str, list[dict]] = {}
    for order in orders:
        groups.setdefault(order["site"], []).append(order)
    rows = [{"site": site, "site_name": max((o["site_name"] or "" for o in group), default="") or site,
             **summary(group)} for site, group in groups.items()]
    return sorted(rows, key=lambda row: (-row["pos"], row["site_name"]))


def slowest(orders: list[dict], n: int = SLOWEST) -> list[dict]:
    """The POs Medline took longest to confirm, slowest first."""
    timed = [o for o in orders if o["confirmed"] and o["minutes"] is not None]
    timed.sort(key=lambda o: (-o["minutes"], str(o["received_at"] or ""), o["order_no"]))
    keys = ("order_no", "po", "site", "site_name", "report_date", "received_at", "created_at", "confirmed_at",
            "minutes", "lines")
    return [{key: o[key] for key in keys} for o in timed[:n]]


def build(filters: queries.Filters) -> dict:
    orders = [order_figures(row) for row in queries.dashboard_orders(filters)]
    return {
        "scope": {"start": filters.start, "end": filters.end, "sites": filters.sites},
        "headline": headline(orders),
        "by_day": by_day(queries.dashboard_days(filters), filters.start, filters.end),
        "by_hour_received": by_hour_received(orders),
        "by_hour_created": by_hour_created(orders),
        "sites": by_site(orders),
        "slowest": slowest(orders),
        "rejected": queries.dashboard_rejected(filters),
    }
