"""Checks for every Fill/Kill action (plan v2 §2, §5.3). Pure: no database, no Flask.

Each ``clean_*`` / ``check_*`` function returns cleaned values or raises
``RuleError``; ``services`` calls them before writing anything.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ..models.fillkill import INSTRUCTION_MAX, REASON_MAX, SUB_STATUSES, TEXT_MAX

# What a Sub Approver can set; pending_review is only where a sub starts (S1).
REVIEW_STATUSES = ("approved", "hold", "rejected")
STATUS_LABELS = {
    "pending_review": "Pending Review",
    "approved": "Approved",
    "hold": "Hold",
    "rejected": "Rejected",
}

# Who fills in what (2026-10-20): nursing (or a Sub Finder) enters a sub's Reference SKU, the part
# they approved, often the manufacturer's; the Materials Manager or a Sub Finder adds its vendor
# items, each a vendor's part in a UOM that can be ordered. With no sub nursing approved, SCM or a
# Materials Manager can add one for the Medline item itself, as SCM directs (2026-11-02).
VENDOR_ITEM_FIELDS = ("vendor_part", "vendor", "vendor_id", "manufacturer_part", "infor_item", "description", "uom", "qoe")
VENDOR_ITEM_REQUIRED = ("vendor_part", "vendor", "vendor_id", "uom")
ORDER_FIELDS = ("site", "po_number", "quantity", "vendor_part", "uom", "qoe", "vendor", "vendor_id", "ordered_dt")

LIMITS = {"medline_item": 50, "reference_sku": 100, "vendor": 255, "vendor_id": 20, "vendor_part": 100,
          "manufacturer_part": 100, "infor_item": 50, "description": 255, "uom": 10, "site": 20, "po_number": 20}
LABELS = {"medline_item": "Medline item", "reference_sku": "Reference SKU", "vendor_id": "Vendor ID", "uom": "UOM",
          "qoe": "QOE", "po_number": "PO number"}

# A vendor item needs Infor's vendor ID (2026-10-19). When Infor has no such vendor, the Materials
# Manager says so on purpose with this one; Infor has no vendor 0000000.
NO_VENDOR_ID = "0000000"
NO_VENDOR_LABEL = "Vendor not available in system"

# What Main, its panel and the help page call SCM's instructions: named for the role that writes
# them (the user, 2026-11-02; "Will's Comments" from 2026-10-27, "MM Instruction" before).
INSTRUCTION_LABEL = "SCM Comments"

# Medline's vendor IDs in Infor (2026-10-20): MEDLINE INDUSTRIES INC, its physician office (LUM) and
# decasing (custom packs) accounts, and its JIT tote program. A vendor item from one of them whose
# vendor part is the Medline item itself is the item that was killed, not a sub.
MEDLINE_VENDOR_IDS = ("1000931", "1017968", "1017969", "1037888")


class RuleError(Exception):
    """An action that isn't allowed. ``status`` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# --- values --------------------------------------------------------------------

def label(name: str) -> str:
    return LABELS.get(name) or name.replace("_", " ").capitalize()


def clean_text(value, *, label: str, max_len: int, required: bool = False) -> str | None:
    text = (str(value).strip() if value is not None else "")
    if not text:
        if required:
            raise RuleError(f"{label} is required.")
        return None
    if len(text) > max_len:
        raise RuleError(f"{label} is longer than {max_len} characters.")
    return text


def clean_field(name: str, value, *, required: bool = False, uoms: dict | None = None):
    """A sub, vendor item or order field by name; uom is upper-cased and made Infor's (``uoms``),
    the vendor ID is Infor's, qoe and quantity are numbers."""
    if name == "qoe":
        return clean_qoe(value)
    if name == "quantity":
        return clean_quantity(value)
    if name == "ordered_dt":
        return clean_ordered_dt(value)
    if name == "po_number":
        return clean_po_number(value)
    if name == "vendor_id":
        text = clean_vendor_id(value)
        if text is None and required:
            raise RuleError(_missing_message(["Vendor ID"]))
        return text
    text = clean_text(value, label=label(name), max_len=LIMITS[name], required=required)
    return infor_uom(text, uoms) if (text and name == "uom") else text


def infor_uom(uom: str, uoms: dict | None = None) -> str:
    """The UOM upper-cased, and Infor's when it's typed another way (2026-10-20): ``uoms`` maps
    MDM_EDI_SUB_UOM's external values to Infor's (Lawson's), e.g. CS to CA, VL to VI. One it doesn't
    list stays as typed."""
    uom = uom.upper()
    return (uoms or {}).get(uom, uom)


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


def clean_po_number(value) -> str | None:
    """Infor's PO number (2026-10-27), optional: digits only (company 3000's are 10, e.g.
    3000564756). Kept to link the order back to the killed items later; not checked against Infor."""
    text = clean_text(value, label="PO number", max_len=LIMITS["po_number"])
    if text is not None and not text.isdigit():
        raise RuleError("PO number must be Infor's PO number, digits only (like 3000564756), or left empty.")
    return text


def clean_site(value, sites, *, required: bool = True) -> str | None:
    """The site an order is for (2026-10-27): one of Medline's Sold-To codes in ``sites``. The
    Materials Manager chooses it; each site orders for itself."""
    text = clean_text(value, label="Site", max_len=LIMITS["site"])
    if text is None:
        if required:
            raise RuleError("Choose the site this order is for.")
        return None
    if text not in set(sites):
        raise RuleError(f"{text} isn't one of the sites in the fill/kill data.")
    return text


def _missing_message(missing: list[str]) -> str:
    labels = [f"{name} (or {NO_VENDOR_ID}: {NO_VENDOR_LABEL})" if name == "Vendor ID" else name for name in missing]
    names = ", ".join(labels[:-1]) + (" and " if len(labels) > 1 else "") + labels[-1]
    return f"{names} {'are' if len(labels) > 1 else 'is'} required."


def _same(name: str, value, current) -> bool:
    if name == "qoe":
        return (value is None and current is None) or (
            value is not None and current is not None and Decimal(current) == value
        )
    return (value or None) == (current or None)


def clean_comment(value, *, label: str = "Comment") -> str:
    return clean_text(value, label=label, max_len=TEXT_MAX, required=True)


def clean_instruction(value) -> str:
    """An SCM instruction to the sites (2026-10-27): longer than a comment, since it may speak
    to every site."""
    return clean_text(value, label="Instruction", max_len=INSTRUCTION_MAX, required=True)


# --- subs ----------------------------------------------------------------------

def check_new_sub(data: dict) -> dict:
    """A new sub: its Reference SKU (2026-10-20) and, if they like, a first comment. What can be
    ordered for it, its vendor items, is the Materials Manager's or a Sub Finder's."""
    return {
        "medline_item": clean_field("medline_item", data.get("medline_item"), required=True),
        "reference_sku": clean_field("reference_sku", data.get("reference_sku"), required=True),
        "comment": clean_text(data.get("comment"), label="Comment", max_len=TEXT_MAX),
    }


def check_status_change(sub, new_status) -> str:
    if new_status not in REVIEW_STATUSES:
        choices = ", ".join(STATUS_LABELS[s] for s in REVIEW_STATUSES)
        raise RuleError(f"Status must be one of: {choices}.")
    if new_status == sub.status:
        raise RuleError(f"The sub is already {STATUS_LABELS[new_status]}.")
    return new_status


def clean_status_reason(value) -> str | None:
    """Why a sub was put on hold or rejected (2026-10-28), if nursing says: optional. It's kept as
    the sub's comment after its new status ("Hold: ..."), so it leaves room for that."""
    return clean_text(value, label="Reason", max_len=REASON_MAX)


def check_delete(sub, reason) -> str:
    """A sub is deleted with a reason (orders voided first: the service checks)."""
    return clean_comment(reason, label="Reason")


# --- vendor items --------------------------------------------------------------

def check_new_vendor_item(data: dict, *, uoms: dict | None = None) -> dict:
    """A vendor item (2026-10-20): its vendor part, vendor, Infor's vendor ID (or 0000000) and UOM
    are required; its manufacturer part, Infor item, description and QOE are optional."""
    clean = {name: clean_field(name, data.get(name), uoms=uoms) for name in VENDOR_ITEM_FIELDS}
    missing = [label(name) for name in VENDOR_ITEM_REQUIRED if not clean[name]]
    if missing:
        raise RuleError(_missing_message(missing))
    return clean


def is_the_killed_item(medline_item: str, vendor_part, vendor_id) -> bool:
    """Whether a vendor item is the Medline item itself (2026-10-20): Medline's own part number
    under one of Medline's vendor IDs, so the sub would point back at the item that was killed."""
    return (vendor_id in MEDLINE_VENDOR_IDS and bool(vendor_part)
            and str(vendor_part).strip().upper() == str(medline_item).strip().upper())


def check_not_the_killed_item(medline_item: str, values: dict) -> None:
    if is_the_killed_item(medline_item, values.get("vendor_part"), values.get("vendor_id")):
        raise RuleError(
            f"{values['vendor_part']} from Medline (vendor ID {values['vendor_id']}) is {medline_item} itself, "
            "the Medline item that was killed, so it can't be ordered as its sub. Add another vendor's part "
            "or another product instead."
        )


def check_vendor_item_changes(item, data: dict, *, uoms: dict | None = None) -> dict:
    """The fields in ``data`` that differ from the vendor item's, cleaned; a required one can't be
    emptied, and nothing to change is refused."""
    changes = {}
    for name in VENDOR_ITEM_FIELDS:
        if name not in data:
            continue
        value = clean_field(name, data[name], required=name in VENDOR_ITEM_REQUIRED, uoms=uoms)
        if not _same(name, value, getattr(item, name)):
            changes[name] = value
    if not changes:
        raise RuleError("Nothing to change.")
    return changes


# --- orders --------------------------------------------------------------------

def check_orderable(sub) -> None:
    """Every sub nursing approved can be ordered (the user, 2026-10-28: picking among them is gone);
    one on hold or rejected can't."""
    if sub.status != "approved":
        state = {"hold": "on hold", "rejected": "rejected"}.get(sub.status, "pending review")
        raise RuleError(f"Only an approved sub can be ordered, and {sub.label()} is {state}.", 409)


def check_new_order(sub, item, data: dict, *, now: datetime | None = None, sites=()) -> dict:
    """An order for a vendor item of an approved sub (S3; 2026-10-20, a picked one until 2026-10-28),
    or of no sub (``sub`` None: as SCM directs, 2026-11-02), for one of ``sites`` (2026-10-27),
    with Infor's PO number if given. It keeps the vendor item's vendor part, vendor, vendor ID, UOM
    and QOE."""
    if sub is not None:
        check_orderable(sub)
    return {
        "site": clean_site(data.get("site"), sites),
        "po_number": clean_po_number(data.get("po_number")),
        "quantity": clean_quantity(data.get("quantity")),
        "vendor_part": item.vendor_part,
        "uom": item.uom,
        "qoe": Decimal(item.qoe) if item.qoe is not None else None,
        "vendor": item.vendor,
        "vendor_id": item.vendor_id,
        "ordered_dt": clean_ordered_dt(data.get("ordered_dt"), now=now),
        "comment": clean_text(data.get("comment"), label="Comment", max_len=TEXT_MAX),
    }


def check_order_edit(order, data: dict, *, now: datetime | None = None, uoms: dict | None = None,
                     sites=()) -> dict:
    """Changed fields only; a voided order can't change (P3). An order from before sites (2026-10-27)
    can be given one; once it has a site, it keeps one."""
    if order.voided_at is not None:
        raise RuleError("A voided order can't be changed.", 409)
    changes = {}
    for name in ORDER_FIELDS:
        if name not in data:
            continue
        if name == "site":
            # Its own site stays allowed, should it leave the data (the test site at go-live).
            value = clean_site(data[name], {*sites, order.site} - {None}, required=order.site is not None)
        elif name == "ordered_dt":
            value = clean_ordered_dt(data[name], now=now)
            if value is None:
                raise RuleError("Ordered date is required.")
        else:
            value = clean_field(name, data[name], required=name in ("quantity", "vendor_part", "uom", "vendor", "vendor_id"),
                                uoms=uoms)
        current = getattr(order, name)
        if not (_same(name, value, current) if name == "qoe" else value == current):
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
