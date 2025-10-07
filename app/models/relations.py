from __future__ import annotations
from typing import Iterable, Sequence

from .. import db
from . import now_ny_naive
from sqlalchemy.orm import relationship, backref, object_session
from sqlalchemy import Index, UniqueConstraint, text


PENDING_PLACEHOLDER_PREFIX = "PENDING***"


def _is_pending_placeholder(value: str | None) -> bool:
	return bool(value) and str(value).startswith(PENDING_PLACEHOLDER_PREFIX)


class ItemGroupConflictError(Exception):
	"""Raised when attempting to assign an item to both sides within the same group."""

	def __init__(self, item_group: int, item: str, existing_side: str, requested_side: str):
		super().__init__(
			f"Item {item} in group {item_group} already assigned to side {existing_side}; "
			f"cannot assign to side {requested_side}."
		)
		self.item_group = item_group
		self.item = item
		self.existing_side = existing_side
		self.requested_side = requested_side

class ItemLink(db.Model):
    __tablename__ = "ItemLink"
    __table_args__ = (
        # Filtered UNIQUE: triplet unique only when Replace Item is present
        Index(
            "UX_ItemLink_Item_Replace",
            "Item Group", "Item", "Replace Item",
            unique=True,
            mssql_where=text("[Replace Item] IS NOT NULL"),
        ),
        # Filtered UNIQUE: at most one NULL-replacement row per (Group, Item)
        Index(
            "UX_ItemLink_GroupItem_Discontinued",
            "Item Group", "Item",
            unique=True,
            mssql_where=text("[Replace Item] IS NULL"),
        ),
        # Search indexes you said you use a lot
        Index("IX_ItemLink_Item", "Item"),
        Index("IX_ItemLink_ItemGroup", "Item Group"),
        Index("IX_ItemLink_ReplaceItem", "Replace Item"),
        Index("IX_ItemLink_Stage", "Stage"),
        {"schema": "PLM"},
    )

    # Surrogate primary key (already IDENTITY in SQL Server)
    pkid = db.Column("PKID", db.BigInteger, primary_key=True, autoincrement=True)

    # Natural key fields (not PKs anymore)
    item_group      = db.Column("Item Group", db.Integer,    nullable=False)  
    item            = db.Column("Item",       db.String(10),  nullable=False)
    replace_item    = db.Column("Replace Item", db.String(250), nullable=True)  

    # Metadata columns
    mfg_part_num        = db.Column("Manufacturer Part Num",           db.String(100))
    manufacturer        = db.Column("Manufacturer",                    db.String(100))
    item_description    = db.Column("Item Description",                db.String(500))

    repl_mfg_part_num   = db.Column("Replace Item Manufacturer Part Num", db.String(100))
    repl_manufacturer   = db.Column("Replace Item Manufacturer",          db.String(100))
    repl_item_description = db.Column("Replace Item Item Description",    db.String(500))

    stage                 = db.Column("Stage", db.String(100))
    expected_go_live_date = db.Column("Expected Go Live Date", db.Date)

    create_dt           = db.Column("CreateDT", db.DateTime(timezone=False))
    update_dt           = db.Column("UpdateDT", db.DateTime(timezone=False))
    wrike_id            = db.Column("WrikeID",  db.String(50))

    def __repr__(self):
        return f"<ItemLink id={self.pkid} {self.item} -> {self.replace_item} (group={self.item_group}, stage={self.stage})>"


class ConflictError(db.Model):
	"""Mapping to PLM.ConflictError table capturing invalid relation attempts."""

	__tablename__ = "ConflictError"
	__table_args__ = (
		Index("IX_ConflictError_Item", "Item"),
		Index("IX_ConflictError_ReplaceItem", "Replace Item"),
		Index("IX_ConflictError_Type", "error_type"),
		{"schema": "PLM"},
	)

	ERROR_TYPES: Sequence[str] = (
		"many-to-many",
		"self-directed",
		"chaining",
		"reciprocal",
		"Unknown",
	)

	pkid = db.Column("PKID", db.BigInteger, primary_key=True, autoincrement=True)
	item_link_id = db.Column(
		"item_link_id",
		db.BigInteger,
		db.ForeignKey("PLM.ItemLink.PKID", ondelete="CASCADE"),
		nullable=True,
	)

	item = db.Column("Item", db.String(10), nullable=False)
	replace_item = db.Column("Replace Item", db.String(250), nullable=True)
	item_group = db.Column("Item Group", db.Integer, nullable=False)
	error_message = db.Column("error_message", db.String(1000), nullable=False)
	error_type = db.Column("error_type", db.String(100), nullable=False)
	create_dt = db.Column("create_dt", db.DateTime(timezone=False), nullable=False, default=now_ny_naive)

	def __repr__(self):
		return (
			f"<ConflictError id={self.pkid} group={self.item_group} item={self.item} "
			f"replace={self.replace_item} type={self.error_type}>"
		)

	@classmethod
	def _validate_error_type(cls, error_type: str) -> str:
		if error_type not in cls.ERROR_TYPES:
			raise ValueError(f"Unsupported conflict error type: {error_type}")
		return error_type

	@classmethod
	def log(
		cls,
		*,
		item_group: int,
		item: str,
		replace_item: str | None,
		error_type: str,
		error_message: str,
		triggering_links: Iterable[ItemLink | None] | None = None,
		session=None,
	) -> list["ConflictError"]:
		"""Persist conflict rows referencing the offending relation and existing links."""

		cls._validate_error_type(error_type)
		session = session or db.session
		links = list(triggering_links or [None])
		results: list[ConflictError] = []

		for link in links:
			if link is not None and link.pkid is None:
				session.flush([link])

			record = cls(
				item_link_id=getattr(link, "pkid", None),
				item=item,
				replace_item=replace_item,
				item_group=item_group,
				error_type=error_type,
				error_message=error_message,
			)
			session.add(record)
			results.append(record)

		return results


class ItemGroup(db.Model):
	""" Mapping to PLM.ItemGroup table.
	Store the pair of (Item, Item Group, Side) information
	When the item link pair(s) are validated and created, the 
	information will be write to this table for easy reference
	and easy check. 
	The side is either 'O' for original item or 'R' for replacement item.
	table will have unique constraint on (Item, Item Group, Side)
	"""

	__tablename__ = "ItemGroup"
	__table_args__ = (
		UniqueConstraint("Item", "Item Group", "Side", name="UX_ItemGroup_Item_Group_Side"),
		Index("IX_ItemGroup_Item", "Item"),
		Index("IX_ItemGroup_ItemGroup", "Item Group"),
		{"schema": "PLM"},
	)

	# Surrogate primary key (already IDENTITY in SQL Server)
	pkid = db.Column("PKID", db.BigInteger, primary_key=True, autoincrement=True)
	# foreign key reference back to ItemLink
	item_link_id = db.Column("item_link_id", db.BigInteger, db.ForeignKey("PLM.ItemLink.PKID", ondelete='CASCADE'), nullable=False)

	item = db.Column("Item", db.String(10), nullable=False)
	item_group = db.Column("Item Group", db.Integer, nullable=False)
	side = db.Column("Side", db.String(1), nullable=False)  # 'O' or 'R' or 'D' (discontinued)
	create_dt = db.Column("create_dt", db.DateTime(timezone=False), nullable=False, default=now_ny_naive)
	update_dt = db.Column("update_dt", db.DateTime(timezone=False), nullable=False, default=now_ny_naive, onupdate=now_ny_naive)

	item_link = relationship(
		"ItemLink",
		backref=backref("item_groups", cascade="all, delete-orphan", passive_deletes=True),
		foreign_keys=[item_link_id],
	)

	def __repr__(self):
		return f"<ItemGroup id={self.pkid} group={self.item_group} item={self.item} side={self.side}>"

	@classmethod
	def _resolve_session(cls, session=None, item_link=None):
		if session is not None:
			return session
		if item_link is not None:
			session = object_session(item_link)
			if session is not None:
				return session
		return db.session

	@classmethod
	def ensure_allowed_side(cls, item_group: int, item_code: str | None, side: str, *, session=None, item_link_id: int | None = None):
		"""Validate that an item within a group can take the requested side."""
		if not item_code or _is_pending_placeholder(item_code):
			return
		session = cls._resolve_session(session)
		existing = (
			session.query(cls)
			.filter(cls.item_group == item_group, cls.item == item_code)
			.first()
		)
		if existing and existing.side != side and existing.item_link_id != item_link_id:
			raise ItemGroupConflictError(item_group, item_code, existing.side, side)

	@classmethod
	def sync_from_item_link(cls, item_link: ItemLink, *, session=None):
		"""Ensure ItemGroup rows reflect the provided ItemLink."""
		if item_link.pkid is None:
			raise ValueError("ItemLink must be flushed before syncing ItemGroup entries")
		session = cls._resolve_session(session, item_link)
		desired_pairs = cls._desired_pairs_for_link(item_link)
		desired_keys = {(code, side) for code, side in desired_pairs if code}

		# Remove stale rows tied to this link that are no longer represented
		existing_rows = (
			session.query(cls)
			.filter(cls.item_link_id == item_link.pkid)
			.all()
		)
		for row in existing_rows:
			if (row.item, row.side) not in desired_keys:
				session.delete(row)

		for code, side in desired_pairs:
			cls._upsert(session, item_link, code, side)

	@staticmethod
	def _desired_pairs_for_link(item_link: ItemLink) -> list[tuple[str | None, str]]:
		replace_value = item_link.replace_item
		if replace_value and not _is_pending_placeholder(replace_value):
			return [
				(item_link.item, "O"),
				(replace_value, "R"),
			]
		if replace_value:
			return [(item_link.item, "O")]
		return [(item_link.item, "D")]

	@classmethod
	def _upsert(cls, session, item_link: ItemLink, item_code: str | None, side: str):
		if not item_code:
			return
		existing = (
			session.query(cls)
			.filter(cls.item_group == item_link.item_group, cls.item == item_code)
			.first()
		)
		if existing:
			if existing.side != side and existing.item_link_id != item_link.pkid:
				raise ItemGroupConflictError(item_link.item_group, item_code, existing.side, side)
			existing.side = side
			existing.item_link_id = item_link.pkid
			existing.update_dt = now_ny_naive()
			return existing
		new_entry = cls(
			item_link_id=item_link.pkid,
			item=item_code,
			item_group=item_link.item_group,
			side=side,
			create_dt=now_ny_naive(),
			update_dt=now_ny_naive(),
		)
		session.add(new_entry)
		return new_entry


class PendingItems(db.Model):
	__tablename__ = "PendingItems"
	__table_args__ = (
		# unique constraint on (item_link_id, replace_item_pending)
		# to prevent duplicate pending entries for same link and part num
		UniqueConstraint("item_link_id", "replace_item_pending", 
				         name="UX_PendingItems_Link_ReplacePending"),
		# index for filtering
		Index("IX_PendingItems_Status", "status"),
		Index("IX_PendingItems_ReplaceItemPending", "replace_item_pending"),
		{"schema": "PLM"},
	)

	# sarrogate primary key
	pkid = db.Column("PKID", db.BigInteger, primary_key=True, autoincrement=True)
	# foreign key reference back to ItemLink
	item_link_id = db.Column("item_link_id", db.BigInteger, db.ForeignKey("PLM.ItemLink.PKID", ondelete='CASCADE'), nullable=False)

	# the placeholder code e.g. PENDING***ABC123
	replace_item_pending = db.Column("replace_item_pending", db.String(250), nullable=False)

	# basic information to track progress and locate the item
	status = db.Column("status", db.String(20), nullable=False, default="PENDING")  # PENDING, IMAST, ERROR
	contract_id = db.Column("contract_id", db.String(50), nullable=False)
	mfg_part_num = db.Column("mfg_part_num", db.String(100), nullable=False)

	# item master number acquired
	replace_item_immast = db.Column("replace_item_immast", db.String(10), nullable=False, default = "")
	
	# timestamps
	create_dt = db.Column("create_dt", db.DateTime(timezone=False), nullable=False, default=now_ny_naive)
	update_dt = db.Column("update_dt", db.DateTime(timezone=False), nullable=False, default=now_ny_naive, onupdate=now_ny_naive)

	item_link = relationship(
		"ItemLink", 
		foreign_keys=[item_link_id], 
		backref=backref("pending_items", cascade="all, delete-orphan"),
		lazy="joined"
    )

	def __repr__(self):
		return f"<PendingItems id={self.pkid} link_id={self.item_link_id} pending={self.replace_item_pending} status={self.status} immast={self.replace_item_immast}>"
	
	@classmethod
	def create_from_contract_item(cls, item_link_id: int, contract_id: str, mfg_part_num: str) -> PendingItems:
		placeholder = f"PENDING***{mfg_part_num}"
		return cls(
			item_link_id=item_link_id,
			replace_item_pending=placeholder,
			contract_id=contract_id,
			mfg_part_num=mfg_part_num,
			status="PENDING",
			replace_item_immast=""
		)
	
	def mark_as_immast(self, immast_item: str):
		self.replace_item_immast = immast_item
		self.status = "IMMAST"
	
	def mark_as_error(self):
		self.status = "ERROR"


class PLMItemGroupLocation(db.Model):
	"""Read-only mapping to PLM.vw_PLMItemGroupLocation view.

	This is an important building block that collect all locations 
	associated with each item group.

	Synthetic composite primary key uses Item Group and Location so the ORM
	can work with result objects.
	"""

	__tablename__ = "vw_PLMItemGroupLocation"
	__table_args__ = {"schema": "PLM"}

	# Columns
	Item_Group = db.Column("Item Group", db.Integer, nullable=False, primary_key=True)
	Company = db.Column("Company", db.String(10), nullable=False, primary_key=True)
	Group_Locations = db.Column("Group Locations", db.String(20), nullable=False, primary_key=True)
	LocationType = db.Column("LocationType", db.String(40), nullable=True)

	__mapper_args__ = {
		"primary_key": [Item_Group, Company, Group_Locations]
	}

	def __repr__(self):
		return f"<PLMItemGroupLocation group={self.Item_Group} company={self.Company} location={self.Group_Locations}>"


class PLMTranckerHead(db.Model):
	"""Read-only mapping to PLM.vw_PLMTrackerHead view.

	This is the left side of the PLMTrackerBase and essential building block 
	to correctly identify the z-date in determing the terminating date for burn
	rate calculation.

	z-date -- initially this is designed to reflect the first zero-inventory date
	for an item at a location after the most recent non-zero inventory date. burn 
	rate, when traverse backwards from z-date, help us to avoid the dilution effect
	of historical usage when an item was stocked but not used for a long time.

	with the new method, z-date now consider the item and replacement item as a pair,
	and the z-date is thus moved to the introduction date of the replacement item if
	it is earlier than the original z-date. In this case, we avoid the complexity of
	trying to resolve the burn rate for the transition period when both items are stocked.

	it is possible that the replacement item is co-existing with the original item for 
	a long time, and in such case the conversion is to consolidate to replacement item.
	In this case, we would like to introduce an artificial co-existing period threshold
	(e.g. 90 days) so if co-exstence is longer than that, the final burn rate calculation
	will be based on the sum of usage of both items.

	This view doesn't expose a natural primary key; we provide a synthetic
	composite mapper_key so the ORM can work with instances. No relationships
	are declared here.
	"""

	__tablename__ = "vw_PLMTrackerHead"
	# __tablename__ = "PLMTrackerHead"
	__table_args__ = {"schema": "PLM"}

	# Columns (use exact names where provided)
	PKID_ItemLink = db.Column("PKID", db.BIGINT, nullable=False, primary_key=True)

	Item_Group = db.Column("Item Group", db.Integer, nullable=False)
	Item = db.Column("Item", db.String(10), nullable=False)
	Replace_Item = db.Column("Replace Item", db.String(250), nullable=False)

	Stage = db.Column("Stage", db.String(100), nullable=False)

	Group_Locations = db.Column("Group Locations", db.String(20), nullable=True, primary_key=True)
	LocationType = db.Column("LocationType", db.String(40), nullable=True)
	Company = db.Column("Company", db.String(10), nullable=True)
	create_dt = db.Column("CreateDT", db.DateTime(timezone=False), nullable=True)
	update_dt = db.Column("UpdateDT", db.DateTime(timezone=False), nullable=True)

	__mapper_args__ = {
		"primary_key": [PKID_ItemLink, Group_Locations]
	}

	def __repr__(self):
		return f"<PLMTrackerHead link={self.PKID_ItemLink} group={self.Item_Group} item={self.Item} replace={self.Replace_Item} location={self.Group_Locations}>"
	

class PLMTrackerBase(db.Model):
	"""Read-only mapping to PLM.vw_PLMTrackerBase used by dashboard views.

	This view doesn't expose a natural primary key; we provide a synthetic
	composite mapper_key so the ORM can work with instances. No relationships
	are declared here.
	"""

	__tablename__ = "vw_PLMTrackerBase"
	# __tablename__ = "PLMTrackerBase"
	__table_args__ = {"schema": "PLM"}


	# Major grouping fields
	Stage = db.Column("Stage", db.String(100), nullable=False)
	Item_Group = db.Column("Item Group", db.Integer, nullable=True)
	Group_Locations = db.Column("Group Locations", db.String(20), nullable=False)
	PKID_ItemLink = db.Column("PKID", db.BIGINT, nullable=False)
	LocationType = db.Column("LocationType", db.String(40), nullable=True)

	# rolling burn rate and rolling BR related meta data fields
	br_calc_status = db.Column("br_calc_status", db.String(12), nullable=True)
	br_calc_type = db.Column("br_calc_type", db.String(12), nullable=True)
	br7_rolling_itemgroup = db.Column("br7_rolling_itemgroup", db.Numeric, nullable=True)
	br60_rolling_itemgroup = db.Column("br60_rolling_itemgroup", db.Numeric, nullable=True)

    # Original Item side fields	
	Item = db.Column("Item", db.String(10), nullable=False)

	Location = db.Column("Location", db.String(20), nullable=True)
	LocationText = db.Column("LocationText", db.String(255), nullable=True)
	Inventory_base_ID = db.Column("Inventory_base_ID", db.BIGINT, nullable=True)
	PreferredBin = db.Column("PreferredBin", db.String(40), nullable=True)
	ItemDescription = db.Column("ItemDescription", db.String(255), nullable=True)
	ManufacturerNumber = db.Column("ManufacturerNumber", db.String(100), nullable=True)
	Active = db.Column("Active", db.String(5), nullable=True)
	Discontinued = db.Column("Discontinued", db.String(5), nullable=True)
	AutomaticPO = db.Column("AutomaticPO", db.String(5), nullable=True)
	StockUOM = db.Column("StockUOM", db.String(20), nullable=True)
	UOMConversion = db.Column("UOMConversion", db.Numeric, nullable=True)
	DefaultBuyUOM = db.Column("DefaultBuyUOM", db.String(10), nullable=True)
	BuyUOMMultiplier = db.Column("BuyUOMMultiplier", db.Numeric, nullable=True)
	ReorderQuantityCode = db.Column("ReorderQuantityCode", db.String(40), nullable=True)
	ReorderPoint = db.Column("ReorderPoint", db.Integer, nullable=True)
	MaxOrderQty = db.Column("MaxOrderQty", db.Integer, nullable=True)
	MinOrderQty = db.Column("MinOrderQty", db.Integer, nullable=True)
	AvailableQty = db.Column("AvailableQty", db.Integer, nullable=True)
	UnitCostInStockUOM = db.Column("UnitCostInStockUOM", db.Numeric, nullable=True)
	br7_rolling_item = db.Column("br7_rolling_item", db.Numeric, nullable=True)
	br60_rolling_item = db.Column("br60_rolling_item", db.Numeric, nullable=True)
	br7 = db.Column("br7", db.Numeric, nullable=True)
	br35 = db.Column("br35", db.Numeric, nullable=True)
	br91 = db.Column("br91", db.Numeric, nullable=True)
	br365 = db.Column("br365", db.Numeric, nullable=True)
	issued_count_365 = db.Column("issued_count_365", db.Integer, nullable=True)
	OrderQty90_EA = db.Column("OrderQty90_EA", db.Numeric, nullable=True)
	ReqQty90_EA = db.Column("ReqQty90_EA", db.Numeric, nullable=True)
	requester_count = db.Column("requester_count", db.Integer, nullable=True) # only available to original item side

	# Replace Item side (ri) fields
	Replace_Item = db.Column("Replace Item", db.String(250), nullable=False)

	Location_ri = db.Column("Location_ri", db.String(20), nullable=True)
	LocationText_ri = db.Column("LocationText_ri", db.String(255), nullable=True)
	Inventory_base_ID_ri = db.Column("Inventory_base_ID_ri", db.BIGINT, nullable=True)
	PreferredBin_ri = db.Column("PreferredBin_ri", db.String(40), nullable=True)
	ItemDescription_ri = db.Column("ItemDescription_ri", db.String(255), nullable=True)
	ManufacturerNumber_ri = db.Column("ManufacturerNumber_ri", db.String(100), nullable=True)
	Active_ri = db.Column("Active_ri", db.String(5), nullable=True)
	Discontinued_ri = db.Column("Discontinued_ri", db.String(5), nullable=True)
	AutomaticPO_ri = db.Column("AutomaticPO_ri", db.String(5), nullable=True)
	StockUOM_ri = db.Column("StockUOM_ri", db.String(20), nullable=True)
	UOMConversion_ri = db.Column("UOMConversion_ri", db.Numeric, nullable=True)
	DefaultBuyUOM_ri = db.Column("DefaultBuyUOM_ri", db.String(10), nullable=True)
	BuyUOMMultiplier_ri = db.Column("BuyUOMMultiplier_ri", db.Numeric, nullable=True)
	ReorderQuantityCode_ri = db.Column("ReorderQuantityCode_ri", db.String(40), nullable=True)
	ReorderPoint_ri = db.Column("ReorderPoint_ri", db.Integer, nullable=True)
	MaxOrderQty_ri = db.Column("MaxOrderQty_ri", db.Integer, nullable=True)
	MinOrderQty_ri = db.Column("MinOrderQty_ri", db.Integer, nullable=True)
	AvailableQty_ri = db.Column("AvailableQty_ri", db.Integer, nullable=True)
	UnitCostInStockUOM_ri = db.Column("UnitCostInStockUOM_ri", db.Numeric, nullable=True)
	br7_rolling_item_ri = db.Column("br7_rolling_item_ri", db.Numeric, nullable=True)
	br60_rolling_item_ri = db.Column("br60_rolling_item_ri", db.Numeric, nullable=True)
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
		"primary_key": [PKID_ItemLink, Group_Locations, Item, Replace_Item, Item_Group]
	}


class PLMQty(db.Model):
	"""Read-only mapping to PLM.vw_PLMQty view.

	Synthetic composite primary key uses Location, Item, and report_stamp so
	the ORM can work with result objects.
	"""

	__tablename__ = "vw_PLMQty"
	__table_args__ = {"schema": "PLM"}

	# Composite primary key
	Inventory_base_ID = db.Column("Inventory_base_ID", db.BIGINT, nullable=False, primary_key=True)
	PKID_ItemLink = db.Column("PKID", db.BIGINT, nullable=False, primary_key=True)
	report_stamp = db.Column("update stamp", db.DateTime, nullable=False, primary_key = True) # this is mapped to update stamp on inventory location, not the report stamp

	# Columns
	Location = db.Column("Location", db.String(20), nullable=False)
	Item = db.Column("Item", db.String(10), nullable=False)
	Item_Group = db.Column("Item Group", db.Integer, nullable=False)
	
	PLM_Zdate = db.Column("PLM_Zdate", db.Date, nullable=True)

	AvailableQty = db.Column("AvailableQty", db.Integer, nullable=True)

	__mapper_args__ = {
		"primary_key": [Inventory_base_ID, PKID_ItemLink, report_stamp]
	}


class PLMDailyIssueOutQty(db.Model):
	"""Read-only mapping to PLM.vw_PLMDailyIssueOutQty view.

	Synthetic composite primary key uses Location, Item, and report_date so
	the ORM can work with result objects.
	"""

	__tablename__ = "vw_PLMDailyIssueOutQty"
	__table_args__ = {"schema": "PLM"}

	# Composite primary key
	Inventory_base_ID = db.Column("Inventory_base_ID", db.BIGINT, nullable=False, primary_key=True)
	PKID_ItemLink = db.Column("PKID", db.BIGINT, nullable=False, primary_key=True)
	trx_date = db.Column("trx_date", db.Date, nullable=False, primary_key=True)

	# Columns
	Location = db.Column("Location", db.String(20), nullable=False)
	Item = db.Column("Item", db.String(10), nullable=False)
	Item_Group = db.Column("Item Group", db.Integer, nullable=False)

	IssuedQty = db.Column("QtyInLum", db.Integer, nullable=True)

	__mapper_args__ = {
		"primary_key": [Inventory_base_ID, PKID_ItemLink, trx_date]
	}