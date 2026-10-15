"""Fill/Kill workflow tables (schema FillKill): subs, orders, and their history.

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
SUB_SOURCES = ("manual", "medline_pbo", "llm")
HISTORY_ENTITIES = ("sub", "order")
HISTORY_ACTIONS = ("created", "status", "pick", "unpick", "comment", "edit", "void")

TEXT_MAX = 400  # comments and void reasons


def _one_of(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Sub(db.Model):
    """A sub of a Medline item: a vendor and that vendor's part number."""

    __tablename__ = "Sub"
    __table_args__ = (
        db.PrimaryKeyConstraint("sub_id", name="PK_Sub"),
        db.UniqueConstraint("medline_item", "vendor", "vendor_part", name="UQ_Sub_item_vendor_part"),
        db.CheckConstraint(_one_of("status", SUB_STATUSES), name="CK_Sub_status"),
        db.CheckConstraint(_one_of("source", SUB_SOURCES), name="CK_Sub_source"),
        db.CheckConstraint("is_picked = 0 OR status = 'approved'", name="CK_Sub_pick_needs_approved"),
        db.CheckConstraint("qoe IS NULL OR qoe > 0", name="CK_Sub_qoe"),
        {"schema": SCHEMA},
    )

    sub_id = db.Column(db.Integer, autoincrement=True)
    medline_item = db.Column(db.String(50), nullable=False)
    vendor = db.Column(db.String(255), nullable=False)  # Infor's vendor ID, e.g. 1000931
    vendor_name = db.Column(db.String(255))             # its name in Infor's vendor master
    vendor_part = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255))
    uom = db.Column(db.String(10))
    qoe = db.Column(db.Numeric(12, 4))
    status = db.Column(db.String(20), nullable=False, default="pending_review")
    is_picked = db.Column(db.Boolean, nullable=False, default=False)
    source = db.Column(db.String(20), nullable=False)
    entered_by = db.Column(db.String(255), nullable=False)
    create_dt = db.Column(db.DateTime, nullable=False, default=now_ny_naive)
    update_dt = db.Column(db.DateTime, nullable=False, default=now_ny_naive)

    def label(self) -> str:
        return f"{self.vendor_part} ({self.vendor_name or self.vendor})"


class SubOrder(db.Model):
    """An order a Materials Manager recorded against a picked sub."""

    __tablename__ = "SubOrder"
    __table_args__ = (
        db.PrimaryKeyConstraint("order_id", name="PK_SubOrder"),
        db.ForeignKeyConstraint(["sub_id"], [f"{SCHEMA}.Sub.sub_id"], name="FK_SubOrder_Sub"),
        db.CheckConstraint("quantity > 0", name="CK_SubOrder_quantity"),
        db.CheckConstraint("qoe IS NULL OR qoe > 0", name="CK_SubOrder_qoe"),
        db.CheckConstraint(
            "(voided_at IS NULL AND voided_by IS NULL AND void_reason IS NULL)"
            " OR (voided_at IS NOT NULL AND voided_by IS NOT NULL AND void_reason IS NOT NULL)",
            name="CK_SubOrder_void",
        ),
        db.Index("IX_SubOrder_item_ordered", "medline_item", "ordered_dt"),
        db.Index("IX_SubOrder_sub", "sub_id"),
        {"schema": SCHEMA},
    )

    order_id = db.Column(db.Integer, autoincrement=True)
    sub_id = db.Column(db.Integer, nullable=False)
    medline_item = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    uom = db.Column(db.String(10), nullable=False)
    qoe = db.Column(db.Numeric(12, 4))
    vendor = db.Column(db.String(255), nullable=False)
    ordered_by = db.Column(db.String(255), nullable=False)
    ordered_dt = db.Column(db.DateTime, nullable=False)
    voided_by = db.Column(db.String(255))
    voided_at = db.Column(db.DateTime)
    void_reason = db.Column(db.String(TEXT_MAX))
    create_dt = db.Column(db.DateTime, nullable=False, default=now_ny_naive)
    update_dt = db.Column(db.DateTime, nullable=False, default=now_ny_naive)

    sub = db.relationship(Sub, lazy="joined")

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None


class History(db.Model):
    """One change or comment on a sub or an order. Comments live only here."""

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
    entity = db.Column(db.String(10), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    medline_item = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(20), nullable=False)
    field = db.Column(db.String(30))
    from_value = db.Column(db.String(TEXT_MAX))
    to_value = db.Column(db.String(TEXT_MAX))
    comment = db.Column(db.String(TEXT_MAX))
    actor = db.Column(db.String(255), nullable=False)
    acted_at = db.Column(db.DateTime, nullable=False, default=now_ny_naive)
