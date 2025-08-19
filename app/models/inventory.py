from __future__ import annotations

from .. import db


class Item(db.Model):
    """Read-only mapping of the PLM.vw_Item view."""

    __tablename__ = "vw_Item"  # underlying view name inside PLM schema
    __table_args__ = {"schema": "PLM"}  # Specify the schema explicitly

    # Use the actual view column names (after AS in the view definition)
    item = db.Column("item", db.String(50), primary_key=True)
    is_active = db.Column("is_active", db.Boolean)
    is_discontinued = db.Column("is_discontinued", db.Boolean)
    manufacturer = db.Column("manufacturer", db.String(255))
    mfg_part_num = db.Column("mfg_part_num", db.String(100))
    item_description = db.Column("item_description", db.String(500))
    last_update_date = db.Column("last_update_date", db.DateTime)

    def __repr__(self):  # pragma: no cover - debug aid
        return f"<Item {self.item} active={self.is_active} disc={self.is_discontinued}>"

    # We do not intend to insert/update/delete items via ORM; application code should treat this as read-only.

__all__ = ["Item"]