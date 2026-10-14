"""Main-table assembly (plan v2 §5.2, design §5). Pure: works on rows the queries return.

Inputs, all plain dicts:
  qty_rows   vw_MedlineFillKillQtyAgg rows already filtered to the dates and sites:
             medline_item, um, ordered, filled, killed, lines (any granularity)
  item_rows  vw_MedlineFillKillItemCollection rows; an item can have several (risk, plan §9)
  subs       the items' subs: sub_id, medline_item, vendor, vendor_part, status, is_picked, uom, qoe
  orders     the items' non-voided orders with ordered_dt inside the range: medline_item, ...
  reasons    {medline_item: {comment, reason, reason_date}}: the latest comment in the range
  family_rows  item-view rows (Medline Item, UM, Customer Item #) of every Medline item sharing a
             customer (Infor) item with an item in the range: its other packagings. ``subs`` then
             also holds their subs.
"""

from __future__ import annotations

from collections import defaultdict

NEEDS = ("needs_subs", "needs_review", "needs_pick", "needs_order", "ordered")
NEEDS_LABELS = {
    "needs_subs": "Needs subs",
    "needs_review": "Needs review",
    "needs_pick": "Needs pick",
    "needs_order": "Needs order",
    "ordered": "Ordered",
}
STATUS_ORDER = ("approved", "hold", "pending_review", "rejected")

# Item-view columns the main table shows, and what they're called in a row.
ITEM_FIELDS = {
    "description": "Item Description",                      # Medline's, from the latest kill line
    "customer_item": "Customer Item #",
    "infor_item": "Infor Item",
    "manufacturer": "Manufacturer Name",
    "mfr_item": "Mfr. Item #",
    "item_qoe": "Item.UOMConversion",
    "vendor_item_qoe": "VendorItem.UOMConversion",
    "long_description": "Item.LongDescription",            # the Infor item's, spelled out
    "infor_active": "Item.Active",
    "commodity_code": "CommodityCode",
    "commodity_description": "CommodityCode.Description",
}


def _number(value) -> int:
    return int(value or 0)


def sum_quantities(qty_rows) -> dict[str, dict]:
    """Per item: quantities per UOM (never added across UOMs) and the line count."""
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
    """One details dict per item. A field whose rows disagree lists every value, and its name is
    added to ``varies``. ``infor_consistent`` is False if any row says the Infor item differs."""
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


def subs_status(subs) -> dict[str, int]:
    counts = {status: 0 for status in STATUS_ORDER}
    for sub in subs:
        counts[sub["status"]] = counts.get(sub["status"], 0) + 1
    return counts


def needs_flags(counts: dict[str, int], *, has_pick: bool, ordered: bool) -> list[str]:
    """Design §5 Needs filter. An item can need more than one thing (e.g. review and order)."""
    flags = []
    if counts.get("pending_review", 0) + counts.get("approved", 0) + counts.get("hold", 0) == 0:
        flags.append("needs_subs")
    if counts.get("pending_review", 0) > 0:
        flags.append("needs_review")
    if counts.get("approved", 0) > 0 and not has_pick:
        flags.append("needs_pick")
    if has_pick and not ordered:
        flags.append("needs_order")
    if ordered:
        flags.append("ordered")
    return flags


def _text_key(value) -> tuple:
    """Sort key for text columns: blanks last, then case-insensitive."""
    return (value in (None, ""), str(value or "").lower())


def sort_key(row) -> tuple:
    """Customer Item, then Medline Item, then Item Description, then the other columns."""
    return (
        _text_key(row["customer_item"]), _text_key(row["medline_item"]), _text_key(row["description"]),
        -row["lines"], -sum(q["killed"] for q in row["quantities"]),
    )


def _sub_key(sub) -> tuple[str, str]:
    """Vendor and vendor part, ignoring case: the same sub on two Medline items."""
    return (str(sub.get("vendor") or "").strip().lower(), str(sub.get("vendor_part") or "").strip().lower())


def each_factors(item_rows) -> dict[tuple[str, str], float]:
    """Eaches per unit, per (Medline item, UOM), from Infor's UOM conversion of the customer item."""
    factors = {}
    for row in item_rows:
        value = row.get("Item.UOMConversion")
        if value not in (None, ""):
            factors[(row["Medline Item"], row.get("UM") or "")] = float(value)
    return factors


def families(family_rows) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """(Medline item -> customer item, customer item -> {Medline item: its UOMs})."""
    customer_of: dict[str, str] = {}
    members: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for row in family_rows:
        item, customer = row["Medline Item"], row.get("Customer Item #")
        if not customer:
            continue
        customer_of[item] = customer
        uom = row.get("UM") or ""
        if uom not in members[customer][item]:
            members[customer][item].append(uom)
    return customer_of, {c: {i: "/".join(sorted(u)) for i, u in m.items()} for c, m in members.items()}


def approved_on_other_packagings(item, subs_by_item, customer_of, members) -> list[dict]:
    """Subs approved on another Medline item of the same Infor item and not approved here (1, 2026-10-14)."""
    customer = customer_of.get(item)
    if not customer:
        return []
    approved_here = {_sub_key(s) for s in subs_by_item.get(item, []) if s["status"] == "approved"}
    found, seen = [], set()
    for sibling, uom in sorted(members.get(customer, {}).items()):
        if sibling == item:
            continue
        for s in subs_by_item.get(sibling, []):
            key = _sub_key(s)
            if s["status"] == "approved" and key not in approved_here and (sibling, key) not in seen:
                seen.add((sibling, key))
                found.append({"medline_item": sibling, "um": uom, "vendor": s["vendor"],
                              "vendor_part": s["vendor_part"], "sub_id": s["sub_id"]})
    return found


def sibling_signals(subs_here, sibling_subs, sibling_uoms) -> tuple[list[dict], list[dict]]:
    """For the item panel.

    Returns the item's subs, each with ``approved_elsewhere`` (the same vendor part approved on
    another packaging), and the other packagings' subs that aren't on this item yet, approved first.
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
        key=lambda o: (rank.get(o["status"], 9), o["medline_item"], o["vendor"], o["vendor_part"]),
    )
    return annotated, others


def infor_groups(rows) -> dict[str, dict]:
    """Per customer (Infor) item in the range: its Medline items and their combined quantities in
    eaches. ``complete`` is False when a UOM has no Infor conversion, so the eaches leave it out."""
    groups: dict[str, dict] = {}
    for row in rows:
        customer = row.get("customer_item")
        if not customer:
            continue
        group = groups.setdefault(customer, {
            "customer_item": customer, "medline_items": [], "lines": 0, "complete": True,
            "ordered_each": 0.0, "killed_each": 0.0, "filled_each": 0.0, "ordered": False,
        })
        group["medline_items"].append(row["medline_item"])
        group["lines"] += row["lines"]
        group["ordered"] = group["ordered"] or row["ordering_status"] == "ordered"
        for q in row["quantities"]:
            if q.get("each") is None:
                group["complete"] = False
                continue
            for key in ("ordered", "killed", "filled"):
                group[f"{key}_each"] += q[key] * q["each"]
    return groups


def build_main_rows(qty_rows, item_rows, subs, orders, reasons, family_rows=()) -> list[dict]:
    """One row per Medline item killed in the range, sorted by ``sort_key``."""
    quantities = sum_quantities(qty_rows)
    details = merge_item_details(item_rows)
    factors = each_factors(item_rows)
    customer_of, members = families(family_rows)
    subs_by_item: dict[str, list] = defaultdict(list)
    for sub in subs:
        subs_by_item[sub["medline_item"]].append(sub)
    orders_by_item: dict[str, int] = defaultdict(int)
    for order in orders:
        orders_by_item[order["medline_item"]] += 1

    rows = []
    for item, qty in quantities.items():
        for q in qty["by_uom"]:
            q["each"] = factors.get((item, q["uom"]))
        item_subs = subs_by_item.get(item, [])
        counts = subs_status(item_subs)
        picks = [sub for sub in item_subs if sub.get("is_picked")]
        ordered = orders_by_item.get(item, 0) > 0
        rows.append({
            "medline_item": item,
            **{key: None for key in ITEM_FIELDS},
            "varies": [],
            "infor_consistent": None,
            **details.get(item, {}),
            "quantities": qty["by_uom"],
            "lines": qty["lines"],
            "latest_reason": reasons.get(item),
            "subs_status": counts,
            "picks": picks,
            "approved_other_packagings": approved_on_other_packagings(item, subs_by_item, customer_of, members),
            "orders_in_range": orders_by_item.get(item, 0),
            "ordering_status": "ordered" if ordered else "no order",
            "needs": needs_flags(counts, has_pick=bool(picks), ordered=ordered),
        })
    rows.sort(key=sort_key)
    return rows


def most_killed(rows, limit: int) -> list[dict]:
    """The items with the most kill lines (then the most killed quantity)."""
    return sorted(rows, key=lambda r: (-r["lines"], -sum(q["killed"] for q in r["quantities"]), r["medline_item"]))[:limit]


def needs_counts(rows) -> dict[str, int]:
    counts = {"all": len(rows), **{flag: 0 for flag in NEEDS}}
    for row in rows:
        for flag in row["needs"]:
            counts[flag] += 1
    return counts
