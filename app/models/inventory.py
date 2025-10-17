from __future__ import annotations

from .. import db
from sqlalchemy.orm import relationship, foreign
from sqlalchemy import and_, or_, Index, UniqueConstraint

#-------------------------------------------------------
# View Mappings - non-PLM ItemLink specific
#-------------------------------------------------------
class Item(db.Model):
    """Read-only mapping of the PLM.vw_Item view."""

    __tablename__ = "vw_Item"  # underlying view name inside PLM schema
    __table_args__ = {"schema": "PLM", "extend_existing": True}  # Specify the schema explicitly

    # Use the actual view column names (after AS in the view definition)
    item = db.Column("item", db.String(50), primary_key=True)
    is_active = db.Column("is_active", db.String(5))
    is_discontinued = db.Column("is_discontinued", db.String(5))
    manufacturer = db.Column("manufacturer", db.String(255))
    mfg_part_num = db.Column("mfg_part_num", db.String(100))
    item_description = db.Column("item_description", db.String(500))
    company_3000 = db.Column("company_3000", db.String(5)) # take value 'Yes' or 'No' to indicate if item exists in 3000's locations (inscope or not)
    last_update_date = db.Column("last_update_date", db.DateTime)

    def __repr__(self):  # pragma: no cover - debug aid
        return f"<Item {self.item} active={self.is_active} disc={self.is_discontinued}>"

    # We do not intend to insert/update/delete items via ORM; application code should treat this as read-only.

class ContractItem(db.Model):
    """Read-only mapping of the PLM.vw_ContractItem view.

    Composite primary key: (contract_id, manufacturer, mfg_part_num)
    """

    __tablename__ = "vw_ContractItem"
    __table_args__ = {"schema": "PLM", "extend_existing": True}

    contract_id = db.Column("contract_id", db.String(50), primary_key=True)
    manufacturer = db.Column("manufacturer", db.String(255), primary_key=True)
    mfg_part_num = db.Column("mfg_part_num", db.String(100), primary_key=True)

     # Computed column in DB consist of stripped (spaces/dashes removed)
    search_shadow = db.Column("search_shadow", db.String(200))

    # Additional columns
    item_description = db.Column("item_description", db.String(500))
    item_type = db.Column("item_type", db.String(100))
    item = db.Column("item", db.String(50))
    is_mhs = db.Column("is_mhs", db.String(5))  # take value 'Yes' or 'No', indicate if item is on MHS Contracts (meaning it is not entity specific)
    last_update_date = db.Column("last_update_date", db.DateTime)

    def __repr__(self):  # pragma: no cover - debug aid
        return (
            f"<ContractItem contract={self.contract_id} {self.manufacturer} "
            f"{self.mfg_part_num} item={self.item}>"
        )
    
class Requesters365Day(db.Model):
    """
    Mapping to PLM.vw_365Day_Requesters (SQL Server VIEW).
    Read-only
    """

    __tablename__ = "vw_365Day_Requesters"
    __table_args__ = {"schema": "PLM", "extend_existing": True}

    # no natural PK in your schema, so we mark all columns as nullable
    # and rely on SQLAlchemy's requirement for *some* PK surrogate.
    RequestingLocation = db.Column(db.String(40),  primary_key=True, nullable=True)
    Item               = db.Column(db.String(100), primary_key=True, nullable=True)
    Requester          = db.Column(db.String(20),  primary_key=True, nullable=True)

    RequesterName      = db.Column(db.String(100), nullable=True)
    Requisition_FD5    = db.Column("Requisition.FD5", db.String(150), nullable=True)
    EmailAddress       = db.Column(db.String(450), nullable=True)

    RequestsCount      = db.Column(db.Integer, nullable=True) # numbers of requisition lines made by this requester for this item at this location in past 365 days

    def __repr__(self):
        return (f"<Requesters365Day("
                f"Requester={self.Requester!r}, "
                f"Item={self.Item!r}, "
                f"Location={self.RequestingLocation!r})>")


class PO90Day(db.Model):
    """
    Mapping to PLM.vw_90Day_PO (SQL Server VIEW).
    Read-only.
    """

    __tablename__ = "vw_90Day_PO"
    __table_args__ = {"schema": "PLM", "extend_existing": True}

    POReleaseDate      = db.Column(db.Date, primary_key = True, nullable=True)
    PO                 = db.Column(db.String(20),  primary_key=True, nullable=False)
    POLine             = db.Column(db.String(10),  primary_key=True, nullable=False)
    PurchaseOrderLine  = db.Column(db.String(10),  nullable=False)

    Company            = db.Column(db.String(10),  nullable=False)

    OrderToStoreroom   = db.Column(db.String(13),  nullable=False)
    Location           = db.Column(db.String(40),  nullable=True)
    TrasientInventoryLocation = db.Column(db.String(40),  nullable=True)

    Item               = db.Column(db.String(100), nullable=True)
    EnteredBuyUOM      = db.Column(db.String(20),  nullable=True)
    EnteredBuyUOMMultiplier = db.Column(db.Numeric, nullable=True)
    Item_StockUOM      = db.Column("Item.StockUOM", db.String(20), nullable=True)
    UOMConversion      = db.Column(db.Numeric, nullable=True)

    Quantity           = db.Column(db.Numeric, nullable=True)
    ReceivedQuantity   = db.Column(db.Numeric, nullable=True)
    CancelQuantity     = db.Column(db.Numeric, nullable=True)

    OrderQty_EA        = db.Column(db.Numeric, nullable=True)
    ReceivedQty_EA     = db.Column(db.Numeric, nullable=True)
    CancelQty_EA       = db.Column(db.Numeric, nullable=True)

    IsOpenForReceivingIncludingUnreleased = db.Column(db.String(10), nullable=True)

    Vendor             = db.Column(db.String(40),  nullable=False)
    VendorName         = db.Column(db.String(255), nullable=True)

    Index              = db.Column(db.String(40),  nullable=True)
    IndexText          = db.Column(db.String(255), nullable=True)
    BusinessArea       = db.Column(db.String(10),  nullable=True)
    BusinessAreaText   = db.Column(db.String(255), nullable=True)

    Requisition        = db.Column(db.String(20),  nullable=True)
    RequisitionLine    = db.Column(db.String(10),  nullable=True)
    PO_RequesterName   = db.Column("PO.RequesterName", db.String(255), nullable=True)

    def __repr__(self):
        return (f"<PO90Day("
                f"PO={self.PO}, Line={self.POLine}, "
                f"Vendor={self.Vendor}, Item={self.Item})>")


#-------------------------------------------------------
# Table Mappings - pre-aggregated / summary tables with that company == '3000' and location like 'P%' or 'I%', non-PLM ItemLink specific
#-------------------------------------------------------
class ItemLocations(db.Model):
    """
    Mapping to PLM.ItemLocations (SQL Server table).
    Holds the canonical (Company, Location) setup for each Item and its Inventory_base_ID.
    Refresh using stored procedure PLM.sp_PLM_MakeItemLocations_FullRefresh
    Currently we only extracted company == '3000' and LocationType of ('Inventory Location', 'Par Location')
    """

    __tablename__ = "ItemLocations"
    # include schema plus explicit UniqueConstraint and Index definitions
    __table_args__ = (
        UniqueConstraint('Location', 'Item', name='UQ_ItemLocations_Location_Item'),
        Index('IX_ItemLocations_Item', 'Item'),
        Index('IX_ItemLocations_Location', 'Location'),
        Index('IX_ItemLocations_LocationType', 'LocationType'),
        {'schema': 'PLM', 'extend_existing': True},
    )

    Inventory_base_ID           = db.Column(db.BIGINT, primary_key=True, nullable=True) # sarrogate PK

    Company                     = db.Column(db.String(10),   nullable=False)
    Location                    = db.Column(db.String(20),   nullable=False)
    LocationText                = db.Column(db.String(255),  nullable=True)
    LocationType                = db.Column(db.String(40),   nullable=True)
    PreferredBin                = db.Column(db.String(40),   nullable=True)

    Item                        = db.Column(db.String(10),   nullable=False)
    ItemDescription             = db.Column(db.String(255),  nullable=True)
    ItemType                    = db.Column(db.String(40),   nullable=True)
    Active                      = db.Column(db.String(5),    nullable=True)
    Discontinued                = db.Column(db.String(5),    nullable=True)
    VendorItem                  = db.Column(db.String(100),  nullable=True)
    ManufacturerNumber          = db.Column(db.String(100),  nullable=True)

    DefaultBuyUOM               = db.Column(db.String(10),   nullable=True)
    BuyUOMMultiplier            = db.Column(db.Numeric,      nullable=True)
    DefaultTransactionUOM       = db.Column(db.String(10),   nullable=True)
    TransactionUOMMultiplier    = db.Column("InventoryTransactionUOMMultiplier", db.Numeric, nullable=True)
    AutomaticPO                 = db.Column(db.String(5),    nullable=True)
    StockUOM                    = db.Column(db.String(10),   nullable=False)
    UOMConversion               = db.Column(db.Numeric,      nullable=True)
    ReorderQuantityCode         = db.Column(db.String(40),   nullable=True)
    ReorderPoint                = db.Column(db.Integer,      nullable=True)

    MaxOrderQty                 = db.Column(db.Integer,      nullable=True)
    MinOrderQty                 = db.Column(db.Integer,      nullable=True)
    OnHandQty                   = db.Column(db.Integer,      nullable=True)
    AvailableQty                = db.Column(db.Integer,      nullable=True)
    OnOrderQty                  = db.Column(db.Integer,      nullable=True)

    UnitCostInStockUOM          = db.Column(db.Numeric,      nullable=True)
    DerivedAverageCost          = db.Column(db.Numeric,      nullable=True)

    report_stamp                = db.Column("report stamp", db.DateTime, nullable=False)
    create_stamp                = db.Column("create stamp", db.DateTime, nullable=False)

    # ----------------------- Relations -----------------------
    def __repr__(self):
        return f"<ItemLocations Item={self.Item} {self.Company}/{self.Location}>"
    

class ItemStartEndDate(db.Model):
    """
    Mapping to PLM.ItemStartEndDate.
    Table holds the transaction start and end date for each (Company, Location, Item).
    To aid in join with other inventory location based table, we also include Inventory_base_ID.
    Refresh using stored procedure PLM.sp_PLM_MakeInvItemStartEndDate_FullRefresh
    We will need to use those date to help calculate burn rates for items.
    Here the Z-date is the date where the item showing zero balance after having a non-zero balance.
    e.g. if we see balance like this : [0,0,5,10,7,3,0,0,0], the start date is the date of [create stamp]
    of the item from ItemLocations, z_date is the the 7th date in the sequence.
    """

    __tablename__ = "ItemStartEndDate"
    __table_args__ = (
        UniqueConstraint('Company', 'Location', 'Item', name='UQ_InvItemStartEndDate_Company_Location_Item'),
        Index('IX_InvItemStartEndDate_Item', 'Item'),
        Index('IX_InvItemStartEndDate_Location', 'Location'),
        Index('IX_InvItemStartEndDate_Company', 'Company'),
        {"schema": "PLM", "extend_existing": True},
    )

    Inventory_base_ID = db.Column(db.BIGINT, primary_key=True, nullable=False) # surrogate PK

    Company        = db.Column(db.String(10), nullable=False)
    Location       = db.Column(db.String(20), nullable=False)
    Item           = db.Column(db.String(10), nullable=False)
    CreateDate     = db.Column("create_date", db.Date, nullable=False)
    ZDate          = db.Column("z_date", db.Date, nullable=False)

    def __repr__(self):
        return f"<PLMItemStartEndDate Location={self.Location} Item={self.Item} Start={self.StartDate} End={self.EndDate}>"
    

class DailyIssueOutQty(db.Model):
    """
    Mapping to PLM.DailyIssueOutQty.
    Built by PLM.sp_PLM_extractDailyIssueOutQty (truncate & reload).
    PK: (Inventory_base_ID, trx_date)
    Unique: (Company, Location, Item, trx_date)
    Indexes: trx_date, item, location, (location, item)
    Currently it extracts past 365 days of data
    """

    __tablename__ = "DailyIssueOutQty"
    __table_args__ = (
        UniqueConstraint('Company', 'Location', 'Item', 'trx_date',
                         name='UQ_DailyIssueOutQty_Company_Location_Item_trxdate'),
        # Indexes
        Index('IX_DailyIssueOutQty_trx_date', 'trx_date'),
        Index('IX_DailyIssueOutQty_item', 'Item'),
        Index('IX_DailyIssueOutQty_location', 'Location'),
        Index('IX_DailyIssueOutQty_location_item', 'Location', 'Item'),
        {"schema": "PLM", "extend_existing": True},
    )

    # Columns
    Inventory_base_ID = db.Column(db.BIGINT, primary_key=True, nullable=False) # surrogate PK
    trx_date       = db.Column(db.Date, nullable=False)

    Company        = db.Column(db.String(10),  nullable=False)
    Location       = db.Column(db.String(20),  nullable=False)
    Item           = db.Column(db.String(10),  nullable=False)

    Lum       = db.Column(db.String(10),  nullable=False)
    QtyInLum  = db.Column(db.Integer)

    CreateDate    = db.Column("create_date", db.Date)
    ZDate         = db.Column("z_date", db.Date)
    existing_days  = db.Column(db.Integer)

    def __repr__(self):
        return (f"<DailyIssueOutQty inv_id={self.Inventory_base_ID} "
                f"item={self.Item} loc={self.Location} date={self.trx_date} "
                f"qty={self.QtyInLum}>")


class ItemLocationsBR(db.Model):
    """
    Mapping to PLM.ItemLocationsBR (SQL Server table).
    Holds (Company, Location, Item) specific pre-calculated 
    1. burn rate at various aggregation frequencies
        (7, 35, 91, 365 days) by 'Inventory Issued' type of transactions
    2. 90-day Purchase Order Qty (EA converted) -- for Inventory Locations
    3. 90-day Requesition Qty (EA converted) -- for Par Locations
    Refresh using stored procedure PLM.sp_PLM_MakeItemLocationsBR_FullRefresh
    Currently the burn is based on z-date
    """
    __tablename__ = "ItemLocationsBR"
    # include schema plus explicit UniqueConstraint and Index definitions
    __table_args__ = (
        UniqueConstraint('Location', 'Item', name='UQ_ItemLocationsBR_Location_Item'),
        Index('IX_ItemLocationsBR_Item', 'Item'),
        Index('IX_ItemLocationsBR_Location', 'Location'),
        Index('IX_ItemLocationsBR_LocationType', 'LocationType'),
        {'schema': 'PLM', 'extend_existing': True},
    )

    Inventory_base_ID    = db.Column(db.BIGINT, primary_key=True, nullable=False)
    LocationType         = db.Column(db.String(40),  nullable=True)
    Company              = db.Column(db.String(10),  nullable=False)
    Location             = db.Column(db.String(20), nullable=False)
    Item                 = db.Column(db.String(255), nullable=False)

    br7                  = db.Column(db.Numeric(17), nullable=True)
    br35                 = db.Column(db.Numeric(17), nullable=True)
    br91                 = db.Column(db.Numeric(17), nullable=True)
    br365                = db.Column(db.Numeric(17), nullable=True)

    issued_count_365     = db.Column(db.Integer, nullable=True)

    OrderQty90_EA        = db.Column(db.Numeric(17), nullable=True)
    ReceivedQty90_EA     = db.Column(db.Numeric(17), nullable=True)
    CancelQty90_EA       = db.Column(db.Numeric(17), nullable=True)
    ReqQty90_EA          = db.Column(db.Numeric(9),  nullable=True)

    def __repr__(self):
        return f"<ItemLocationsBR Item={self.Item} {self.Company}/{self.Location}>"


#-------------------------------------------------------
# View Mappings - PLM ItemLink specific
#-------------------------------------------------------
class PLMZDate(db.Model):
    """
    Mapping to PLM.vw_PLMZDate (SQL Server VIEW).
    View holds the PLM z-date for each pair of PLM ItemLink items (original, replacement)
    Read-only
    """

    __tablename__ = "vw_PLMZDate"
    __table_args__ = {"schema": "PLM", "extend_existing": True}

    # Columns based on provided DB schema
    Inventory_base_ID = db.Column(db.Integer, nullable=True, primary_key=True)  # part of PK
    item_link_id = db.Column(db.BigInteger, nullable=False, primary_key=True)  # part of PK

    Location = db.Column(db.String(255), nullable=True)
    item_group = db.Column("Item Group", db.Integer, nullable=False)
    Item = db.Column(db.String(250), nullable=True)
    LocationType = db.Column(db.String(40), nullable=True)
    Company = db.Column(db.String(10), nullable=True)

    br_calc_type = db.Column("BRCalcType",     db.String(12), nullable=False)
    br_calc_status = db.Column("BRCalcStatus", db.String(12), nullable=False)
    
    days_overlap = db.Column(db.Integer, nullable=True)  # days of O side natural z-date - R side create date (overlap, expect to be negative value if overlapping)
    days_to_start = db.Column(db.Integer, nullable=True) # days of R side create date - (current date go back 365 days), measures when replacement started compared to 1 year

    PLM_Zdate = db.Column("PLM_Zdate", db.Date, nullable=True)

    def __repr__(self):  # pragma: no cover - debug aid
        return (
            f"<PLMZDate PKID={self.PKID} inv_id={self.Inventory_base_ID} "
            f"company={self.Company} loc={self.Location} item={self.Item} "
            f"plm_zdate={self.PLM_Zdate} status={self.br_calc_status}>"
        )
    
#-------------------------------------------------------
# Table Mappings - PLM ItemLink specific (only contains ItemLink items)
#-------------------------------------------------------
class PLMItemGroupBRRoling(db.Model):
    """
    Mapping to PLM.PLMItemGroupBRRolling (SQL Server Table).
    View holds (Company, Location, ItemGroup) specific pre-calculated 
    rolling 7, 60 days burn rate based on DailyIssueOutQty join to available PLM items' Location x ItemGroup
      - this very limited scope is to save some computation time since compute rolling burn rate is expensive
    rolling stop date is up until today
    """

    __tablename__ = "PLMItemGroupBRRolling"
    __table_args__ = (
        UniqueConstraint('Item Group', 'Location', 'Company', name='UQ_PLMItemGroupBRRolling_ItemGroup_Location_Company'),
        Index('IX_PLMItemGroupBRRolling_ItemGroup', 'Item Group'),
        Index('IX_PLMItemGroupBRRolling_Location', 'Location'),
        {'schema': 'PLM', 'extend_existing': True},
    )

    item_group                 = db.Column("Item Group", db.Integer,  nullable=False, primary_key=True)
    Location                   = db.Column(db.String(20),   nullable=False, primary_key=True)
    Company                    = db.Column(db.String(10),   nullable=False)

    LocationType               = db.Column(db.String(40),   nullable=True)

    br_rolling_avg_7           = db.Column("rolling_daily_avg_7", db.Numeric(17), nullable=True)
    br_rolling_avg_60          = db.Column("rolling_daily_avg_60", db.Numeric(17), nullable=True)
    br_rolling_median_7        = db.Column("rolling_daily_median_7", db.Float(8), nullable=True)
    br_rolling_median_60       = db.Column("rolling_daily_median_60", db.Float(8), nullable=True)

    create_stamp               = db.Column("create_ts", db.DateTime, nullable=False)

    def __repr__(self):
        return (f"<PLMItemGroupBRRolling ItemGroup={self.item_group} "
                f"loc={self.Location} br7={self.br_rolling_avg_7} "
                f"br60={self.br_rolling_avg_60}>")

class PLMItemBRRolling(db.Model):
    """
    Mapping to PLM.PLMItemBRRolling (SQL Server Table).
    View holds (Company, Location, Item) specific pre-calculated 
    rolling 7, 60 days burn rate based on DailyIssueOutQty join to available PLM items using their PLM specific Z-date (different from natural z-date)
      - this very limited scope is to save some computation time since compute rolling burn rate is expensive
    rolling stop date is the PLMZdate when applicable (original item z-date exist, replace item create date <= 90 days ago)
    """

    __tablename__ = "PLMItemBRRolling"
    __table_args__ = (
        UniqueConstraint('Inventory_base_ID', 'PKID', name='UQ_PLMItemBRRolling_item_link_id'),
        Index('IX_PLMItemBRRolling_item_link_id', 'PKID'),
        Index('IX_PLMItemBRRolling_InventoryBaseID', 'Inventory_base_ID'),
        Index('IX_PLMItemBRRolling_Item', 'Item'),
        Index('IX_PLMItemBRRolling_Location', 'Location'),
        {'schema': 'PLM', 'extend_existing': True},
    )

    Inventory_base_ID            = db.Column(db.BIGINT, nullable=False, primary_key=True)
    item_link_id                 = db.Column("PKID", db.BIGINT, nullable=False, primary_key=True)

    Company                      = db.Column(db.String(10),  nullable=False)
    Location                     = db.Column(db.String(20),  nullable=False)
    Item                         = db.Column(db.String(10),  nullable=False)

    LocationType                 = db.Column(db.String(40),  nullable=True)
    item_group                   = db.Column("Item Group", db.Integer,  nullable=False)
    side                         = db.Column("Side", db.String(1),  nullable=False) # e.g. 'O', 'R', 'D'
    
    z_date                       = db.Column("z_date", db.Date, nullable=True)  #natural z-date attach to the item
    esixting_days                = db.Column("existing_days", db.Integer, nullable=True)
    z_date_to_use                = db.Column("Z_date_to_use", db.Date, nullable=True) # PLM specific z-date to use for this burn rate calc
    br_calc_status               = db.Column("BRCalcStatus", db.String(12),  nullable=False) # e.g. "Existing", "Pending"
    br_calc_type                 = db.Column("BRCalcType", db.String(12),  nullable=False) # e.g. "ReplaceZCDR", "GroupBR", "KeepZ"
    days_overlap                 = db.Column("days_overlap", db.Integer,  nullable=True) # days overlap between original and replacement item

    br7_rolling_avg              = db.Column("rolling_daily_avg_7", db.Numeric(17), nullable=True)
    br60_rolling_avg             = db.Column("rolling_daily_avg_60", db.Numeric(17), nullable=True)
    br7_rolling_median           = db.Column("rolling_daily_median_7", db.Float(8), nullable=True)
    br60_rolling_median          = db.Column("rolling_daily_median_60", db.Float(8), nullable=True)
    
    create_stamp                 = db.Column("create_ts", db.DateTime, nullable=False)

    def __repr__(self):
        return (f"<PLMItemBRRolling ItemLinkID={self.item_link_id} "
                f"Item={self.Item} loc={self.Location} side={self.side} "
                f"br7={self.br7_rolling_avg} br60={self.br60_rolling_avg}>")



__all__ = ["Item", 
           "ContractItem", 
           "Requesters365Day", 
           "PO90Day",
           "ItemLocations", 
           "ItemLocationsBR",
           "ItemStartEndDate",
           "DailyIssueOutQty",]