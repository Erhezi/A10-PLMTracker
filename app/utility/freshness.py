"""How fresh a feed's data is: the "Data as of" note at the top right of Fill/Kill's Main and Order
Timing's Main, the same on both (2026-11-16). Each page shows it in grey, or as a warning badge
when it's stale.
"""

from __future__ import annotations

from datetime import datetime, timedelta

STALE_AFTER = timedelta(minutes=90)
FEED_HOURS = (8, 23)  # the hourly feeds run 8am-11pm; outside that, old data is expected


def data_as_of(last_success, last_lines, now: datetime) -> dict:
    """The last good feed run (``source`` "feed": "Data as of"), else the newest line ("lines":
    "Latest line update"); ``stale`` when that's more than STALE_AFTER old during FEED_HOURS."""
    as_of = last_success or last_lines
    if isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of)
    stale = bool(as_of and now - as_of > STALE_AFTER and FEED_HOURS[0] <= now.hour < FEED_HOURS[1])
    return {"as_of": as_of, "source": "feed" if last_success else "lines", "stale": stale}
