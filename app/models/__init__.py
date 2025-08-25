from __future__ import annotations
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # py3.9+
except Exception:
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

NY_TZ = None
if ZoneInfo is not None:
    try:
        NY_TZ = ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:
        try:
            import tzdata  # noqa: F401
            NY_TZ = ZoneInfo("America/New_York")
        except Exception:
            NY_TZ = None

if NY_TZ is None:
    try:
        from dateutil.tz import gettz
        tz = gettz("America/New_York")
        if tz is not None:
            NY_TZ = tz
    except Exception:
        NY_TZ = None

if NY_TZ is None:
    NY_TZ = timezone(timedelta(hours=-5))


def now_ny() -> datetime:
    """Return current time in America/New_York as timezone-aware datetime."""
    return datetime.now(NY_TZ)

def now_ny_naive() -> datetime:
    """Return current time in America/New_York as naive datetime (no tzinfo) for DB storage."""
    return now_ny().replace(tzinfo=None)

__all__ = ["now_ny", "now_ny_naive", "NY_TZ"]

# Export commonly used model classes from submodules so callers can do
# `from app.models import ItemLocationPar` (used by `relations.py`).
try:
    # import lazily to avoid import-time side-effects; inventory has no
    # dependency on this module so this is safe.
    from .inventory import (
        Item,
        ContractItem,
        ItemLocationPar,
        ItemLocationInventory,
        Requesters365Day,
        PO90Day,
    )
    __all__.extend([
        "Item",
        "ContractItem",
        "ItemLocationPar",
        "ItemLocationInventory",
        "Requesters365Day",
        "PO90Day",
    ])
except Exception:
    # If inventory can't be imported at package-import time (e.g. missing
    # DB deps), keep package importable; the specific importers will
    # surface the real error when they import the models.
    pass
