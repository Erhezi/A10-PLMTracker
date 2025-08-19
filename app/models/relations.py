from __future__ import annotations
from .. import db
from . import now_ny_naive


class ItemLink(db.Model):
	__tablename__ = "ItemLink"

	# Clean Python attribute  ->  Exact DB column name (with spaces)
	item_group = db.Column("Item Group", db.Integer)

	# Composite primary key
	item = db.Column("Item", db.String(50), primary_key=True)
	replace_item = db.Column("Replace Item", db.String(50), primary_key=True)

	# Metadata columns from the sheet
	mfg_part_num = db.Column("Manufacturer Part Num", db.String(100))
	manufacturer = db.Column("Manufacturer", db.String(100))
	item_description = db.Column("Item Description", db.String(500))

	repl_mfg_part_num = db.Column("Replace Item Manufacturer Part Num", db.String(100))
	repl_manufacturer = db.Column("Replace Item Manufacturer", db.String(100))
	repl_item_description = db.Column("Replace Item Item Description", db.String(500))

	stage = db.Column("Stage", db.String(100))
	expected_go_live_date = db.Column("Expected Go Live Date", db.Date)

	create_dt = db.Column("CreateDT", db.DateTime(timezone=False), default=now_ny_naive)
	update_dt = db.Column("UpdateDT", db.DateTime(timezone=False), default=now_ny_naive, onupdate=now_ny_naive)
	wrike_id = db.Column("WrikeID", db.String(50))

	def __repr__(self):
		return f"<ItemLink {self.item} -> {self.replace_item} ({self.item_group}, {self.stage})>"
