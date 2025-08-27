from __future__ import annotations

from .. import db
from sqlalchemy.orm import relationship, foreign
from sqlalchemy import and_, or_, Index, UniqueConstraint


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
    
class Requesters365Day(db.Model):
    """
    Mapping to PLM.vw_vw_365Day_Requesters (SQL Server VIEW).
    """

    __tablename__ = "vw_vw_365Day_Requesters"
    __table_args__ = {"schema": "PLM"}

    # no natural PK in your schema, so we mark all columns as nullable
    # and rely on SQLAlchemy's requirement for *some* PK surrogate.
    RequestingLocation = db.Column(db.String(40),  primary_key=True, nullable=True)
    Item               = db.Column(db.String(100), primary_key=True, nullable=True)
    Requester          = db.Column(db.String(20),  primary_key=True, nullable=True)

    RequesterName      = db.Column(db.String(100), nullable=True)
    Requisition_FD5    = db.Column("Requisition.FD5", db.String(150), nullable=True)
    EmailAddress       = db.Column(db.String(450), nullable=True)

    def __repr__(self):
        return (f"<Requesters365Day("
                f"Requester={self.Requester!r}, "
                f"Item={self.Item!r}, "
                f"Location={self.RequestingLocation!r})>")


class PO90Day(db.Model):
    """
    Mapping to PLM.vw_90Day_PO (SQL Server VIEW).
    """

    __tablename__ = "vw_90Day_PO"
    __table_args__ = {"schema": "PLM"}

    POReleaseDate      = db.Column(db.Date, primary_key = True, nullable=True)
    PO                 = db.Column(db.String(20),  primary_key=True, nullable=False)
    POLine             = db.Column(db.String(10),  primary_key=True, nullable=False)
    PurchaseOrderLine  = db.Column(db.String(10),  nullable=False)

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



class ItemLocations(db.Model):
    """
    Mapping to PLM.vw_ItemLocations (SQL Server table).
    Holds the canonical (Company, Location) setup for each Item and its Inventory_base_ID.
    """

    __tablename__ = "ItemLocations"
    # include schema plus explicit UniqueConstraint and Index definitions
    __table_args__ = (
        UniqueConstraint('Location', 'Item', name='UQ_ItemLocations_Location_Item'),
        Index('IX_ItemLocations_Item', 'Item'),
        Index('IX_ItemLocations_Location', 'Location'),
        {'schema': 'PLM'},
    )

    Inventory_base_ID   = db.Column(db.BIGINT, primary_key=True, nullable=True) # sarrogate PK

    Company             = db.Column(db.String(10),   nullable=False)
    Location            = db.Column(db.String(20),   nullable=False)
    LocationText        = db.Column(db.String(255),  nullable=True)
    LocationType        = db.Column(db.String(40),   nullable=True)
    PreferredBin        = db.Column(db.String(40),   nullable=True)

    Item                = db.Column(db.String(10),   nullable=False)
    ItemDescription     = db.Column(db.String(255),  nullable=True)
    ItemType            = db.Column(db.String(40),   nullable=True)
    Active              = db.Column(db.String(5),    nullable=True)
    Discontinued        = db.Column(db.String(5),    nullable=True)
    VendorItem          = db.Column(db.String(100),  nullable=True)

    defaultBuyUOM       = db.Column(db.String(20),   nullable=True)
    BuyUOMMultiplier    = db.Column(db.Numeric,      nullable=True)
    AutomaticPO         = db.Column(db.String(5),    nullable=True)
    StockUOM            = db.Column(db.String(20),   nullable=False)
    UOMConversion       = db.Column(db.Numeric,      nullable=True)
    ReorderQuantityCode = db.Column(db.String(40),   nullable=True)
    ReorderPoint        = db.Column(db.Integer,      nullable=True)

    MaxOrderQty         = db.Column(db.Integer,      nullable=True)
    MinOrderQty         = db.Column(db.Integer,      nullable=True)
    OnHandQty           = db.Column(db.Integer,      nullable=True)
    AvailableQty        = db.Column(db.Integer,      nullable=True)
    OnOrderQty          = db.Column(db.Integer,      nullable=True)

    UnitCostInStockUOM  = db.Column(db.Numeric,      nullable=True)
    DerivedAverageCost  = db.Column(db.Numeric,      nullable=True)

    report_stamp        = db.Column("report stamp", db.DateTime, nullable=False)

    # ----------------------- Relations -----------------------


    def __repr__(self):
        return f"<ItemLocations Item={self.Item} {self.Company}/{self.Location}>"

__all__ = ["Item", 
           "ContractItem", 
           "ItemLocations", 
           "Requesters365Day", 
           "PO90Day"]