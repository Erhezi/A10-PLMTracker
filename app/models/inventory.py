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

class ContractItem(db.Model):
    """Read-only mapping of the PLM.vw_ContractItem view.

    Composite primary key: (contract_id, manufacturer, mfg_part_num)
    """

    __tablename__ = "vw_ContractItem"
    __table_args__ = {"schema": "PLM"}

    contract_id = db.Column("contract_id", db.String(50), primary_key=True)
    manufacturer = db.Column("manufacturer", db.String(255), primary_key=True)
    mfg_part_num = db.Column("mfg_part_num", db.String(100), primary_key=True)

     # Computed column in DB consist of stripped (spaces/dashes removed)
    search_shadow = db.Column("search_shadow", db.String(200))

    # Additional columns
    item_description = db.Column("item_description", db.String(500))
    item_type = db.Column("item_type", db.String(100))
    item = db.Column("item", db.String(50))
    last_update_date = db.Column("last_update_date", db.DateTime)

    def __repr__(self):  # pragma: no cover - debug aid
        return (
            f"<ContractItem contract={self.contract_id} {self.manufacturer} "
            f"{self.mfg_part_num} item={self.item}>"
        )

__all__ = ["Item", "ContractItem"]