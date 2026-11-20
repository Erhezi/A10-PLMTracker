"""Fill/Kill workflow tables (schema FillKill): subs, their vendor items, orders, their history, and
SCM's instructions.

db/fillkill/12_workflow_tables.sql creates these tables. The constraints are
spelled out here with the same names, because the app's startup (db.create_all)
creates a table itself if it runs before that script; the script then only adds
the defaults. Views (kill lines, item and quantity views, contract search) are
read with SQL in app/fillkill/queries.py and never mapped, so create_all never
tries to create one.
"""

from __future__ import annotations

from .. import db
from . import now_ny_naive

SCHEMA = "FillKill"

SUB_STATUSES = ("pending_review", "approved", "hold", "rejected")
# Where a sub came from: entered by hand, one of Medline's lists (2026-11-19: AutoSub, the Fill/Kill
# file's Customer Preferred and Possible Subst. items, PBO; 14_pbo_sync.sql adds them), or an AI finder.
SUB_SOURCES = ("manual", "medline_autosub", "medline_preferred", "medline_possible", "medline_pbo", "llm")
# Who the sync of Medline's subs records as approving the AutoSub and Customer Preferred ones (14).
SYSTEM_ACTOR = "System"
HISTORY_ENTITIES = ("sub", "vendoritem", "order")
# pick and unpick: none written since 2026-10-28, when picking went; the table still allows them.
HISTORY_ACTIONS = ("created", "status", "pick", "unpick", "comment", "edit", "void", "delete")

TEXT_MAX = 400  # comments and void reasons
REASON_MAX = TEXT_MAX - 20  # a Hold or Reject reason, kept as a comment after "Rejected: " (2026-10-28)
INSTRUCTION_MAX = 1000  # an SCM instruction: it may speak to every site (2026-10-27)


def _one_of(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Sub(db.Model):
    """A sub of a Medline item: the Reference SKU a Sub Approver (nursing) or a Sub Finder entered,
    and its review status: every approved sub can be ordered (2026-10-28). What can be ordered for it,
    a vendor's part in a UOM, are its vendor items (VendorItem): the Materials Manager's or the Sub
    Finder's. A Reference SKU is often the manufacturer's part, which several vendors sell.

    A deleted sub keeps its row (who, when, why), so its history stays and the sync of Medline's
    subs doesn't add it back; it's hidden everywhere, and the same Reference SKU can be added again.
    """

    __tablename__ = "Sub"
    __table_args__ = (
        db.PrimaryKeyConstraint("sub_id", name="PK_Sub"),
        # One live sub per item and Reference SKU; deleted ones don't count.
        db.Index("UX_Sub_item_reference_sku", "medline_item", "reference_sku", unique=True,
                 mssql_where=db.text("deleted_at IS NULL"), sqlite_where=db.text("deleted_at IS NULL")),
        db.CheckConstraint(_one_of("status", SUB_STATUSES), name="CK_Sub_status"),
        db.CheckConstraint(_one_of("source", SUB_SOURCES), name="CK_Sub_source"),
        db.CheckConstraint("is_picked = 0 OR status = 'approved'", name="CK_Sub_pick_needs_approved"),
        db.CheckConstraint(
            "(deleted_at IS NULL AND deleted_by IS NULL AND delete_reason IS NULL) "
            "OR (deleted_at IS NOT NULL AND deleted_by IS NOT NULL AND delete_reason IS NOT NULL AND is_picked = 0)",
            name="CK_Sub_delete",
        ),
        {"schema": SCHEMA},
    )

    sub_id = db.Column(db.Integer, autoincrement=True)
    medline_item = db.Column(db.String(50), nullable=False)
    # As entered: nursing's approved reference, or Medline's sub item number. Often the manufacturer's part.
    reference_sku = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending_review")
    # Picked among the approved subs, 2026-10-20 to 10-28: always 0 since picking went (the table's
    # CHECKs still name it).
    is_picked = db.Column(db.Boolean, nullable=False, default=False)
    source = db.Column(db.String(20), nullable=False)
    entered_by = db.Column(db.String(255), nullable=False)
    create_dt = db.Column(db.DateTime, nullable=False, default=now_ny_naive)
    update_dt = db.Column(db.DateTime, nullable=False, default=now_ny_naive)
    deleted_at = db.Column(db.DateTime)
    deleted_by = db.Column(db.String(255))
    delete_reason = db.Column(db.String(TEXT_MAX))

    def label(self) -> str:
        return self.reference_sku


class VendorItem(db.Model):
    """What can be ordered for a sub (2026-10-20): a vendor's part in a UOM, with Infor's vendor ID
    (or 0000000 when Infor has no such vendor). The Materials Manager or a Sub Finder adds them; a
    sub has as many as there are ways to order it, one per vendor ID, vendor part and UOM.

    Or, with no sub, what SCM directs the sites to order for the Medline item when no sub nursing
    approved is available (2026-11-02, the user): e.g. the same item from another vendor, or a sub
    item nursing hasn't approved. It can be ordered as it is.

    A deleted one keeps its row (who, when, why) and its orders.
    """

    __tablename__ = "SubVendorItem"
    __table_args__ = (
        db.PrimaryKeyConstraint("vendor_item_id", name="PK_SubVendorItem"),
        db.ForeignKeyConstraint(["sub_id"], [f"{SCHEMA}.Sub.sub_id"], name="FK_SubVendorItem_Sub"),
        # One live vendor item per sub, vendor ID, vendor part and UOM; without a sub, per Medline item.
        db.Index("UX_SubVendorItem_vendor_part_uom", "sub_id", "vendor_id", "vendor_part", "uom", unique=True,
                 mssql_where=db.text("deleted_at IS NULL AND sub_id IS NOT NULL"),
                 sqlite_where=db.text("deleted_at IS NULL AND sub_id IS NOT NULL")),
        db.Index("UX_SubVendorItem_item_vendor_part_uom", "medline_item", "vendor_id", "vendor_part", "uom", unique=True,
                 mssql_where=db.text("deleted_at IS NULL AND sub_id IS NULL"),
                 sqlite_where=db.text("deleted_at IS NULL AND sub_id IS NULL")),
        db.CheckConstraint("qoe IS NULL OR qoe > 0", name="CK_SubVendorItem_qoe"),
        db.CheckConstraint(
            "(deleted_at IS NULL AND deleted_by IS NULL AND delete_reason IS NULL) "
            "OR (deleted_at IS NOT NULL AND deleted_by IS NOT NULL AND delete_reason IS NOT NULL)",
            name="CK_SubVendorItem_delete",
        ),
        # A sub's, or a Medline item's: never both, never neither.
        db.CheckConstraint(
            "(sub_id IS NOT NULL AND medline_item IS NULL) OR (sub_id IS NULL AND medline_item IS NOT NULL)",
            name="CK_SubVendorItem_sub_or_item",
        ),
        {"schema": SCHEMA},
    )

    vendor_item_id = db.Column(db.Integer, autoincrement=True)
    sub_id = db.Column(db.Integer)  # or none, and then its Medline item (2026-11-02)
    medline_item = db.Column(db.String(50))  # only without a sub: the Medline item it's for
    vendor_part = db.Column(db.String(100), nullable=False)  # the vendor's part number: the one ordered
    vendor = db.Column(db.String(255), nullable=False)       # the vendor's name
    vendor_id = db.Column(db.String(20), nullable=False)     # Infor's vendor ID (e.g. 1000931), or 0000000
    uom = db.Column(db.String(10), nullable=False)
    qoe = db.Column(db.Numeric(12, 4))
    manufacturer_part = db.Column(db.String(100))
    infor_item = db.Column(db.String(50))  # Infor's item number for it, when it has one
    description = db.Column(db.String(255))
    entered_by = db.Column(db.String(255), nullable=False)
    create_dt = db.Column(db.DateTime, nullable=False, default=now_ny_naive)
    update_dt = db.Column(db.DateTime, nullable=False, default=now_ny_naive)
    deleted_at = db.Column(db.DateTime)
    deleted_by = db.Column(db.String(255))
    delete_reason = db.Column(db.String(TEXT_MAX))

    sub = db.relationship(Sub, lazy="joined")

    @property
    def item_for(self) -> str:
        """The Medline item it's for: its sub's, or its own without a sub."""
        return self.sub.medline_item if self.sub_id is not None else self.medline_item

    def label(self) -> str:
        return f"{self.vendor_part} ({self.vendor}, {self.uom})"


class SubOrder(db.Model):
    """An order a Materials Manager recorded for a vendor item of an approved sub, or for a vendor item
    without a sub (2026-11-02), for a site. It keeps what it was placed with (vendor part, vendor,
    vendor ID, UOM, QOE), whatever happens to the vendor item."""

    __tablename__ = "SubOrder"
    __table_args__ = (
        db.PrimaryKeyConstraint("order_id", name="PK_SubOrder"),
        db.ForeignKeyConstraint(["sub_id"], [f"{SCHEMA}.Sub.sub_id"], name="FK_SubOrder_Sub"),
        db.ForeignKeyConstraint(["vendor_item_id"], [f"{SCHEMA}.SubVendorItem.vendor_item_id"],
                                name="FK_SubOrder_SubVendorItem"),
        # Without a sub, it's for a vendor item (one without a sub).
        db.CheckConstraint("sub_id IS NOT NULL OR vendor_item_id IS NOT NULL", name="CK_SubOrder_sub_or_vendor_item"),
        db.CheckConstraint("quantity > 0", name="CK_SubOrder_quantity"),
        db.CheckConstraint("qoe IS NULL OR qoe > 0", name="CK_SubOrder_qoe"),
        db.CheckConstraint(
            "(voided_at IS NULL AND voided_by IS NULL AND void_reason IS NULL)"
            " OR (voided_at IS NOT NULL AND voided_by IS NOT NULL AND void_reason IS NOT NULL)",
            name="CK_SubOrder_void",
        ),
        db.Index("IX_SubOrder_item_ordered", "medline_item", "ordered_dt"),
        db.Index("IX_SubOrder_sub", "sub_id"),
        db.Index("IX_SubOrder_vendor_item", "vendor_item_id"),
        {"schema": SCHEMA},
    )

    order_id = db.Column(db.Integer, autoincrement=True)
    sub_id = db.Column(db.Integer)  # none for a vendor item without a sub (2026-11-02)
    # The vendor item ordered (2026-10-20). An order recorded before vendor items has one when the
    # sub's vendor details were what it was placed with (12_workflow_tables.sql, step 2).
    vendor_item_id = db.Column(db.Integer)
    medline_item = db.Column(db.String(50), nullable=False)
    # The site it was ordered for, Medline's Sold-To code (2026-10-27): each site orders for itself.
    # Orders recorded before then have none.
    site = db.Column(db.String(20))
    po_number = db.Column(db.String(20))  # Infor's PO number, when the Materials Manager gives it (2026-10-27)
    quantity = db.Column(db.Integer, nullable=False)
    vendor_part = db.Column(db.String(100), nullable=False)
    uom = db.Column(db.String(10), nullable=False)
    qoe = db.Column(db.Numeric(12, 4))
    vendor = db.Column(db.String(255), nullable=False)
    vendor_id = db.Column(db.String(20))  # an order from before 2026-10-20 may have none
    ordered_by = db.Column(db.String(255), nullable=False)
    ordered_dt = db.Column(db.DateTime, nullable=False)
    voided_by = db.Column(db.String(255))
    voided_at = db.Column(db.DateTime)
    void_reason = db.Column(db.String(TEXT_MAX))
    create_dt = db.Column(db.DateTime, nullable=False, default=now_ny_naive)
    update_dt = db.Column(db.DateTime, nullable=False, default=now_ny_naive)

    sub = db.relationship(Sub, lazy="joined")
    vendor_item = db.relationship(VendorItem, lazy="joined")

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None


class ItemInstruction(db.Model):
    """An SCM instruction to the sites' Materials Managers on how to order an item (2026-10-27):
    which sub, how much, which sites. One thread per Infor item, the main table's row, or per Medline
    item when it isn't in Infor. Never changed or deleted: the newest is the one in force."""

    __tablename__ = "ItemInstruction"
    __table_args__ = (
        db.PrimaryKeyConstraint("instruction_id", name="PK_ItemInstruction"),
        db.Index("IX_ItemInstruction_infor_item", "infor_item", "written_at"),
        db.Index("IX_ItemInstruction_medline_item", "medline_item", "written_at"),
        {"schema": SCHEMA},
    )

    instruction_id = db.Column(db.Integer, autoincrement=True)
    infor_item = db.Column(db.String(50))  # the row's Infor item; none for a Medline item not in Infor
    medline_item = db.Column(db.String(50), nullable=False)  # the Medline item it was written from
    instruction = db.Column(db.String(INSTRUCTION_MAX), nullable=False)
    written_by = db.Column(db.String(255), nullable=False)
    written_at = db.Column(db.DateTime, nullable=False, default=now_ny_naive)


class History(db.Model):
    """One change or comment on a sub, a vendor item or an order. Comments live only here."""

    __tablename__ = "History"
    __table_args__ = (
        db.PrimaryKeyConstraint("history_id", name="PK_History"),
        db.CheckConstraint(_one_of("entity", HISTORY_ENTITIES), name="CK_History_entity"),
        db.CheckConstraint(_one_of("action", HISTORY_ACTIONS), name="CK_History_action"),
        db.Index("IX_History_item", "medline_item", "acted_at"),
        db.Index("IX_History_entity", "entity", "entity_id", "acted_at"),
        {"schema": SCHEMA},
    )

    # BIGINT on SQL Server; SQLite only auto-numbers a plain INTEGER key (tests).
    history_id = db.Column(db.BigInteger().with_variant(db.Integer(), "sqlite"), autoincrement=True)
    entity = db.Column(db.String(10), nullable=False)  # sub, vendoritem or order
    entity_id = db.Column(db.Integer, nullable=False)
    medline_item = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(20), nullable=False)
    field = db.Column(db.String(30))
    from_value = db.Column(db.String(TEXT_MAX))
    to_value = db.Column(db.String(TEXT_MAX))
    comment = db.Column(db.String(TEXT_MAX))
    actor = db.Column(db.String(255), nullable=False)
    acted_at = db.Column(db.DateTime, nullable=False, default=now_ny_naive)
