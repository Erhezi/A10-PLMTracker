"""How fresh a feed's data is: the note at the top right of Fill/Kill's Main and Order Timing's pages,
the same on each (2026-11-16). Each page shows it in grey, or as a warning badge when it's stale.

Two times (the user, 2026-11-17): when we last loaded the feed ("Last loaded"; until then the page
said "Data as of" for it), and when Medline made the file we loaded ("Data as of"), which is earlier:
Medline sends a file, A13 loads it at its next hourly run. Medline's file names carry that time:
"MHS - FILL KILL REPORT-2026-11-17-01-04-00.xlsx" was made at 1:04 PM Central (loaded at 2:37 PM New
York time). The stamp is Central time on a 12-hour clock without AM or PM, so of its two readings the
later one not after the load is taken (on O2 every file so far was loaded within 7 hours). A file
whose name doesn't end with such a stamp gives no "Data as of", only "Last loaded".
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import PureWindowsPath
from zoneinfo import ZoneInfo

STALE_AFTER = timedelta(minutes=90)
FEED_HOURS = (8, 23)  # the hourly feeds run 8am-11pm; outside that, old data is expected

CENTRAL = ZoneInfo("America/Chicago")  # Medline's file names
NEW_YORK = ZoneInfo("America/New_York")  # the app's times, and the loads'
# The stamp at the end of Medline's file names: date, then hour, minute and second.
FILE_STAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})\.[A-Za-z0-9]+$")
# Medline's clock and ours may differ a little: a file "made" a few minutes after we loaded it still
# reads as made then.
CLOCK_SLACK = timedelta(minutes=10)


def _datetime(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def file_made_at(name, loaded_at) -> datetime | None:
    """When Medline made the file ``name`` (a path or a file name), in New York time, from the stamp
    at the end of its name; None without a stamp or a load time to read it by (see the top)."""
    match = FILE_STAMP.search(str(name or "").strip())
    loaded_at = _datetime(loaded_at)
    if not match or loaded_at is None:
        return None
    year, month, day, hour, minute, second = map(int, match.groups())
    # 12 is noon or midnight; an hour past 12 or 00 can only be read one way.
    hours = (hour % 12, hour % 12 + 12) if 1 <= hour <= 12 else (hour,)
    readings = []
    for h in hours:
        try:
            central = datetime(year, month, day, h, minute, second, tzinfo=CENTRAL)
        except ValueError:
            continue
        readings.append(central.astimezone(NEW_YORK).replace(tzinfo=None))
    fitting = [made for made in readings if made <= loaded_at + CLOCK_SLACK]
    return max(fitting) if fitting else None


def data_as_of(last_success, last_lines, now: datetime, last_file=None) -> dict:
    """The feed's freshness: ``loaded_at``, the last good feed run, else the newest line's load;
    ``data_as_of``, when Medline made the file loaded (``last_file``, its name in ``file``), or None;
    ``stale`` when the load is more than STALE_AFTER old during FEED_HOURS."""
    loaded_at = _datetime(last_success or last_lines)
    stale = bool(loaded_at and now - loaded_at > STALE_AFTER and FEED_HOURS[0] <= now.hour < FEED_HOURS[1])
    made = file_made_at(last_file, loaded_at)
    return {"loaded_at": loaded_at, "data_as_of": made,
            "file": PureWindowsPath(str(last_file).strip()).name if made else None, "stale": stale}
