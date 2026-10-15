"""Checks for every Fill/Kill action (plan v2 §2, §5.3). Pure: no database, no Flask.

Each ``clean_*`` / ``check_*`` function returns cleaned values or raises
``RuleError``; ``services`` calls them before writing anything.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ..models.fillkill import SUB_STATUSES, TEXT_MAX

# What a Sub Approver can set; pending_review is only where a sub starts (S1).
REVIEW_STATUSES = ("approved", "hold", "rejected")
STATUS_LABELS = {
    "pending_review": "Pending Review",
    "approved": "Approved",
    "hold": "Hold",
    "rejected": "Rejected",
}

# Fields a Sub Finder can correct, before and after the first review (P2).
SUB_FIELDS_BEFORE_REVIEW = ("vendor", "vendor_part", "description", "uom", "qoe")
SUB_FIELDS_AFTER_REVIEW = ("description", "uom", "qoe")
ORDER_FIELDS = ("quantity", "uom", "qoe", "vendor", "ordered_dt")

LIMITS = {"medline_item": 50, "vendor": 255, "vendor_id": 20, "vendor_part": 100, "description": 255, "uom": 10}


class RuleError(Exception):
    """An action that isn't allowed. ``status`` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# --- values --------------------------------------------------------------------

def clean_text(value, *, label: str, max_len: int, required: bool = False) -> str | None:
    text = (str(value).strip() if value is not None else "")
    if not text:
        if required:
            raise RuleError(f"{label} is required.")
        return None
    if len(text) > max_len:
        raise RuleError(f"{label} is longer than {max_len} characters.")
    return text


def clean_field(name: str, value, *, required: bool = False):
    """A sub or order field by name; uom is upper-cased, qoe and quantity are numbers."""
    if name == "qoe":
        return clean_qoe(value)
    if name == "quantity":
        return clean_quantity(value)
    if name == "ordered_dt":
        return clean_ordered_dt(value)
    label = name.replace("_", " ").capitalize()
    text = clean_text(value, label=label, max_len=LIMITS[name], required=required)
    return text.upper() if (text and name == "uom") else text


def clean_qoe(value) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        qoe = Decimal(str(value).strip())
    except InvalidOperation:
        raise RuleError("QOE must be a number.") from None
    if not qoe.is_finite() or qoe <= 0:
        raise RuleError("QOE must be more than 0.")
    if qoe >= Decimal("100000000"):
        raise RuleError("QOE is too large.")
    return qoe.quantize(Decimal("0.0001"))


def clean_quantity(value) -> int:
    try:
        quantity = int(str(value).strip())
    except (TypeError, ValueError):
        raise RuleError("Quantity must be a whole number.") from None
    if quantity <= 0:
        raise RuleError("Quantity must be more than 0.")
    return quantity


def clean_ordered_dt(value, *, now: datetime | None = None) -> datetime | None:
    """ISO date or date-time; None means "now". A future date isn't allowed."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise RuleError("Ordered date must look like 2026-10-13 or 2026-10-13T14:30.") from None
    parsed = parsed.replace(tzinfo=None)
    today = (now or datetime.now()).date()
    if parsed.date() > today:
        raise RuleError("Ordered date can't be in the future.")
    return parsed


def clean_vendor_id(value) -> str:
    """A sub's vendor: Infor's vendor ID, digits only (e.g. 1000931). Its name comes from Infor."""
    text = clean_text(value, label="Vendor ID", max_len=LIMITS["vendor_id"], required=True)
    if not text.isdigit():
        raise RuleError("Vendor must be Infor's vendor ID (digits, like 1000931), not the vendor's name.")
    return text


def clean_comment(value, *, label: str = "Comment") -> str:
    return clean_text(value, label=label, max_len=TEXT_MAX, required=True)


# --- subs ----------------------------------------------------------------------

def check_new_sub(data: dict) -> dict:
    """A sub a Sub Finder adds: vendor (Infor's vendor ID) and vendor part required; an optional
    first comment."""
    return {
        "medline_item": clean_field("medline_item", data.get("medline_item"), required=True),
        "vendor": clean_vendor_id(data.get("vendor")),
        "vendor_part": clean_field("vendor_part", data.get("vendor_part"), required=True),
        "description": clean_field("description", data.get("description")),
        "uom": clean_field("uom", data.get("uom")),
        "qoe": clean_qoe(data.get("qoe")),
        "comment": clean_text(data.get("comment"), label="Comment", max_len=TEXT_MAX),
    }


def check_sub_edit(sub, data: dict) -> dict:
    """Changed fields only. Vendor and vendor part are fixed after the first review (P2)."""
    allowed = SUB_FIELDS_BEFORE_REVIEW if sub.status == "pending_review" else SUB_FIELDS_AFTER_REVIEW
    asked = [name for name in SUB_FIELDS_BEFORE_REVIEW if name in data]
    locked = [name for name in asked if name not in allowed]
    if locked:
        raise RuleError(
            "Vendor and vendor part can't change after the sub has been reviewed. "
            "Reject it and add the right one instead."
        )
    changes = {}
    for name in asked:
        if name == "vendor":
            value = clean_vendor_id(data[name])
        else:
            value = clean_field(name, data[name], required=name == "vendor_part")
        current = getattr(sub, name)
        if name == "qoe":
            same = (value is None and current is None) or (
                value is not None and current is not None and Decimal(current) == value
            )
        else:
            same = (value or None) == (current or None)
        if not same:
            changes[name] = value
    if not changes:
        raise RuleError("Nothing to change.")
    return changes


def check_status_change(sub, new_status) -> str:
    if new_status not in REVIEW_STATUSES:
        choices = ", ".join(STATUS_LABELS[s] for s in REVIEW_STATUSES)
        raise RuleError(f"Status must be one of: {choices}.")
    if new_status == sub.status:
        raise RuleError(f"The sub is already {STATUS_LABELS[new_status]}.")
    return new_status


def check_pick(sub) -> None:
    if sub.status != "approved":
        raise RuleError("Only an approved sub can be picked.")
    if sub.is_picked:
        raise RuleError("The sub is already picked.", 409)


def check_unpick(sub) -> None:
    if not sub.is_picked:
        raise RuleError("The sub isn't picked.", 409)


# --- orders --------------------------------------------------------------------

def check_new_order(sub, data: dict, *, now: datetime | None = None) -> dict:
    """An order against a picked sub (S3). UOM, QOE and vendor default to the sub's (the order's
    vendor is free text: the sub's vendor name unless changed)."""
    if not sub.is_picked:
        raise RuleError("Orders are recorded against a picked sub, and this one isn't picked.", 409)
    uom = clean_field("uom", data.get("uom")) or sub.uom
    if not uom:
        raise RuleError("UOM is required.")
    qoe = clean_qoe(data["qoe"]) if "qoe" in data else (Decimal(sub.qoe) if sub.qoe is not None else None)
    return {
        "quantity": clean_quantity(data.get("quantity")),
        "uom": uom,
        "qoe": qoe,
        "vendor": clean_field("vendor", data.get("vendor")) or getattr(sub, "vendor_name", None) or sub.vendor,
        "ordered_dt": clean_ordered_dt(data.get("ordered_dt"), now=now),
        "comment": clean_text(data.get("comment"), label="Comment", max_len=TEXT_MAX),
    }


def check_order_edit(order, data: dict, *, now: datetime | None = None) -> dict:
    """Changed fields only; a voided order can't change (P3)."""
    if order.voided_at is not None:
        raise RuleError("A voided order can't be changed.", 409)
    changes = {}
    for name in ORDER_FIELDS:
        if name not in data:
            continue
        if name == "ordered_dt":
            value = clean_ordered_dt(data[name], now=now)
            if value is None:
                raise RuleError("Ordered date is required.")
        else:
            value = clean_field(name, data[name], required=name in ("quantity", "uom", "vendor"))
        current = getattr(order, name)
        if name == "qoe":
            same = (value is None and current is None) or (
                value is not None and current is not None and Decimal(current) == value
            )
        else:
            same = value == current
        if not same:
            changes[name] = value
    if not changes:
        raise RuleError("Nothing to change.")
    return changes


def check_void(order, reason) -> str:
    if order.voided_at is not None:
        raise RuleError("The order is already voided.", 409)
    return clean_comment(reason, label="Reason")


def display(value) -> str | None:
    """How a value is written into History's from/to columns."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
        return text
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


assert set(REVIEW_STATUSES) < set(SUB_STATUSES)
