from __future__ import annotations
from .. import db
from . import now_ny_naive
from . import ItemLocationPar, ItemLocationInventory, ItemLocations
from sqlalchemy.orm import relationship, foreign

class ItemLink(db.Model):
	__tablename__ = "ItemLink"
	# Include server-side indexes (already created manually) for ORM awareness / reflection.
	# Note: SQLAlchemy will not attempt to create them if they already exist; keeps metadata aligned.
	from sqlalchemy import Index
	__table_args__ = (
		Index("UX_ItemLink_Item_Replace", "Item", "Replace Item", unique=True),
		Index("IX_ItemLink_Item", "Item"),
		Index("IX_ItemLink_ReplaceItem", "Replace Item"),
		Index("IX_ItemLink_ItemGroup", "Item Group"),
		Index("IX_ItemLink_Stage", "Stage"),
		{"schema": "PLM"},
	)

	# Clean Python attribute  ->  Exact DB column name (with spaces)
	item_group = db.Column("Item Group", db.Integer)

	# Composite primary key
	item = db.Column("Item", db.String(10), primary_key=True)
	replace_item = db.Column("Replace Item", db.String(250), primary_key=True)

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


class PLMTrackerBase(db.Model):
	"""Read-only mapping to PLM.vw_PLMTrackerBase used by dashboard views.

	This view doesn't expose a natural primary key; we provide a synthetic
	composite mapper_key so the ORM can work with instances. No relationships
	are declared here per your request.
	"""

	__tablename__ = "vw_PLMTrackerBase"
	# __tablename__ = "PLMTrackerBase"
	__table_args__ = {"schema": "PLM"}

	# Columns (use exact names where provided)
	Stage = db.Column("Stage", db.String(100), nullable=False)
	Item_Group = db.Column("Item Group", db.Integer, nullable=True)
	Group_Locations = db.Column("Group Locations", db.String(20), nullable=False)
	LocationType = db.Column("LocationType", db.String(40), nullable=True)
	Item = db.Column("Item", db.String(10), nullable=False)
	Location = db.Column("Location", db.String(20), nullable=True)
	LocationText = db.Column("LocationText", db.String(255), nullable=True)
	Inventory_base_ID = db.Column("Inventory_base_ID", db.BIGINT, nullable=True)
	PreferredBin = db.Column("PreferredBin", db.String(40), nullable=True)
	ItemDescription = db.Column("ItemDescription", db.String(255), nullable=True)
	Active = db.Column("Active", db.String(5), nullable=True)
	Discontinued = db.Column("Discontinued", db.String(5), nullable=True)
	AutomaticPO = db.Column("AutomaticPO", db.String(5), nullable=True)
	StockUOM = db.Column("StockUOM", db.String(20), nullable=True)
	UOMConversion = db.Column("UOMConversion", db.Numeric, nullable=True)
	ReorderQuantityCode = db.Column("ReorderQuantityCode", db.String(40), nullable=True)
	ReorderPoint = db.Column("ReorderPoint", db.Integer, nullable=True)
	MaxOrderQty = db.Column("MaxOrderQty", db.Integer, nullable=True)
	MinOrderQty = db.Column("MinOrderQty", db.Integer, nullable=True)
	AvailableQty = db.Column("AvailableQty", db.Integer, nullable=True)
	UnitCostInStockUOM = db.Column("UnitCostInStockUOM", db.Numeric, nullable=True)
	br7 = db.Column("br7", db.Numeric, nullable=True)
	br35 = db.Column("br35", db.Numeric, nullable=True)
	br91 = db.Column("br91", db.Numeric, nullable=True)
	br365 = db.Column("br365", db.Numeric, nullable=True)
	issued_count_365 = db.Column("issued_count_365", db.Integer, nullable=True)
	OrderQty90_EA = db.Column("OrderQty90_EA", db.Numeric, nullable=True)
	ReqQty90_EA = db.Column("ReqQty90_EA", db.Numeric, nullable=True)
	Replace_Item = db.Column("Replace Item", db.String(250), nullable=False)

	# Replace Item side (ri) fields
	Location_ri = db.Column("Location_ri", db.String(20), nullable=True)
	LocationText_ri = db.Column("LocationText_ri", db.String(255), nullable=True)
	Inventory_base_ID_ri = db.Column("Inventory_base_ID_ri", db.BIGINT, nullable=True)
	PreferredBin_ri = db.Column("PreferredBin_ri", db.String(40), nullable=True)
	ItemDescription_ri = db.Column("ItemDescription_ri", db.String(255), nullable=True)
	Active_ri = db.Column("Active_ri", db.String(5), nullable=True)
	Discontinued_ri = db.Column("Discontinued_ri", db.String(5), nullable=True)
	AutomaticPO_ri = db.Column("AutomaticPO_ri", db.String(5), nullable=True)
	StockUOM_ri = db.Column("StockUOM_ri", db.String(20), nullable=True)
	UOMConversion_ri = db.Column("UOMConversion_ri", db.Numeric, nullable=True)
	ReorderQuantityCode_ri = db.Column("ReorderQuantityCode_ri", db.String(40), nullable=True)
	ReorderPoint_ri = db.Column("ReorderPoint_ri", db.Integer, nullable=True)
	MaxOrderQty_ri = db.Column("MaxOrderQty_ri", db.Integer, nullable=True)
	MinOrderQty_ri = db.Column("MinOrderQty_ri", db.Integer, nullable=True)
	AvailableQty_ri = db.Column("AvailableQty_ri", db.Integer, nullable=True)
	UnitCostInStockUOM_ri = db.Column("UnitCostInStockUOM_ri", db.Numeric, nullable=True)
	br7_ri = db.Column("br7_ri", db.Numeric, nullable=True)
	br35_ri = db.Column("br35_ri", db.Numeric, nullable=True)
	br91_ri = db.Column("br91_ri", db.Numeric, nullable=True)
	br365_ri = db.Column("br365_ri", db.Numeric, nullable=True)
	issued_count_365_ri = db.Column("issued_count_365_ri", db.Integer, nullable=True)
	OrderQty90_EA_ri = db.Column("OrderQty90_EA_ri", db.Numeric, nullable=True)
	ReqQty90_EA_ri = db.Column("ReqQty90_EA_ri", db.Numeric, nullable=True)

	# No relationships per request

	# Provide a synthetic composite primary key for the mapper so SQLAlchemy can
	# work with result objects. Adjust if your view has a better natural key.
	__mapper_args__ = {
		"primary_key": [Group_Locations, Item, Replace_Item]
	}
