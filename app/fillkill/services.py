"""Every Fill/Kill write (plan v2 §5.3): one transaction per action, with its History rows.

Callers check the user's role first (routes, via ``access.require_module``);
these functions check the rules and record who did what. On a ``RuleError``
nothing is written.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import and_, delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from .. import db
from ..models import now_ny_naive
from ..models.fillkill import History, ItemInstruction, Sub, SubOrder, VendorItem
from . import queries, rules
from .rules import RuleError

log = logging.getLogger(__name__)

VENDOR_LOOKUP_DOWN = (
    "Infor's vendor list can't be read right now, so nothing was saved. "
    "Try again later, or ask the Item Management admin."
)


# --- helpers ---------------------------------------------------------------------

def _history(entity: str, entity_id: int, medline_item: str, action: str, actor: str, at: datetime,
             *, field=None, from_value=None, to_value=None, comment=None) -> None:
    db.session.add(History(
        entity=entity, entity_id=entity_id, medline_item=medline_item, action=action,
        field=field, from_value=rules.display(from_value), to_value=rules.display(to_value),
        comment=comment, actor=actor, acted_at=at,
    ))


def _locked(model, key):
    """The row, re-read and locked for this transaction (UPDLOCK on SQL Server)."""
    pk = model.__table__.primary_key.columns.values()[0]
    row = db.session.execute(
        select(model).where(pk == key).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        noun = {Sub: "sub", VendorItem: "vendor item"}.get(model, "order")
        raise RuleError(f"That {noun} no longer exists; reload the page.", 404)
    return row


def _live_sub(sub_id: int) -> Sub:
    """The sub, locked; a deleted one can't be changed."""
    sub = _locked(Sub, sub_id)
    if sub.deleted_at is not None:
        raise RuleError(f"{sub.label()} was deleted by {sub.deleted_by}; reload the page.", 409)
    return sub


def _live_vendor_item(vendor_item_id: int) -> tuple[VendorItem, Sub | None]:
    """The vendor item and its sub, both locked; neither may be deleted. A vendor item without a sub
    (SCM's, 2026-11-02) comes with None."""
    item = _locked(VendorItem, vendor_item_id)
    if item.deleted_at is not None:
        raise RuleError(f"Vendor item {item.label()} was deleted by {item.deleted_by}; reload the page.", 409)
    return item, (_live_sub(item.sub_id) if item.sub_id is not None else None)


def _last_change(entity: str, entity_id: int) -> History | None:
    return db.session.execute(
        select(History).where(History.entity == entity, History.entity_id == entity_id)
        .order_by(History.acted_at.desc(), History.history_id.desc()).limit(1)
    ).scalar_one_or_none()


def _ensure_current(sub: Sub, expected_status: str | None) -> None:
    """P9: refuse if the sub's status moved on since the user loaded it."""
    if expected_status is None or sub.status == expected_status:
        return
    last = _last_change("sub", sub.sub_id)
    who = f" by {last.actor} at {last.acted_at:%m/%d %H:%M}" if last else ""
    raise RuleError(
        f"{sub.label()} was changed{who} and is now {rules.STATUS_LABELS[sub.status]}; "
        "reload to see the latest.",
        409,
    )


def _ensure_unique(medline_item: str, reference_sku: str, *, except_id: int | None = None) -> None:
    """One live sub per Medline item and Reference SKU."""
    query = select(Sub).where(
        Sub.medline_item == medline_item,
        func.lower(Sub.reference_sku) == reference_sku.lower(),
        Sub.deleted_at.is_(None),
    )
    if except_id is not None:
        query = query.where(Sub.sub_id != except_id)
    existing = db.session.execute(query).scalars().first()
    if existing is not None:
        raise RuleError(
            f"{existing.label()} is already a sub of {medline_item} "
            f"({rules.STATUS_LABELS[existing.status]}).",
            409,
        )


def _ensure_unique_vendor_item(sub: Sub | None, medline_item: str, values: dict, *, except_id: int | None = None) -> None:
    """One live vendor item per sub, vendor ID, vendor part and UOM; without a sub, per Medline item."""
    query = select(VendorItem).where(
        VendorItem.sub_id == sub.sub_id if sub else and_(VendorItem.sub_id.is_(None), VendorItem.medline_item == medline_item),
        VendorItem.vendor_id == values["vendor_id"],
        func.lower(VendorItem.vendor_part) == values["vendor_part"].lower(), VendorItem.uom == values["uom"],
        VendorItem.deleted_at.is_(None),
    )
    if except_id is not None:
        query = query.where(VendorItem.vendor_item_id != except_id)
    existing = db.session.execute(query).scalars().first()
    if existing is not None:
        owner = sub.label() if sub else f"{medline_item} (no sub)"
        raise RuleError(f"{owner} already has vendor item {existing.label()} (vendor ID {existing.vendor_id}).", 409)


def find_vendor(vendor_id: str) -> dict | None:
    """Infor's vendor for an ID (vw_Vendor, 13_contract_search.sql). If the lookup itself fails (the
    view is missing or not readable), the user gets a message instead of a server error, and the
    details go to the log."""
    try:
        return queries.vendor(vendor_id)
    except SQLAlchemyError:
        db.session.rollback()
        log.exception("FillKill.vw_Vendor lookup failed; has 13_contract_search.sql been run?")
        raise RuleError(VENDOR_LOOKUP_DOWN, 503) from None


def search_vendors(q: str) -> list[dict]:
    """Infor's vendors whose names match ``q`` (queries.search_vendors), or a message instead of a
    server error when vw_Vendor can't be read."""
    try:
        return queries.search_vendors(q)
    except SQLAlchemyError:
        db.session.rollback()
        log.exception("FillKill.vw_Vendor search failed; has 13_contract_search.sql been run?")
        raise RuleError(VENDOR_LOOKUP_DOWN, 503) from None


def uom_aliases() -> dict[str, str]:
    """Infor's UOM for one typed another way (queries.uom_aliases). If vw_UomAlias can't be read
    (13_contract_search.sql not run yet, or no grant), UOMs stay as typed and the log says why;
    nothing is refused for it. Read before a change starts: it rolls the session back on failure."""
    try:
        return queries.uom_aliases()
    except SQLAlchemyError:
        db.session.rollback()
        log.exception("FillKill.vw_UomAlias read failed; has 13_contract_search.sql been run?")
        return {}


def site_codes() -> list[str]:
    """The sites an order can be for (2026-10-27): Medline's Sold-To codes in the kill lines."""
    return [site["code"] for site in queries.sites()]


def _check_vendor_id(vendor_id: str | None) -> dict | None:
    """A vendor ID, when given, must be one Infor knows, or 0000000 (Vendor not available in system).
    Returns Infor's vendor for it (None for 0000000 or no ID)."""
    if not vendor_id or vendor_id == rules.NO_VENDOR_ID:
        return None
    found = find_vendor(vendor_id)
    if found is None:
        raise RuleError(f"Vendor ID {vendor_id} isn't in Infor's vendor list. Fix it, or use "
                        f"{rules.NO_VENDOR_ID} ({rules.NO_VENDOR_LABEL}).")
    return found


def _infor_name(found: dict | None) -> str | None:
    """Infor's name for a vendor ID (2026-10-21): the vendor name follows the ID, so a name and an ID
    saved together are always the same vendor. None for 0000000, whose name is typed by hand."""
    name = str((found or {}).get("vendor_name") or "").strip()
    return name[:rules.LIMITS["vendor"]] or None


def _vendor_follows_id(record, changes: dict) -> None:
    """In a correction that touches the vendor or its ID, the vendor name becomes Infor's for the ID
    (an order from before vendor IDs may have none: its name stays as typed). A name typed for an
    Infor vendor ID, and nothing else, is refused: the ID is what to change."""
    if not changes.keys() & {"vendor", "vendor_id"}:
        return
    vendor_id = changes.get("vendor_id", record.vendor_id)
    name = _infor_name(_check_vendor_id(vendor_id))
    if name is None:
        return
    if name == record.vendor:
        changes.pop("vendor", None)
    else:
        changes["vendor"] = name
    if not changes:
        raise RuleError(f"The vendor name follows the vendor ID: Infor calls {vendor_id} {name}. "
                        "To change the vendor, change its vendor ID.")


def _commit():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _run(action):
    """Run ``action`` and commit; roll back and re-raise on any failure."""
    try:
        result = action()
    except Exception:
        db.session.rollback()
        raise
    _commit()
    return result


def _open_orders(sub: Sub) -> int:
    return db.session.execute(
        select(func.count()).select_from(SubOrder).where(SubOrder.sub_id == sub.sub_id, SubOrder.voided_at.is_(None))
    ).scalar()


# --- subs: entering, correcting, deleting ------------------------------------------------------

def add_sub(data: dict, actor: str, *, source: str = "manual", approve: bool = False) -> Sub:
    """A new sub: its Reference SKU. With ``approve`` (a Sub Approver entering it) it's approved on
    entry, so it can be ordered; otherwise it waits for review (a Sub Finder, a future AI finder).
    Medline's subs are added by 14_pbo_sync.sql, not here."""
    clean = rules.check_new_sub(data)

    def action():
        _ensure_unique(clean["medline_item"], clean["reference_sku"])
        now = now_ny_naive()
        sub = Sub(
            medline_item=clean["medline_item"], reference_sku=clean["reference_sku"],
            status="pending_review", source=source, entered_by=actor,
            create_dt=now, update_dt=now,
        )
        db.session.add(sub)
        db.session.flush()
        _history("sub", sub.sub_id, sub.medline_item, "created", actor, now)
        if clean["comment"]:
            _history("sub", sub.sub_id, sub.medline_item, "comment", actor, now, comment=clean["comment"])
        if approve:
            sub.status = "approved"
            _history("sub", sub.sub_id, sub.medline_item, "status", actor, now,
                     field="status", from_value="pending_review", to_value="approved")
        return sub

    return _run(action)


def edit_sub(sub_id: int, data: dict, actor: str) -> Sub:
    """Nursing corrects the Reference SKU they entered, until the sub has an order. Its vendor items
    stay as they are: they're the Materials Manager's (2026-10-20)."""
    def action():
        sub = _live_sub(sub_id)
        new = rules.clean_field("reference_sku", data.get("reference_sku"), required=True)
        if new == sub.reference_sku:
            raise RuleError("Nothing to change.")
        if _open_orders(sub):
            raise RuleError(f"{sub.label()} has an order, so its Reference SKU can't change.", 409)
        _ensure_unique(sub.medline_item, new, except_id=sub.sub_id)
        now = now_ny_naive()
        _history("sub", sub.sub_id, sub.medline_item, "edit", actor, now,
                 field="reference_sku", from_value=sub.reference_sku, to_value=new)
        sub.reference_sku = new
        sub.update_dt = now
        return sub

    return _run(action)


def delete_sub(sub_id: int, reason, actor: str, *, expected_status: str | None = None) -> Sub:
    """Hide a sub everywhere, keeping its row and history (who, when, why). Refused for a sub
    with orders that aren't voided."""
    def action():
        sub = _live_sub(sub_id)
        _ensure_current(sub, expected_status)
        why = rules.check_delete(sub, reason)
        orders = _open_orders(sub)
        if orders:
            raise RuleError(f"{sub.label()} has {orders} order{'s' if orders > 1 else ''}; "
                            "void {} before deleting it.".format("them" if orders > 1 else "it"), 409)
        now = now_ny_naive()
        sub.deleted_at, sub.deleted_by, sub.delete_reason = now, actor, why
        sub.update_dt = now
        _history("sub", sub.sub_id, sub.medline_item, "delete", actor, now, comment=why)
        return sub

    return _run(action)


# --- subs (Sub Approver) -------------------------------------------------------------

def set_status(sub_id: int, new_status: str, actor: str, *, expected_status: str | None = None,
               reason=None) -> Sub:
    """S1, S2: approve, hold or reject. Every approved sub can be ordered; on hold or rejected it
    can't, and its orders so far stay (2026-10-28, the user: picking among approved subs is gone).
    ``reason``, if nursing gives one, is kept as the sub's comment, after its new status."""
    def action():
        sub = _live_sub(sub_id)
        _ensure_current(sub, expected_status)
        status = rules.check_status_change(sub, new_status)
        why = rules.clean_status_reason(reason)
        now = now_ny_naive()
        _history("sub", sub.sub_id, sub.medline_item, "status", actor, now,
                 field="status", from_value=sub.status, to_value=status)
        if why:
            _history("sub", sub.sub_id, sub.medline_item, "comment", actor, now,
                     comment=f"{rules.STATUS_LABELS[status]}: {why}")
        sub.status = status
        sub.update_dt = now
        return sub

    return _run(action)


def comment_on_sub(sub_id: int, text, actor: str) -> Sub:
    comment = rules.clean_comment(text)

    def action():
        sub = _live_sub(sub_id)
        now = now_ny_naive()
        sub.update_dt = now
        _history("sub", sub.sub_id, sub.medline_item, "comment", actor, now, comment=comment)
        return sub

    return _run(action)


# --- vendor items (Materials Manager, Sub Finder) ----------------------------------------------

def _open_orders_of(item: VendorItem) -> int:
    return db.session.execute(
        select(func.count()).select_from(SubOrder).where(SubOrder.vendor_item_id == item.vendor_item_id,
                                                         SubOrder.voided_at.is_(None))
    ).scalar()


def add_vendor_item(sub_id: int | None, data: dict, actor: str, *, medline_item: str | None = None) -> VendorItem:
    """A way to order the sub (2026-10-20): a vendor's part in a UOM, with Infor's vendor ID (or
    0000000). Any sub can have them, whatever its status, as many as there are ways to order it,
    but never the Medline item itself from Medline. The UOM is Infor's (CS is saved as CA), and so is
    the vendor name for an Infor vendor ID (2026-10-21).

    With no ``sub_id``, it's for ``medline_item`` itself, as SCM directs when no sub nursing approved
    is available (2026-11-02, the user): e.g. the same item from another vendor."""
    clean = rules.check_new_vendor_item(data, uoms=uom_aliases())
    if sub_id is None:
        medline_item = rules.clean_field("medline_item", medline_item, required=True)

    def action():
        sub = _live_sub(sub_id) if sub_id is not None else None
        item_for = sub.medline_item if sub else medline_item
        rules.check_not_the_killed_item(item_for, clean)
        _ensure_unique_vendor_item(sub, item_for, clean)
        clean["vendor"] = _infor_name(_check_vendor_id(clean["vendor_id"])) or clean["vendor"]
        now = now_ny_naive()
        item = VendorItem(sub_id=sub.sub_id if sub else None, medline_item=None if sub else item_for, **clean,
                          entered_by=actor, create_dt=now, update_dt=now)
        db.session.add(item)
        db.session.flush()
        if sub:
            sub.update_dt = now
        _history("vendoritem", item.vendor_item_id, item_for, "created", actor, now)
        return item

    return _run(action)


def edit_vendor_item(vendor_item_id: int, data: dict, actor: str) -> VendorItem:
    """Corrects a vendor item, any time; its orders keep what they were placed with. It can't be
    made the Medline item itself from Medline."""
    uoms = uom_aliases()

    def action():
        item, sub = _live_vendor_item(vendor_item_id)
        changes = rules.check_vendor_item_changes(item, data, uoms=uoms)
        if changes.keys() & {"vendor_id", "vendor_part"}:
            rules.check_not_the_killed_item(item.item_for, {name: changes.get(name, getattr(item, name))
                                                            for name in ("vendor_id", "vendor_part")})
        if changes.keys() & {"vendor_id", "vendor_part", "uom"}:
            _ensure_unique_vendor_item(sub, item.item_for, {name: changes.get(name, getattr(item, name))
                                                            for name in ("vendor_id", "vendor_part", "uom")},
                                       except_id=item.vendor_item_id)
        _vendor_follows_id(item, changes)
        now = now_ny_naive()
        for name, value in changes.items():
            _history("vendoritem", item.vendor_item_id, item.item_for, "edit", actor, now,
                     field=name, from_value=getattr(item, name), to_value=value)
            setattr(item, name, value)
        item.update_dt = now
        if sub:
            sub.update_dt = now
        return item

    return _run(action)


def delete_vendor_item(vendor_item_id: int, reason, actor: str) -> VendorItem:
    """Takes a vendor item off its sub (or its Medline item), with a reason; its row and history
    stay. Refused while it has orders that aren't voided."""
    def action():
        item, sub = _live_vendor_item(vendor_item_id)
        why = rules.clean_comment(reason, label="Reason")
        orders = _open_orders_of(item)
        if orders:
            raise RuleError(f"Vendor item {item.label()} has {orders} order{'s' if orders > 1 else ''}; "
                            "void {} before deleting it.".format("them" if orders > 1 else "it"), 409)
        now = now_ny_naive()
        item.deleted_at, item.deleted_by, item.delete_reason = now, actor, why
        item.update_dt = now
        if sub:
            sub.update_dt = now
        _history("vendoritem", item.vendor_item_id, item.item_for, "delete", actor, now, comment=why)
        return item

    return _run(action)


# --- orders (Materials Manager) -------------------------------------------------------

def record_order(vendor_item_id: int, data: dict, actor: str, *, expected_status: str | None = None) -> SubOrder:
    """An order for a vendor item of an approved sub (2026-10-20), or for one without a sub, as SCM
    directs (2026-11-02), for the site the Materials Manager chose, with Infor's PO number if they
    gave it (2026-10-27). It keeps the vendor item's vendor part, vendor, vendor ID, UOM and QOE."""
    sites = site_codes()

    def action():
        item, sub = _live_vendor_item(vendor_item_id)
        if sub:
            _ensure_current(sub, expected_status)
        now = now_ny_naive()
        clean = rules.check_new_order(sub, item, data, now=now, sites=sites)
        order = SubOrder(
            sub_id=sub.sub_id if sub else None, vendor_item_id=item.vendor_item_id, medline_item=item.item_for,
            site=clean["site"], po_number=clean["po_number"], quantity=clean["quantity"], vendor_part=clean["vendor_part"], uom=clean["uom"], qoe=clean["qoe"],
            vendor=clean["vendor"], vendor_id=clean["vendor_id"], ordered_by=actor,
            ordered_dt=clean["ordered_dt"] or now, create_dt=now, update_dt=now,
        )
        db.session.add(order)
        db.session.flush()
        _history("order", order.order_id, order.medline_item, "created", actor, now)
        if clean["comment"]:
            _history("order", order.order_id, order.medline_item, "comment", actor, now,
                     comment=clean["comment"])
        return order

    return _run(action)


def edit_order(order_id: int, data: dict, actor: str) -> SubOrder:
    uoms = uom_aliases()
    sites = site_codes()

    def action():
        order = _locked(SubOrder, order_id)
        now = now_ny_naive()
        changes = rules.check_order_edit(order, data, now=now, uoms=uoms, sites=sites)
        _vendor_follows_id(order, changes)
        for name, value in changes.items():
            _history("order", order.order_id, order.medline_item, "edit", actor, now,
                     field=name, from_value=getattr(order, name), to_value=value)
            setattr(order, name, value)
        order.update_dt = now
        return order

    return _run(action)


def void_order(order_id: int, reason, actor: str) -> SubOrder:
    def action():
        order = _locked(SubOrder, order_id)
        why = rules.check_void(order, reason)
        now = now_ny_naive()
        order.voided_by, order.voided_at, order.void_reason = actor, now, why
        order.update_dt = now
        _history("order", order.order_id, order.medline_item, "void", actor, now, comment=why)
        return order

    return _run(action)


def comment_on_order(order_id: int, text, actor: str) -> SubOrder:
    comment = rules.clean_comment(text)

    def action():
        order = _locked(SubOrder, order_id)
        now = now_ny_naive()
        order.update_dt = now
        _history("order", order.order_id, order.medline_item, "comment", actor, now, comment=comment)
        return order

    return _run(action)


# --- instructions (SCM) -------------------------------------------------------------------

def add_instruction(medline_item: str, text, actor: str) -> ItemInstruction:
    """An SCM instruction to the sites on how to order an item (2026-10-27). It belongs to the
    Infor item of ``medline_item``, the main table's row (to the Medline item when Infor has none).
    Instructions are never changed: a new one replaces the last as the one in force."""
    instruction = rules.clean_instruction(text)
    infor_item = queries.infor_items_of([medline_item]).get(medline_item)

    def action():
        row = ItemInstruction(infor_item=infor_item, medline_item=medline_item, instruction=instruction,
                              written_by=actor, written_at=now_ny_naive())
        db.session.add(row)
        db.session.flush()
        return row

    return _run(action)


# --- reset (development server only) ----------------------------------------------------------

RESET_TABLES = (ItemInstruction, History, SubOrder, VendorItem, Sub)  # each before what it points at


def reset_workflow(actor: str) -> dict:
    """Empty the Fill/Kill workflow, as db/fillkill/90_reset_workflow.sql does (2026-11-02, the user):
    every SCM instruction, history row, order, vendor item and sub. The kill lines are Medline's and
    stay. Only the development server offers it (routes.api_reset). Returns the rows deleted per table."""
    def action():
        return {model.__tablename__: db.session.execute(delete(model)).rowcount for model in RESET_TABLES}

    deleted = _run(action)
    log.warning("Fill/Kill workflow reset by %s: %s", actor, deleted)
    _renumber()
    return deleted


def _renumber() -> None:
    """On SQL Server, new rows number from 1 again, as after 90 (a table that never had rows already
    does). Needs ALTER on the tables: without it the numbers just carry on."""
    if not db.engine.url.get_backend_name().startswith("mssql"):
        return  # SQLite numbers from the highest id left: from 1 in an empty table
    for model in RESET_TABLES:
        name = f"[{model.__table__.schema}].[{model.__tablename__}]"
        try:
            db.session.execute(text(
                f"IF (SELECT [last_value] FROM sys.identity_columns WHERE [object_id] = OBJECT_ID(N'{name}')) IS NOT NULL "
                f"DBCC CHECKIDENT ('{name}', RESEED, 0) WITH NO_INFOMSGS"))
            _commit()
        except SQLAlchemyError:
            log.exception("Fill/Kill reset: couldn't renumber %s", name)
