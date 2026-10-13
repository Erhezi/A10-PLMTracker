"""Every Fill/Kill write (plan v2 §5.3): one transaction per action, with its History rows.

Callers check the user's role first (routes, via ``access.require_module``);
these functions check the rules and record who did what. On a ``RuleError``
nothing is written.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from .. import db
from ..models import now_ny_naive
from ..models.fillkill import History, Sub, SubOrder
from . import rules
from .rules import RuleError


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
        noun = "sub" if model is Sub else "order"
        raise RuleError(f"That {noun} no longer exists; reload the page.", 404)
    return row


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


def _ensure_unique(medline_item: str, vendor: str, vendor_part: str, *, except_id: int | None = None) -> None:
    query = select(Sub).where(
        Sub.medline_item == medline_item,
        func.lower(Sub.vendor) == vendor.lower(),
        func.lower(Sub.vendor_part) == vendor_part.lower(),
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


# --- subs (Sub Finder) ---------------------------------------------------------------

def add_sub(data: dict, actor: str, *, source: str = "manual") -> Sub:
    clean = rules.check_new_sub(data)

    def action():
        _ensure_unique(clean["medline_item"], clean["vendor"], clean["vendor_part"])
        now = now_ny_naive()
        sub = Sub(
            medline_item=clean["medline_item"], vendor=clean["vendor"], vendor_part=clean["vendor_part"],
            description=clean["description"], uom=clean["uom"], qoe=clean["qoe"],
            status="pending_review", is_picked=False, source=source, entered_by=actor,
            create_dt=now, update_dt=now,
        )
        db.session.add(sub)
        db.session.flush()
        _history("sub", sub.sub_id, sub.medline_item, "created", actor, now)
        if clean["comment"]:
            _history("sub", sub.sub_id, sub.medline_item, "comment", actor, now, comment=clean["comment"])
        return sub

    return _run(action)


def edit_sub(sub_id: int, data: dict, actor: str) -> Sub:
    def action():
        sub = _locked(Sub, sub_id)
        changes = rules.check_sub_edit(sub, data)
        if "vendor" in changes or "vendor_part" in changes:
            _ensure_unique(sub.medline_item, changes.get("vendor", sub.vendor),
                           changes.get("vendor_part", sub.vendor_part), except_id=sub.sub_id)
        now = now_ny_naive()
        for name, value in changes.items():
            _history("sub", sub.sub_id, sub.medline_item, "edit", actor, now,
                     field=name, from_value=getattr(sub, name), to_value=value)
            setattr(sub, name, value)
        sub.update_dt = now
        return sub

    return _run(action)


# --- subs (Sub Approver) -------------------------------------------------------------

def set_status(sub_id: int, new_status: str, actor: str, *, expected_status: str | None = None) -> Sub:
    """S1, S2: leaving 'approved' unpicks the sub, recorded as its own History row."""
    def action():
        sub = _locked(Sub, sub_id)
        _ensure_current(sub, expected_status)
        status = rules.check_status_change(sub, new_status)
        now = now_ny_naive()
        _history("sub", sub.sub_id, sub.medline_item, "status", actor, now,
                 field="status", from_value=sub.status, to_value=status)
        if sub.is_picked and status != "approved":
            sub.is_picked = False
            _history("sub", sub.sub_id, sub.medline_item, "unpick", actor, now,
                     comment="Unpicked automatically: no longer approved.")
        sub.status = status
        sub.update_dt = now
        return sub

    return _run(action)


def pick(sub_id: int, actor: str, *, expected_status: str | None = None) -> Sub:
    def action():
        sub = _locked(Sub, sub_id)
        _ensure_current(sub, expected_status)
        rules.check_pick(sub)
        now = now_ny_naive()
        sub.is_picked = True
        sub.update_dt = now
        _history("sub", sub.sub_id, sub.medline_item, "pick", actor, now)
        return sub

    return _run(action)


def unpick(sub_id: int, actor: str, *, expected_status: str | None = None) -> Sub:
    def action():
        sub = _locked(Sub, sub_id)
        _ensure_current(sub, expected_status)
        rules.check_unpick(sub)
        now = now_ny_naive()
        sub.is_picked = False
        sub.update_dt = now
        _history("sub", sub.sub_id, sub.medline_item, "unpick", actor, now)
        return sub

    return _run(action)


def comment_on_sub(sub_id: int, text, actor: str) -> Sub:
    comment = rules.clean_comment(text)

    def action():
        sub = _locked(Sub, sub_id)
        now = now_ny_naive()
        sub.update_dt = now
        _history("sub", sub.sub_id, sub.medline_item, "comment", actor, now, comment=comment)
        return sub

    return _run(action)


# --- orders (Materials Manager) -------------------------------------------------------

def record_order(sub_id: int, data: dict, actor: str, *, expected_status: str | None = None) -> SubOrder:
    def action():
        sub = _locked(Sub, sub_id)
        _ensure_current(sub, expected_status)
        now = now_ny_naive()
        clean = rules.check_new_order(sub, data, now=now)
        order = SubOrder(
            sub_id=sub.sub_id, medline_item=sub.medline_item, quantity=clean["quantity"],
            uom=clean["uom"], qoe=clean["qoe"], vendor=clean["vendor"], ordered_by=actor,
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
    def action():
        order = _locked(SubOrder, order_id)
        now = now_ny_naive()
        changes = rules.check_order_edit(order, data, now=now)
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
