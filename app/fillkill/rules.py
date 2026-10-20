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

# Who fills in what on a sub (2026-10-15): nursing enters the part they approved; the Materials
# Manager fills in the vendor details, the vendor part ordered among them (2026-10-19: what nursing
# entered may be the manufacturer's part, or another vendor's).
SUB_DETAIL_FIELDS = ("vendor_part", "vendor", "vendor_id", "manufacturer_part", "infor_item", "description", "uom", "qoe")
ORDER_FIELDS = ("quantity", "uom", "qoe", "vendor", "vendor_id", "ordered_dt")

LIMITS = {"medline_item": 50, "vendor": 255, "vendor_id": 20, "vendor_part": 100, "manufacturer_part": 100,
          "infor_item": 50, "description": 255, "uom": 10}

# A sub's vendor details need Infor's vendor ID (2026-10-19). When Infor has no such vendor, the
# Materials Manager says so on purpose with this one; Infor has no vendor 0000000.
NO_VENDOR_ID = "0000000"
NO_VENDOR_LABEL = "Vendor not available in system"


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


def clean_vendor_id(value) -> str | None:
    """Infor's vendor ID: digits only (e.g. 1000931), or 0000000 when Infor has no such vendor."""
    text = clean_text(value, label="Vendor ID", max_len=LIMITS["vendor_id"])
    if text is not None and not text.isdigit():
        raise RuleError(f"Vendor ID must be Infor's vendor ID (digits, like 1000931), or {NO_VENDOR_ID} "
                        f"({NO_VENDOR_LABEL}).")
    return text


def details_missing(sub) -> list[str]:
    """What a sub still lacks for an order: its vendor, Infor's vendor ID (or 0000000) and its UOM.
    ``sub`` is a Sub or a dict with those keys."""
    get = sub.get if isinstance(sub, dict) else lambda name: getattr(sub, name)
    return [label for name, label in (("vendor", "Vendor"), ("vendor_id", "Vendor ID"), ("uom", "UOM"))
            if not get(name)]


def _missing_message(missing: list[str]) -> str:
    labels = [f"{name} (or {NO_VENDOR_ID}: {NO_VENDOR_LABEL})" if name == "Vendor ID" else name for name in missing]
    names = ", ".join(labels[:-1]) + (" and " if len(labels) > 1 else "") + labels[-1]
    return f"{names} {'are' if len(labels) > 1 else 'is'} required: fill in the sub's vendor details."


def check_details_complete(sub) -> None:
    """Saved vendor details always include the vendor, its vendor ID and the UOM (2026-10-19)."""
    missing = details_missing(sub)
    if missing:
        raise RuleError(_missing_message(missing))


def clean_comment(value, *, label: str = "Comment") -> str:
    return clean_text(value, label=label, max_len=TEXT_MAX, required=True)


# --- subs ----------------------------------------------------------------------

def check_new_sub(data: dict) -> dict:
    """A new sub: the vendor part is required. The vendor details (vendor, vendor ID, manufacturer
    part, Infor item, description, UOM, QOE) and a first comment are optional: the Materials Manager
    fills the details in."""
    return {
        "medline_item": clean_field("medline_item", data.get("medline_item"), required=True),
        "vendor": clean_field("vendor", data.get("vendor")),
        "vendor_id": clean_vendor_id(data.get("vendor_id")),
        "vendor_part": clean_field("vendor_part", data.get("vendor_part"), required=True),
        "manufacturer_part": clean_field("manufacturer_part", data.get("manufacturer_part")),
        "infor_item": clean_field("infor_item", data.get("infor_item")),
        "description": clean_field("description", data.get("description")),
        "uom": clean_field("uom", data.get("uom")),
        "qoe": clean_qoe(data.get("qoe")),
        "comment": clean_text(data.get("comment"), label="Comment", max_len=TEXT_MAX),
    }


def check_sub_changes(sub, data: dict, fields, *, required: bool = True) -> dict:
    """The fields of ``fields`` in ``data`` that differ from the sub's, cleaned. With ``required``,
    nothing to change is refused."""
    changes = {}
    for name in fields:
        if name not in data:
            continue
        if name == "vendor_id":
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
    if not changes and required:
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


def check_delete(sub, reason) -> str:
    """A sub is deleted with a reason. The Approver's Pick stays until it's unpicked."""
    if sub.is_picked:
        raise RuleError(f"{sub.label()} is the Approver's Pick; it has to be unpicked before it's deleted.", 409)
    return clean_comment(reason, label="Reason")


# --- orders --------------------------------------------------------------------

def check_orderable(sub) -> None:
    if not sub.is_picked:
        raise RuleError("Orders are recorded against a picked sub, and this one isn't picked.", 409)


def check_new_order(sub, data: dict, *, now: datetime | None = None) -> dict:
    """An order against a picked sub (S3). UOM, QOE and vendor default to the sub's details,
    which the Materials Manager fills in (with the order or before); the sub needs its vendor ID
    too (2026-10-19)."""
    check_orderable(sub)
    uom = clean_field("uom", data.get("uom")) or sub.uom
    vendor = clean_field("vendor", data.get("vendor")) or sub.vendor
    missing = details_missing({"vendor": vendor, "vendor_id": sub.vendor_id, "uom": uom})
    if missing:
        raise RuleError(_missing_message(missing))
    qoe = clean_qoe(data["qoe"]) if "qoe" in data else (Decimal(sub.qoe) if sub.qoe is not None else None)
    return {
        "quantity": clean_quantity(data.get("quantity")),
        "uom": uom,
        "qoe": qoe,
        "vendor": vendor,
        "vendor_id": sub.vendor_id,  # the order keeps it, as it keeps the vendor's name (2026-10-20)
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
        elif name == "vendor_id":
            value = clean_vendor_id(data[name])
            if value is None:
                raise RuleError(f"Vendor ID (or {NO_VENDOR_ID}: {NO_VENDOR_LABEL}) is required.")
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
