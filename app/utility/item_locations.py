from __future__ import annotations

from typing import List, Dict

from sqlalchemy import select, union_all, literal

from .. import db
from ..models.inventory import ItemLocationPar, ItemLocationInventory
from ..models.relations import ItemLink


def get_par_table(company: str | None = None, location: str | None = None, require_active: bool = False) -> List[Dict]:
    """
    Returns rows for the 'PAR' table with a 'side' column in {'source','replacement'}.
    """
    Par = ItemLocationPar

    src_q = (
        select(
            literal("source").label("side"),
            ItemLink.item.label("item"),
            ItemLink.replace_item.label("replace_item"),
            Par.Company, Par.Location, Par.StockUOM,
            Par.Active, Par.Discontinued,
            Par.ReqQty_EA,
            Par.issued_count_365,
            Par.report_stamp,
        )
        .select_from(ItemLink)
        .join(Par, Par.Item == ItemLink.item, isouter=False)
    )

    repl_q = (
        select(
            literal("replacement").label("side"),
            ItemLink.item.label("item"),
            ItemLink.replace_item.label("replace_item"),
            Par.Company, Par.Location, Par.StockUOM,
            Par.Active, Par.Discontinued,
            Par.ReqQty_EA,
            Par.issued_count_365,
            Par.report_stamp,
        )
        .select_from(ItemLink)
        .join(Par, Par.Item == ItemLink.replace_item, isouter=False)
    )

    if company:
        src_q = src_q.where(Par.Company == company)
        repl_q = repl_q.where(Par.Company == company)
    if location:
        src_q = src_q.where(Par.Location == location)
        repl_q = repl_q.where(Par.Location == location)
    if require_active:
        # adapt to your data convention
        src_q = src_q.where((Par.Active == "true") | (Par.Active.is_(None)))
        repl_q = repl_q.where((Par.Active == "true") | (Par.Active.is_(None)))

    stmt = union_all(src_q, repl_q)
    return [dict(r._mapping) for r in db.session.execute(stmt).all()]


def get_inventory_table(company: str | None = None, location: str | None = None, require_active: bool = False) -> List[Dict]:
    """
    Returns rows for the 'Inventory' table with a 'side' column in {'source','replacement'}.
    """
    Inv = ItemLocationInventory

    src_q = (
        select(
            literal("source").label("side"),
            ItemLink.item.label("item"),
            ItemLink.replace_item.label("replace_item"),
            Inv.Company, Inv.Location, Inv.StockUOM,
            Inv.OnHandQty, Inv.AvailableQty, Inv.OnOrderQty,
            Inv.UnitCostInStockUOM, Inv.DerivedAverageCost,
            Inv.report_stamp,
        )
        .select_from(ItemLink)
        .join(Inv, Inv.Item == ItemLink.item, isouter=False)
    )

    repl_q = (
        select(
            literal("replacement").label("side"),
            ItemLink.item.label("item"),
            ItemLink.replace_item.label("replace_item"),
            Inv.Company, Inv.Location, Inv.StockUOM,
            Inv.OnHandQty, Inv.AvailableQty, Inv.OnOrderQty,
            Inv.UnitCostInStockUOM, Inv.DerivedAverageCost,
            Inv.report_stamp,
        )
        .select_from(ItemLink)
        .join(Inv, Inv.Item == ItemLink.replace_item, isouter=False)
    )

    if company:
        src_q = src_q.where(Inv.Company == company)
        repl_q = repl_q.where(Inv.Company == company)
    if location:
        src_q = src_q.where(Inv.Location == location)
        repl_q = repl_q.where(Inv.Location == location)
    if require_active:
        src_q = src_q.where((Inv.Active == "true") | (Inv.Active.is_(None)))
        repl_q = repl_q.where((Inv.Active == "true") | (Inv.Active.is_(None)))

    stmt = union_all(src_q, repl_q)
    return [dict(r._mapping) for r in db.session.execute(stmt).all()]


# Example usage in a Flask route (copy into your blueprint/module):
#
# @app.get("/dashboard/item-locations")
# def item_locations_dashboard():
#     company   = request.args.get("company")     # e.g. ?company=MHS
# #   location  = request.args.get("location")    # e.g. ?location=MAIN
#     active    = request.args.get("active") in ("1", "true", "yes")
#
#     par_rows = get_par_table(company=company, location=location, require_active=active)
#     inv_rows = get_inventory_table(company=company, location=location, require_active=active)
#
#     return jsonify({"par": par_rows, "inventory": inv_rows})
