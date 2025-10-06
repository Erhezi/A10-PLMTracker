from __future__ import annotations

from typing import List, Dict, Optional, Mapping, Tuple

from sqlalchemy import select
from sqlalchemy.orm import aliased

from .. import db
from ..models.inventory import ItemLocations  # legacy imports (may be removed later)
from ..models.relations import PLMTrackerBase  # new consolidated view


###############################################################################
# Unified location pair builder
###############################################################################

def build_location_pairs(
    stages: Optional[List[str]] = None,
    company: str | None = None,
    location: str | None = None,
    require_active: bool = False,
    include_par: bool = False,  # ignored for inventory-only view
    location_types: Optional[List[str]] = None,
    offset: int = 0,
    limit: int | None = None,
) -> List[Dict]:
    """Fetch pre-computed inventory side-by-side rows from PLM.vw_PLMTrackerBase.

    The consolidated view already joins source + replacement inventory attributes.
    We only apply lightweight filters and compute burn / weeks metrics.
    """
    v = PLMTrackerBase
    q = select(v)
    if stages:
        q = q.where(v.Stage.in_(stages))
    if company:
        # View may or may not have company; if absent remove this filter.
        if hasattr(v, "LocationType"):
            # company not in schema provided; skip if not present
            pass
    if location:
        q = q.where(v.Location == location)
    if require_active:
        q = q.where((v.Active == "true") | (v.Active.is_(None)))
    if location_types:
        q = q.where(v.LocationType.in_(location_types))

    if offset:
        q = q.offset(max(offset, 0))
    if limit is not None:
        q = q.limit(limit)
    rows_raw = db.session.execute(q).scalars().all()

    out: List[Dict] = []
    for r in rows_raw:
        # Burn estimation (source, replacement, and group/location aggregate)
        src_burn = burnrate_estimator(getattr(r, "br7_rolling_item", None), r.issued_count_365)
        repl_burn = burnrate_estimator(getattr(r, "br7_rolling_item_ri", None), r.issued_count_365_ri)
        group_loc_burn = burnrate_estimator(getattr(r, "br7_rolling_itemgroup", None))
        weekly_src = src_burn["weekly_burn"]
        weekly_repl = repl_burn["weekly_burn"]
        weekly_group = group_loc_burn["weekly_burn"]
        weeks_src = _weeks_on_hand(getattr(r, "AvailableQty", None), weekly_src)
        weeks_repl = _weeks_on_hand(getattr(r, "AvailableQty_ri", None), weekly_repl)

        out.append({
            "stage": r.Stage,
            "item_group": r.Item_Group,
            "item": r.Item,
            "replacement_item": r.Replace_Item,
            "location": r.Location,  # unified location label (view-level logic)
            "group_location": r.Group_Locations or r.Location,
            "location_ri": r.Location_ri or r.Location,  # fallback
            "location_type": r.LocationType,
            "auto_replenishment": r.AutomaticPO,
            "active": r.Active,
            "discontinued": r.Discontinued,
            "current_qty": r.AvailableQty,
            "reorder_point": r.ReorderPoint,
            "weekly_burn": weekly_src,
            "weekly_burn_group_location": weekly_group,
            "weeks_on_hand": weeks_src,
            "po_90_qty": r.OrderQty90_EA,
            "req_qty_ea": r.ReqQty90_EA,
            "requesters_past_year": r.issued_count_365,
            "item_description": r.ItemDescription,
            # replacement side
            "auto_replenishment_ri": r.AutomaticPO_ri,
            "active_ri": r.Active_ri,
            "discontinued_ri": r.Discontinued_ri,
            "current_qty_ri": r.AvailableQty_ri,
            "reorder_point_ri": r.ReorderPoint_ri,
            "weekly_burn_ri": weekly_repl,
            "weeks_on_hand_ri": weeks_repl,
            "po_90_qty_ri": r.OrderQty90_EA_ri,
            "req_qty_ea_ri": r.ReqQty90_EA_ri,
            "requesters_past_year_ri": r.issued_count_365_ri,
            "item_description_ri": r.ItemDescription_ri,
        })
    # Stable sort by item_group then location for display
    out.sort(key=lambda d: (
        d.get("item_group") or 0,
        (d.get("group_location") or d.get("location") or "")
    ))
    return out


# ---------------------------------------------------------------------------
# Burn rate estimation helper
# ---------------------------------------------------------------------------
PeriodValue = Optional[float]


def burnrate_estimator(
    br7_rolling: PeriodValue,
    issued_count_365: Optional[int] = None,
) -> Dict[str, float]:
    """Compute burn rate using 7-day rolling averages.

    The view provides a 7-day rolling daily burn rate for the primary and
    replacement items. We interpret the incoming value as the *daily* average
    and convert it to a weekly burn by multiplying by 7.

    If ``issued_count_365`` is provided and indicates sparse usage (<= 4
    requesters in the past year), we continue to apply the historical uplift of
    doubling the projected burn rate to avoid under-estimating demand.
    """
    if br7_rolling is None:
        daily = 0.0
    else:
        daily = float(br7_rolling)

    weekly = daily * 7
    if issued_count_365 is not None and issued_count_365 <= 4:
        daily *= 2
        weekly *= 2
    return {"daily_avg": daily, "weekly_burn": weekly}


def _weeks_on_hand(available_qty: Optional[float], weekly_burn: float) -> str | float:
    """Return naive weeks-on-hand (qty / weekly_burn)."""
    try:  # pragma: no cover - defensive block
        if available_qty is None or weekly_burn is None:
            return "unknown"
        wb = float(weekly_burn)
        if wb == 0:
            return "unknown"
        qty = float(available_qty)
        return qty / wb
    except Exception:
        return "unknown"


__all__ = [
    "build_location_pairs",
    "burnrate_estimator",
    "build_inventory_pairs",  # backward compatibility
]


# ---------------------------------------------------------------------------
# Backward compatibility shim (legacy name used by older routes)
# ---------------------------------------------------------------------------
def build_inventory_pairs(
    stages: Optional[List[str]] = None,
    company: str | None = None,
    location: str | None = None,
    require_active: bool = False,
) -> List[Dict]:
    """Shim calling build_location_pairs for existing imports.

    Kept temporarily so existing code importing build_inventory_pairs keeps working.
    Uses inventory mode (include_par=False) and defaults to Inventory Location type.
    """
    return build_location_pairs(
        stages=stages,
        company=company,
        location=location,
        require_active=require_active,
        include_par=False,
        location_types=["Inventory Location"],
    )