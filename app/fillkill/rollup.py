"""Main-table assembly (plan v2 §5.2, design §5). Pure: works on rows the queries return.

The main table has one row per **Infor item** (Materials Managers' choice, 2026-10-14). Its Medline
items are its **packagings**, listed inside the row; a Medline item Infor can't place stands alone.
Subs, picks and orders still belong to a Medline item.

Inputs, all plain dicts:
  qty_rows     vw_MedlineFillKillQtyAgg rows already filtered to the dates and sites:
               medline_item, um, ordered, filled, killed, lines (any granularity), and site, the
               Sold-To, for the per-site figures (2026-10-27)
  item_rows    vw_MedlineFillKillItemCollection rows of the Medline items in the range
  subs         subs of those Medline items and of their Infor items' other Medline items:
               sub_id, medline_item, reference_sku, status, is_picked, vendor_items
  orders       non-voided orders dated inside the range (2026-10-20) for its sites (2026-10-27), for
               the same Medline items: medline_item, order_id, site, quantity, uom, qoe, ordered_dt
  reasons      {medline_item: {comment, reason, reason_date, order_date, order_time}}: the latest
               comment in the range
  family_rows  item-view rows (Medline Item, UM, Customer Item #, Infor Item) of every Medline item
               Medline has killed under the Infor items in the range
  instructions the MM Lead's instructions for those Infor items, and for Medline items Infor had
               none for (2026-10-27), oldest first: infor_item, medline_item, instruction, written_by,
               written_at
"""

from __future__ import annotations

from collections import defaultdict

NEEDS = ("needs_subs", "needs_review", "needs_pick", "needs_details", "needs_order", "ordered")
NEEDS_LABELS = {
    "needs_subs": "Needs subs",
    "needs_review": "Needs review",
    "needs_pick": "Needs pick",
    "needs_details": "Needs details",  # a pick without a vendor item yet: the Materials Manager's
    "needs_order": "Needs order",
    "ordered": "Ordered",
}
STATUS_ORDER = ("approved", "hold", "pending_review", "rejected")

# Item-view columns, and what they're called here.
ITEM_FIELDS = {
    "description": "Item Description",                      # Medline's, from the latest kill line
    "customer_item": "Customer Item #",                     # Medline's; not always an Infor item
    "infor_item": "Infor Item",                             # Infor's, by Medline vendor item
    "manufacturer": "Manufacturer Name",
    "mfr_item": "Mfr. Item #",
    "item_qoe": "Item.UOMConversion",
    "vendor_item_qoe": "VendorItem.UOMConversion",
    "long_description": "Item.LongDescription",            # the Infor item's, spelled out
    "infor_active": "Item.Active",
    "commodity_code": "CommodityCode",
    "commodity_description": "CommodityCode.Description",
}
# Fields that describe the Infor item, so the same for all its packagings.
INFOR_FIELDS = ("long_description", "infor_active", "commodity_code", "commodity_description")


def _number(value) -> int:
    return int(value or 0)


def sum_quantities(qty_rows) -> dict[str, dict]:
    """Per Medline item: quantities per UOM (never added across UOMs) and the line count."""
    by_item: dict[str, dict] = {}
    for row in qty_rows:
        item = by_item.setdefault(row["medline_item"], {"by_uom": {}, "lines": 0})
        uom = row.get("um") or ""
        totals = item["by_uom"].setdefault(uom, {"uom": uom, "ordered": 0, "filled": 0, "killed": 0})
        for key in ("ordered", "filled", "killed"):
            totals[key] += _number(row.get(key))
        item["lines"] += _number(row.get("lines"))
    for item in by_item.values():
        item["by_uom"] = [item["by_uom"][uom] for uom in sorted(item["by_uom"])]
    return by_item


def merge_item_details(item_rows) -> dict[str, dict]:
    """One details dict per Medline item. A field whose rows disagree lists every value, and its
    name is added to ``varies``. ``infor_consistent`` is False if any row says Medline's customer item
    isn't the Infor item (or Infor has none)."""
    values: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    consistent: dict[str, bool] = {}
    for row in item_rows:
        item = row["Medline Item"]
        for key, column in ITEM_FIELDS.items():
            value = row.get(column)
            if value not in (None, "") and value not in values[item][key]:
                values[item][key].append(value)
        flag = row.get("Infor Item Consistency")
        if flag is not None:
            consistent[item] = consistent.get(item, True) and bool(flag)

    details = {}
    for item, fields in values.items():
        merged = {"varies": sorted(key for key, found in fields.items() if len(found) > 1)}
        for key in ITEM_FIELDS:
            found = fields.get(key, [])
            merged[key] = found[0] if len(found) == 1 else (" / ".join(map(str, found)) if found else None)
        merged["infor_consistent"] = consistent.get(item)
        details[item] = merged
    return details


def eaches(amounts) -> float | None:
    """(quantity, uom, eaches per unit) added up in eaches; an EA without a QOE counts 1. None when
    one can't be converted (no QOE for another UOM)."""
    total = 0.0
    for quantity, uom, per in amounts:
        if per in (None, ""):
            if str(uom or "").strip().upper() != "EA":
                return None
            per = 1
        total += float(quantity or 0) * float(per)
    return total


def subs_status(subs) -> dict[str, int]:
    counts = {status: 0 for status in STATUS_ORDER}
    for sub in subs:
        counts[sub["status"]] = counts.get(sub["status"], 0) + 1
    return counts


def needs_flags(counts: dict[str, int], *, has_pick: bool, ordered: bool, details_missing: bool = False) -> list[str]:
    """Design §5 Needs filter. An item can need more than one thing (e.g. review and order).
    ``details_missing``: a pick has no vendor item yet, nothing to order (2026-10-20); once
    ordered, it's done."""
    flags = []
    if counts.get("pending_review", 0) + counts.get("approved", 0) + counts.get("hold", 0) == 0:
        flags.append("needs_subs")
    if counts.get("pending_review", 0) > 0:
        flags.append("needs_review")
    if counts.get("approved", 0) > 0 and not has_pick:
        flags.append("needs_pick")
    if has_pick and details_missing and not ordered:  # an order took the details
        flags.append("needs_details")
    if has_pick and not ordered:
        flags.append("needs_order")
    if ordered:
        flags.append("ordered")
    return flags


def _text_key(value) -> tuple:
    """Sort key for text columns: blanks last, then case-insensitive."""
    return (value in (None, ""), str(value or "").lower())


def sort_key(row) -> tuple:
    """Infor Item, then Medline Item, then Item Description, then the other columns."""
    return (
        _text_key(row["infor_item"]), _text_key(row["medline_items"][0]), _text_key(row["description"]),
        -row["lines"],
    )


def _sub_key(sub) -> str:
    """The Reference SKU, ignoring case: the same sub on two Medline items."""
    return str(sub.get("reference_sku") or "").strip().lower()


def each_factors(item_rows) -> dict[tuple[str, str], float]:
    """Eaches per unit, per (Medline item, UOM), from Infor's UOM conversion of the Infor item."""
    factors = {}
    for row in item_rows:
        value = row.get("Item.UOMConversion")
        if value not in (None, ""):
            factors[(row["Medline Item"], row.get("UM") or "")] = float(value)
    return factors


def families(family_rows) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """(Medline item -> Infor item, Infor item -> {Medline item: its UOMs})."""
    infor_of: dict[str, str] = {}
    members: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for row in family_rows:
        item, infor = row["Medline Item"], row.get("Infor Item")
        if not infor:
            continue
        infor_of[item] = infor
        uom = row.get("UM") or ""
        if uom not in members[infor][item]:
            members[infor][item].append(uom)
    return infor_of, {i: {m: "/".join(sorted(u)) for m, u in ms.items()} for i, ms in members.items()}


def approved_on_other_packagings(item, subs_by_item, infor_of, members, *, skip=()) -> list[dict]:
    """Subs approved on another Medline item of the same Infor item and not approved here
    (signal, 2026-10-14). Medline items in ``skip`` aren't looked at."""
    infor = infor_of.get(item)
    if not infor:
        return []
    approved_here = {_sub_key(s) for s in subs_by_item.get(item, []) if s["status"] == "approved"}
    found, seen = [], set()
    for sibling, uom in sorted(members.get(infor, {}).items()):
        if sibling == item or sibling in skip:
            continue
        for s in subs_by_item.get(sibling, []):
            key = _sub_key(s)
            if s["status"] == "approved" and key not in approved_here and (sibling, key) not in seen:
                seen.add((sibling, key))
                found.append({"medline_item": sibling, "um": uom, "reference_sku": s["reference_sku"],
                              "sub_id": s["sub_id"]})
    return found


def sibling_signals(subs_here, sibling_subs, sibling_uoms) -> tuple[list[dict], list[dict]]:
    """For one packaging in the item panel.

    Returns its subs, each with ``approved_elsewhere`` (the same Reference SKU approved on another
    packaging), and the other packagings' subs that aren't on it yet, approved first.
    """
    by_key: dict[tuple, list] = defaultdict(list)
    for s in sibling_subs:
        by_key[_sub_key(s)].append({**s, "um": sibling_uoms.get(s["medline_item"], "")})
    here_keys = {_sub_key(s) for s in subs_here}
    annotated = [
        {**s, "approved_elsewhere": [o for o in by_key.get(_sub_key(s), []) if o["status"] == "approved"]}
        for s in subs_here
    ]
    rank = {status: i for i, status in enumerate(STATUS_ORDER)}
    others = sorted(
        (o for key, found in by_key.items() if key not in here_keys for o in found),
        key=lambda o: (rank.get(o["status"], 9), o["medline_item"], o["reference_sku"]),
    )
    return annotated, others


def latest_of(reasons):
    """The latest of several packagings' latest reasons."""
    found = [r for r in reasons if r]
    if not found:
        return None
    return max(found, key=lambda r: (str(r.get("order_date") or ""), str(r.get("order_time") or "")))


def _order_key(order) -> tuple:
    """Orders by date, then by ID (reverse it for newest first)."""
    return (str(order.get("ordered_dt") or ""), order.get("order_id") or 0)


def kills_by_site(qty_rows) -> dict[str, list[dict]]:
    """Per Medline item: what each site killed, per UOM (2026-10-27)."""
    found: dict[str, dict[tuple, dict]] = defaultdict(dict)
    for row in qty_rows:
        key = (row.get("site"), row.get("um") or "")
        entry = found[row["medline_item"]].setdefault(key, {"site": key[0], "uom": key[1], "killed": 0})
        entry["killed"] += _number(row.get("killed"))
    return {item: list(entries.values()) for item, entries in found.items()}


def site_figures(packagings, site_kills, factors, orders) -> list[dict]:
    """Per site (2026-10-27): what it killed of the row's Medline items, each UOM and in eaches, and
    its sub orders in eaches. Each site orders for itself, so its shortfall is its own. Orders
    recorded before sites are under None. Sorted by site, None last."""
    sites: dict = {}

    def entry(site):
        return sites.setdefault(site, {"site": site, "kills": [], "orders": []})

    for p in packagings:
        for k in site_kills.get(p["medline_item"], []):
            entry(k["site"])["kills"].append({"medline_item": p["medline_item"], "uom": k["uom"], "killed": k["killed"],
                                              "each": factors.get((p["medline_item"], k["uom"]))})
    for order in orders:
        entry(order.get("site"))["orders"].append(order)
    found = [{
        "site": e["site"],
        "kills": e["kills"],
        "killed_each": eaches((k["killed"], k["uom"], k["each"]) for k in e["kills"]),
        "orders": len(e["orders"]),
        "sub_ordered_each": eaches((o.get("quantity"), o.get("uom"), o.get("qoe")) for o in e["orders"]),
    } for e in sites.values()]
    return sorted(found, key=lambda s: (s["site"] is None, str(s["site"] or "")))


def row_instructions(infor, medline_items, instructions) -> list[dict]:
    """The row's instructions (2026-10-27): its Infor item's, and those written for its Medline items
    while Infor had none for them."""
    return [i for i in instructions
            if (infor and i.get("infor_item") == infor)
            or (i.get("infor_item") is None and i.get("medline_item") in medline_items)]


def _packaging(item, qty, info, factors, item_subs, reason, orders, infor) -> dict:
    for q in qty["by_uom"]:
        q["each"] = factors.get((item, q["uom"]))
    return {
        "medline_item": item,
        "customer_item": info["customer_item"],
        # Medline's customer item is the Infor item: no warning beside the Medline item.
        "consistent": bool(infor) and info["customer_item"] == infor,
        "description": info["description"],
        "varies": info["varies"],
        "quantities": qty["by_uom"],
        "lines": qty["lines"],
        "latest_reason": reason,
        "subs_status": subs_status(item_subs),
        "picks": sorted((s for s in item_subs if s.get("is_picked")), key=lambda s: s["sub_id"]),  # oldest first
        "orders": orders,
    }


def build_main_rows(qty_rows, item_rows, subs, orders, reasons, family_rows=(), instructions=()) -> list[dict]:
    """One row per Infor item killed in the range (a Medline item without one is its own row),
    sorted by ``sort_key``. Each row lists its packagings: its Medline items killed in the range."""
    quantities = sum_quantities(qty_rows)
    site_kills = kills_by_site(qty_rows)
    details = merge_item_details(item_rows)
    factors = each_factors(item_rows)
    infor_of, members = families(family_rows)
    subs_by_item: dict[str, list] = defaultdict(list)
    for sub in subs:
        subs_by_item[sub["medline_item"]].append(sub)
    orders_by_item: dict[str, list] = defaultdict(list)
    for order in sorted(orders, key=_order_key, reverse=True):
        orders_by_item[order["medline_item"]].append(order)

    blank = {key: None for key in ITEM_FIELDS} | {"varies": [], "infor_consistent": None}
    infos: dict[str, dict] = {}
    groups: dict[str, list] = defaultdict(list)
    for item, qty in quantities.items():
        info = blank | details.get(item, {})
        infos[item] = info
        infor = infor_of.get(item) or (None if "infor_item" in info["varies"] else info["infor_item"])
        groups[infor or f"M:{item}"].append(_packaging(
            item, qty, info, factors, subs_by_item.get(item, []), reasons.get(item),
            orders_by_item.get(item, []), infor,
        ))

    rows = []
    for key, packagings in groups.items():
        packagings.sort(key=lambda p: _text_key(p["medline_item"]))
        infor = None if key.startswith("M:") else key
        info = infos[packagings[0]["medline_item"]]
        here = {p["medline_item"] for p in packagings}
        row_subs = [s for p in packagings for s in subs_by_item.get(p["medline_item"], [])]
        counts = subs_status(row_subs)
        picks = [s for p in packagings for s in p["picks"]]
        row_orders = sorted((o for p in packagings for o in p["orders"]), key=_order_key, reverse=True)
        ordered = bool(row_orders)
        quantities_ = [q for p in packagings for q in p["quantities"]]
        # Approved on a packaging of this Infor item not killed in the range, and on none here.
        approved_here = {_sub_key(s) for s in row_subs if s["status"] == "approved"}
        elsewhere = {}
        for p in packagings:
            for found in approved_on_other_packagings(p["medline_item"], subs_by_item, infor_of, members, skip=here):
                if _sub_key(found) not in approved_here:
                    elsewhere[(found["medline_item"], found["sub_id"])] = found
        rows.append({
            "key": key,
            "infor_item": infor,
            "medline_items": [p["medline_item"] for p in packagings],
            "customer_items": sorted({p["customer_item"] for p in packagings if p["customer_item"]}),
            "packagings": packagings,
            "description": packagings[0]["description"],
            **{field: (info[field] if infor else None) for field in INFOR_FIELDS},
            "manufacturer": info["manufacturer"],
            "mfr_item": info["mfr_item"],
            "lines": sum(p["lines"] for p in packagings),
            # In eaches, by Infor's UOM conversion; None when a UOM has none.
            "quantities_each": {
                k: sum(q[k] * q["each"] for q in quantities_) for k in ("ordered", "killed", "filled")
            } if all(q["each"] is not None for q in quantities_) else None,
            "latest_reason": latest_of(p["latest_reason"] for p in packagings),
            "subs_status": counts,
            "picks": picks,
            "approved_other_packagings": list(elsewhere.values()),
            "orders": row_orders,  # dated inside the range, newest first
            # Killed and ordered in these dates, in eaches (2026-10-21): kill lines keep coming in
            # through the day, so a Materials Manager can see when orders fall short. An order counts
            # by its own QOE (quantity x eaches per its UOM).
            "killed_each": eaches((q["killed"], q["uom"], q["each"]) for q in quantities_),
            "sub_ordered_each": eaches((o.get("quantity"), o.get("uom"), o.get("qoe")) for o in row_orders),
            # The same per site (2026-10-27): each site orders for itself.
            "sites": site_figures(packagings, site_kills, factors, row_orders),
            # The MM Lead's instruction in force, and how many there have been (2026-10-27).
            "instruction": instruction_summary(row_instructions(infor, here, instructions)),
            "ordering_status": "ordered" if ordered else "no order",
            "needs": needs_flags(counts, has_pick=bool(picks), ordered=ordered,
                                 details_missing=any(not p.get("vendor_items") for p in picks)),
        })
    rows.sort(key=sort_key)
    return rows


def instruction_summary(found) -> dict | None:
    return {"count": len(found), "latest": found[-1]} if found else None


def killed_total(row) -> float:
    """For ranking: killed eaches when known, otherwise the killed quantities as they are."""
    if row.get("quantities_each"):
        return row["quantities_each"]["killed"]
    return float(sum(q["killed"] for p in row["packagings"] for q in p["quantities"]))


def most_killed(rows, limit: int) -> list[dict]:
    """The items with the most kill lines (then the most killed)."""
    return sorted(rows, key=lambda r: (-r["lines"], -killed_total(r), r["medline_items"][0]))[:limit]


def needs_counts(rows) -> dict[str, int]:
    counts = {"all": len(rows), **{flag: 0 for flag in NEEDS}}
    for row in rows:
        for flag in row["needs"]:
            counts[flag] += 1
    return counts
