from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from typing import List, Dict, Optional

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
    br_calc_type: str = "simple",
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
            "preferred_bin": r.PreferredBin,
            "group_location": r.Group_Locations or r.Location,
            "location_ri": r.Location_ri or r.Location,  # fallback
            "preferred_bin_ri": getattr(r, "PreferredBin_ri", None),
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
            "item_description": r.ItemDescription,
            # UOM and reorder policy fields for original item
            "stock_uom": r.StockUOM,
            "uom_conversion": r.UOMConversion,
            "buy_uom": r.DefaultBuyUOM,
            "buy_uom_multiplier": r.BuyUOMMultiplier,
            "transaction_uom": r.DefaultTransactionUOM,
            "transaction_uom_multiplier": r.TransactionUOMMultiplier,
            "reorder_quantity_code": r.ReorderQuantityCode,
            "min_order_qty": r.MinOrderQty,
            "max_order_qty": r.MaxOrderQty,
            "manufacturer_number": r.ManufacturerNumber,
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
            "item_description_ri": r.ItemDescription_ri,
            # UOM and reorder policy fields for replacement item
            "stock_uom_ri": r.StockUOM_ri,
            "uom_conversion_ri": r.UOMConversion_ri,
            "buy_uom_ri": r.DefaultBuyUOM_ri,
            "buy_uom_multiplier_ri": r.BuyUOMMultiplier_ri,
            "transaction_uom_ri": r.DefaultTransactionUOM_ri,
            "transaction_uom_multiplier_ri": r.TransactionUOMMultiplier_ri,
            "reorder_quantity_code_ri": r.ReorderQuantityCode_ri,
            "min_order_qty_ri": r.MinOrderQty_ri,
            "max_order_qty_ri": r.MaxOrderQty_ri,
            "manufacturer_number_ri": r.ManufacturerNumber_ri,
        })
    _annotate_replacement_setups(out, br_calc_type=br_calc_type)
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
    requests in the past year), we continue to apply the historical uplift of
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
            return "n/a"
        wb = float(weekly_burn)
        if wb == 0:
            return "n/a"
        qty = float(available_qty)
        return qty / wb
    except Exception:
        return "n/a"


def _annotate_replacement_setups(rows: List[Dict], br_calc_type: str = "simple") -> None:
    """Attach relationship classification and recommended RI quantities."""
    groups: Dict[tuple, List[Dict]] = defaultdict(list)
    for row in rows:
        key = (
            row.get("item_group"),
            row.get("group_location") or row.get("location"),
        )
        groups[key].append(row)

    for group_rows in groups.values():
        items = {r.get("item") for r in group_rows if r.get("item")}
        replacements = {r.get("replacement_item") for r in group_rows if r.get("replacement_item")}

        if len(items) == 1 and len(replacements) == 1:
            relation = "1-1"
        elif len(items) <= 1 and len(replacements) > 1:
            relation = "1-many"
        elif len(items) > 1 and len(replacements) <= 1:
            relation = "many-1"
        elif not items and not replacements:
            relation = "unknown"
        else:
            relation = "many-many"

        for row in group_rows:
            row["item_replace_relation"] = relation
            row["BRCalcType"] = br_calc_type

        if relation == "1-1":
            base = next(
                (r for r in group_rows if r.get("item") and r.get("replacement_item")),
                group_rows[0],
            )
            calculations = _compute_replacement_quantities(base, br_calc_type=br_calc_type)
            for row in group_rows:
                row.update(calculations)
        elif relation == "many-1":
            calculations = _compute_many_to_one_quantities(group_rows, br_calc_type=br_calc_type)
            if calculations:
                for row in group_rows:
                    row.update(calculations)
        elif relation == "1-many":
            _apply_one_to_many_quantities(group_rows, br_calc_type=br_calc_type)


def _normalize_location_type(value: object | None) -> str:
    return str(value or "").strip().lower()


def _is_par_location(row: Dict) -> bool:
    return _normalize_location_type(row.get("location_type")) == "par location"


def _positive_decimal_value(value: object | None) -> Optional[Decimal]:
    dec = _to_decimal(value)
    if dec is None or dec <= 0:
        return None
    return dec


def _non_negative_decimal_value(value: object | None) -> Optional[Decimal]:
    dec = _to_decimal(value)
    if dec is None:
        return None
    if dec < 0:
        return None
    return dec


def _coerce_multiplier(value: object | None, default: Optional[Decimal] = Decimal(1)) -> Optional[Decimal]:
    dec = _positive_decimal_value(value)
    if dec is None:
        return default
    return dec


def _scaled_value(
    value: Optional[Decimal],
    numerator_multiplier: Optional[Decimal],
    denominator_multiplier: Optional[Decimal],
) -> Optional[Decimal]:
    if value is None:
        return None
    numerator = numerator_multiplier if numerator_multiplier is not None else Decimal(1)
    denominator = denominator_multiplier if denominator_multiplier is not None else Decimal(1)
    if denominator == 0:
        return None
    return (value * numerator) / denominator


def _divide(value: Optional[Decimal], denominator: Optional[Decimal]) -> Optional[Decimal]:
    if value is None:
        return None
    return _scaled_value(value, Decimal(1), denominator)


def _round_half_up_integer(value: Optional[Decimal]) -> Optional[Decimal]:
    if value is None:
        return None
    return value.to_integral_value(rounding=ROUND_HALF_UP)


def _ceil_positive_value(value: Optional[Decimal]) -> Optional[Decimal]:
    if value is None:
        return None
    return value.to_integral_value(rounding=ROUND_CEILING)


def _sum_weighted(rows: List[Dict], value_key: str, multiplier_key: str) -> Optional[Decimal]:
    total = Decimal(0)
    has_value = False
    for row in rows:
        base_value = _to_decimal(row.get(value_key))
        if base_value is None:
            continue
        multiplier = _coerce_multiplier(row.get(multiplier_key))
        if multiplier is None:
            continue
        total += base_value * multiplier
        has_value = True
    return total if has_value else None


def _collect_non_negative(rows: List[Dict], key: str) -> List[Optional[Decimal]]:
    return [_non_negative_decimal_value(row.get(key)) for row in rows]


def _compute_replacement_quantities(row: Dict, br_calc_type: str = "simple") -> Dict[str, Optional[float]]:
    is_par = _is_par_location(row)
    relation_label = "par" if is_par else "inventory"
    result: Dict[str, Optional[float]] = {
        "recommended_reorder_point_ri": None,
        "recommended_min_order_qty_ri": None,
        "recommended_max_order_qty_ri": None,
        "recommended_reorder_quantity_code_ri": row.get("reorder_quantity_code") or row.get("reorder_quantity_code_ri"),
        "recommended_setup_source": f"{br_calc_type}-1-1-{relation_label}",
    }

    if br_calc_type != "simple":
        return result

    src_reorder = _to_decimal(row.get("reorder_point"))
    src_min = _non_negative_decimal_value(row.get("min_order_qty"))
    src_max = _non_negative_decimal_value(row.get("max_order_qty"))

    src_stock_mult = _coerce_multiplier(row.get("uom_conversion"))
    repl_stock_mult = _coerce_multiplier(row.get("uom_conversion_ri"))
    repl_buy_mult = _positive_decimal_value(row.get("buy_uom_multiplier_ri"))
    repl_trans_mult = _positive_decimal_value(row.get("transaction_uom_multiplier_ri"))

    reorder_calc = _ceil_positive_value(_scaled_value(src_reorder, src_stock_mult, repl_stock_mult))
    if reorder_calc is None:
        reorder_calc = src_reorder

    if is_par:
        min_calc = src_min
    else:
        min_calc = repl_buy_mult if repl_buy_mult is not None else src_min

    max_calc: Optional[Decimal] = None
    if is_par:
        max_ratio = _scaled_value(src_max, src_stock_mult, repl_trans_mult)
        if max_ratio is not None:
            max_calc = _round_half_up_integer(max_ratio)
    else:
        if repl_buy_mult is not None:
            unit_ratio = _scaled_value(src_max, src_stock_mult, repl_buy_mult)
            units = _round_half_up_integer(unit_ratio)
            if units is not None:
                max_calc = units * repl_buy_mult

    if max_calc is None:
        max_calc = src_max

    result.update({
        "recommended_reorder_point_ri": _to_native(reorder_calc),
        "recommended_min_order_qty_ri": _to_native(min_calc),
        "recommended_max_order_qty_ri": _to_native(max_calc),
    })
    return result


def _compute_many_to_one_quantities(group_rows: List[Dict], br_calc_type: str = "simple") -> Dict[str, Optional[float]]:
    if not group_rows:
        return {}

    base = next((r for r in group_rows if r.get("replacement_item")), group_rows[0])
    is_par = _is_par_location(base)
    relation_label = "par" if is_par else "inventory"

    result: Dict[str, Optional[float]] = {
        "recommended_setup_source": f"{br_calc_type}-many-1-{relation_label}",
        "recommended_reorder_quantity_code_ri": base.get("reorder_quantity_code_ri") or base.get("reorder_quantity_code"),
        "recommended_reorder_point_ri": None,
        "recommended_min_order_qty_ri": None,
        "recommended_max_order_qty_ri": None,
    }

    if br_calc_type != "simple":
        return result

    reorder_weighted = _sum_weighted(group_rows, "reorder_point", "uom_conversion")
    max_weighted = _sum_weighted(group_rows, "max_order_qty", "uom_conversion")
    src_min_candidates = _collect_non_negative(group_rows, "min_order_qty")

    repl_stock_mult = _coerce_multiplier(base.get("uom_conversion_ri"))
    repl_buy_mult = _positive_decimal_value(base.get("buy_uom_multiplier_ri"))
    repl_trans_mult = _positive_decimal_value(base.get("transaction_uom_multiplier_ri"))

    reorder_calc = _ceil_positive_value(_divide(reorder_weighted, repl_stock_mult))
    if reorder_calc is None:
        reorder_calc = _non_negative_decimal_value(reorder_weighted)

    if is_par:
        min_calc = _max_positive(src_min_candidates)
    else:
        min_calc = repl_buy_mult if repl_buy_mult is not None else _max_positive(src_min_candidates)

    max_calc: Optional[Decimal] = None
    if is_par:
        max_ratio = _divide(max_weighted, repl_trans_mult)
        if max_ratio is not None:
            max_calc = _round_half_up_integer(max_ratio)
    else:
        if repl_buy_mult is not None:
            unit_ratio = _divide(max_weighted, repl_buy_mult)
            units = _round_half_up_integer(unit_ratio)
            if units is not None:
                max_calc = units * repl_buy_mult
        else:
            unit_ratio = _divide(max_weighted, None)
            max_calc = unit_ratio

    if max_calc is None:
        max_calc = _max_positive(_collect_non_negative(group_rows, "max_order_qty"))

    result.update({
        "recommended_reorder_point_ri": _to_native(reorder_calc),
        "recommended_min_order_qty_ri": _to_native(min_calc),
        "recommended_max_order_qty_ri": _to_native(max_calc),
    })
    return result


def _apply_one_to_many_quantities(group_rows: List[Dict], br_calc_type: str = "simple") -> None:
    """Distribute source policy values evenly across multiple replacements."""
    if not group_rows:
        return

    replacements = [r for r in group_rows if r.get("replacement_item")]
    if not replacements:
        return

    count = len(replacements)
    if count == 0:
        return

    fraction = Decimal(1) / Decimal(count)

    for row in group_rows:
        if not row.get("replacement_item"):
            continue

        is_par = _is_par_location(row)
        relation_label = "par" if is_par else "inventory"
        row["recommended_setup_source"] = f"{br_calc_type}-1-many-{relation_label}"
        row["recommended_reorder_quantity_code_ri"] = row.get("reorder_quantity_code_ri") or row.get("reorder_quantity_code")

        if br_calc_type != "simple":
            continue

        src_reorder = _to_decimal(row.get("reorder_point"))
        src_max = _non_negative_decimal_value(row.get("max_order_qty"))
        src_min = _non_negative_decimal_value(row.get("min_order_qty"))

        src_stock_mult = _coerce_multiplier(row.get("uom_conversion"))
        repl_stock_mult = _coerce_multiplier(row.get("uom_conversion_ri"))
        repl_buy_mult = _positive_decimal_value(row.get("buy_uom_multiplier_ri"))
        repl_trans_mult = _positive_decimal_value(row.get("transaction_uom_multiplier_ri"))

        numerator_mult = (src_stock_mult if src_stock_mult is not None else Decimal(1)) * fraction

        reorder_raw = _scaled_value(src_reorder, numerator_mult, repl_stock_mult)
        if is_par:
            reorder_calc = _ceil_positive_value(reorder_raw)
        else:
            reorder_calc = _round_half_up_integer(reorder_raw)
        if reorder_calc is None and reorder_raw is not None:
            reorder_calc = _non_negative_decimal_value(reorder_raw)

        if is_par:
            min_calc = src_min
        else:
            min_calc = repl_buy_mult if repl_buy_mult is not None else src_min

        max_calc: Optional[Decimal] = None
        if is_par:
            max_ratio = _scaled_value(src_max, numerator_mult, repl_trans_mult)
            if max_ratio is not None:
                max_calc = _round_half_up_integer(max_ratio)
        else:
            max_ratio = _scaled_value(src_max, numerator_mult, repl_buy_mult)
            if max_ratio is not None:
                units = _round_half_up_integer(max_ratio)
                if units is not None and repl_buy_mult is not None:
                    max_calc = units * repl_buy_mult
                elif units is not None:
                    max_calc = units

        if max_calc is None:
            if max_ratio is not None:
                max_calc = _non_negative_decimal_value(max_ratio)
            else:
                max_calc = src_max

        row.update({
            "recommended_reorder_point_ri": _to_native(reorder_calc),
            "recommended_min_order_qty_ri": _to_native(min_calc),
            "recommended_max_order_qty_ri": _to_native(max_calc),
        })


def _to_decimal(value: object | None) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _ceil_to_multiple(value: Optional[Decimal], multiple: Decimal) -> Optional[Decimal]:
    if value is None or multiple is None or multiple == 0:
        return value
    quotient = (value / multiple).to_integral_value(rounding=ROUND_CEILING)
    return quotient * multiple


def _round_to_multiple(value: Optional[Decimal], step: Decimal) -> Optional[Decimal]:
    if value is None or step is None or step <= 0:
        return value
    units = (value / step).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return units * step


def _sum_non_negative(rows: List[Dict], key: str) -> Optional[Decimal]:
    total = Decimal(0)
    has_value = False
    for row in rows:
        val = _to_decimal(row.get(key))
        if val is None:
            continue
        if val < 0:
            continue
        total += val
        has_value = True
    return total if has_value else None


def _max_positive(values: List[Optional[Decimal]]) -> Optional[Decimal]:
    positives = [v for v in values if v is not None and v > 0]
    if not positives:
        return None
    return max(positives)


def _to_native(value: Optional[Decimal]) -> Optional[float]:
    if value is None:
        return None
    normalized = value
    if normalized == normalized.to_integral():
        return int(normalized)
    return float(normalized)


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
    br_calc_type: str = "simple",
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
        br_calc_type=br_calc_type,
    )