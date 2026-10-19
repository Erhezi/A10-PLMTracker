"""Fill/Kill local UI server: the real app on an in-memory SQLite database, for trying the pages in a
browser and for smoke.mjs. Nothing it does reaches O2 except reads.

    python tools/fillkill_ui/dev_server.py                 # sample data, dated around today
    python tools/fillkill_ui/dev_server.py --data o2       # O2's Fill/Kill data, copied read-only

Then open http://127.0.0.1:5099/dev-login, or /dev-login?as=<who> for one role (see USERS). The
/dev-login route exists only in this script, never in the app, and the server only listens on this
computer. Its database lives in memory: every start is fresh, and nothing is kept.

The views (db/fillkill/10-13) exist only on SQL Server; tests/conftest.py makes SQLite tables with
their names and columns, which this fills.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "tests")]

from flask import redirect, request  # noqa: E402
from flask_login import login_user, logout_user  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from conftest import FILLKILL_VIEWS, TEST_VENDORS, add_view_rows, create_fillkill_views, make_user  # noqa: E402

O2 = r"DRIVER={ODBC Driver 17 for SQL Server};SERVER=YNBBSTVWP02\PROCDATASRVPROD;DATABASE=PLM;Trusted_Connection=yes;"

# Who /dev-login?as=<who> signs in: (app role, Fill/Kill roles).
USERS = {
    "all": ("admin", ("sub_finder", "sub_approver", "materials_manager")),
    "nurse": ("user", ("sub_approver",)),
    "mm": ("user", ("materials_manager",)),
    "finder": ("user", ("sub_finder",)),
    "viewer": ("user", ("viewer",)),
}


def attach_schemas(dbapi_conn, _record):
    if type(dbapi_conn).__module__.startswith("sqlite3"):
        cur = dbapi_conn.cursor()
        for schema in ("PLM", "FillKill"):
            cur.execute(f"ATTACH DATABASE ':memory:' AS \"{schema}\"")
        cur.close()


def make_app():
    from app import create_app

    event.listen(Engine, "connect", attach_schemas)
    app = create_app("development", config_overrides={
        "SECRET_KEY": "fillkill-dev-server",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        # One shared connection: an in-memory database lives only as long as its connection.
        "SQLALCHEMY_ENGINE_OPTIONS": {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}},
        "ENABLE_BURN_RATE_REFRESH": False,
    })
    create_fillkill_views(app)
    return app


# --- sample data ---------------------------------------------------------------------------

SITE_A, SITE_B = ("0000000001", "SAMPLE SITE A"), ("0000000002", "SAMPLE SITE B")


def sample_rows(today: date) -> dict[str, list[dict]]:
    """A few kill lines over the last three days: an item with one UOM, an Infor item with two
    (Medline's customer item differing on one), and an item that isn't in Infor."""
    day = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
    items = [
        {"Medline Item": "DYND70294BH", "UM": "EA", "Customer Item #": "100339", "Item Description": "CUP,DENTURE,8OZ",
         "Infor Item": "100339", "Infor Item Consistency": 1, "Item.UOMConversion": 1, "Item.Active": "Yes",
         "Item.LongDescription": "CUP DENTURE 8 OZ", "CommodityCode": "4214-15-01",
         "CommodityCode.Description": "PATIENT CARE CUPS"},
        {"Medline Item": "MDS2585H", "UM": "BX", "Customer Item #": "MDS2585H", "Item Description": "GLOVE,EXAM,NITRILE,M",
         "Infor Item": "999999", "Infor Item Consistency": 0, "Item.UOMConversion": 100, "Item.Active": "Yes",
         "Item.LongDescription": "GLOVE EXAM NITRILE MEDIUM", "CommodityCode": "4213-22-03",
         "CommodityCode.Description": "MEDICAL EXAM GLOVES"},
        {"Medline Item": "MDS2585HC", "UM": "CS", "Customer Item #": "999999", "Item Description": "GLOVE,EXAM,NITRILE,M,CS",
         "Infor Item": "999999", "Infor Item Consistency": 1, "Item.UOMConversion": 1000, "Item.Active": "Yes",
         "Item.LongDescription": "GLOVE EXAM NITRILE MEDIUM", "CommodityCode": "4213-22-03",
         "CommodityCode.Description": "MEDICAL EXAM GLOVES"},
        {"Medline Item": "SAMPLE0001", "UM": "EA", "Customer Item #": "SAMPLE0001", "Item Description": "SAMPLE,NOT IN INFOR",
         "Infor Item": None, "Infor Item Consistency": 0},
    ]
    # (days ago, time, site, Medline item, UM, ordered, filled, reason, comment)
    kills = [
        (0, "09:12:00", SITE_A, "DYND70294BH", "EA", 5, 0, "MBO", "MBO - ERD is 11/18/2026"),
        (1, "14:05:00", SITE_B, "DYND70294BH", "EA", 3, 0, "OUT_OF_STOCK", "OUT OF STOCK - ETA is 10/30/2026"),
        (0, "08:40:00", SITE_A, "MDS2585H", "BX", 4, 1, "ALLOCATION", "Allocation limit has been reached"),
        (1, "10:30:00", SITE_A, "MDS2585HC", "CS", 2, 0, "MBO", "MBO - ERD is 12/01/2026"),
        (2, "16:20:00", SITE_B, "SAMPLE0001", "EA", 6, 0, "DISCONTINUED", "Discontinued by the manufacturer"),
    ]
    customer = {row["Medline Item"]: row["Customer Item #"] for row in items}
    lines, qty = [], {}
    for n, (ago, at, (code, name), item, um, ordered, filled, reason, comment) in enumerate(kills, start=1):
        lines.append({
            "Sold-To": code, "Sold-To Name": name, "Ship-To": code, "Ship-To Name": "4 WEST", "Order Date": day(ago),
            "Order Time": at, "Sales Order #": f"S{n:04d}", "Order Line #": "10", "Item": item,
            "Customer Item #": customer[item], "Order Qty": ordered, "UM": um, "Filled Qty": filled,
            "PO": f"26000{n:05d}", "POLine": n, "Internal Order Comments from SAP (Z106)": comment, "Reason": reason,
            "Reason Date": None, "Is Test": 0, "Test Purpose": None,
        })
        key = (day(ago), code, item, um)
        row = qty.setdefault(key, {"Order Date": day(ago), "Sold-To": code, "Sold-To Name": name, "Medline Item": item,
                                   "UM": um, "Customer Item #": customer[item], "Total Ordered Qty": 0,
                                   "Total Filled Qty": 0, "Total Killed Qty": 0, "Total PO Line Count": 0})
        row["Total Ordered Qty"] += ordered
        row["Total Filled Qty"] += filled
        row["Total Killed Qty"] += ordered - filled
        row["Total PO Line Count"] += 1
    now = datetime.combine(today, time(9, 30)).isoformat(sep=" ")
    contract = {"vendor_id": "1000001", "vendor_name": "CARDINAL HEALTH", "vendor_item": "88885",
                "vendor_item_stripped": "88885", "manufacturer_number": "N88885", "manufacturer_number_stripped": "N88885",
                "description": "GLOVE EXAM NITRILE MEDIUM", "uom": "BX", "qoe": 100, "infor_item": "200001",
                "item_type": "Itemmast"}
    return {
        "vw_MedlineFillKillItemCollection": items,
        "vw_MedlineFillKill": lines,
        "vw_MedlineFillKillQtyAgg": list(qty.values()),
        "vw_FillKillLastLoad": [{"last_success": now, "last_line_update": now}],
        # The search groups lines per vendor item and UOM: 88885 BX on two contracts (one MHS's), and
        # a case of it from another vendor on a non-MHS contract only.
        "vw_ContractLineSearch": [
            {**contract, "contract": "C-MHS-1", "contract_name": "Sample MHS contract", "base_cost": 7.5, "is_mhs": "Yes"},
            {**contract, "contract": "C-OTHER-2", "contract_name": "Sample other contract", "base_cost": 7.1, "is_mhs": "No"},
            {**contract, "vendor_id": "1000002", "vendor_name": "OWENS & MINOR", "vendor_item": "88885-CS",
             "vendor_item_stripped": "88885CS", "description": "GLOVE EXAM NITRILE MEDIUM CASE", "uom": "CS", "qoe": 1000,
             "infor_item": "200002", "contract": "C-OTHER-3", "contract_name": "Sample other contract", "base_cost": 70,
             "is_mhs": "No"},
        ],
    }


# --- O2, read-only -------------------------------------------------------------------------

def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, bool):
        return int(value)
    return value


def o2_rows() -> dict[str, list[dict]]:
    """O2's Fill/Kill views, read with your Windows login on a read-only connection. The contract
    search is read through the repo's 13_contract_search.sql, so a column it adds shows before 13
    runs on O2; it is limited to vendor items Medline has killed plus nitrile gloves, to stay small."""
    import pyodbc

    script = (REPO / "db" / "fillkill" / "13_contract_search.sql").read_text(encoding="utf-8")
    head = "CREATE OR ALTER VIEW [FillKill].[vw_ContractLineSearch] AS"
    start = script.index(head) + len(head)
    contract_sql = script[start:script.index("\nGO", start)].strip().rstrip(";")
    copies = {
        "vw_MedlineFillKillQtyAgg": "SELECT {cols} FROM FillKill.vw_MedlineFillKillQtyAgg",
        "vw_MedlineFillKillItemCollection": "SELECT {cols} FROM FillKill.vw_MedlineFillKillItemCollection",
        "vw_MedlineFillKill": "SELECT {cols} FROM FillKill.vw_MedlineFillKill",
        "vw_FillKillLastLoad": "SELECT {cols} FROM FillKill.vw_FillKillLastLoad",
        "vw_ContractLineSearch": ("SELECT TOP 2000 {cols} FROM (" + contract_sql + ") AS v WHERE vendor_item IN "
                                  "(SELECT DISTINCT Item FROM FillKill.vw_MedlineFillKill) OR description LIKE '%GLOVE%NITRILE%'"),
        "vw_Vendor": ("SELECT {cols} FROM (SELECT Vendor AS vendor_id, VendorName AS vendor_name, "
                      "VendorStatus AS vendor_status FROM PLMPreprocessorShared.infor.MDM_VENDOR) AS v"),
    }
    found = {}
    conn = pyodbc.connect(O2, readonly=True)
    try:
        cur = conn.cursor()
        for name, sql in copies.items():
            if name in ("vw_ContractLineSearch", "vw_Vendor"):  # read as 13 defines them
                present = set(FILLKILL_VIEWS[name])
            else:
                cur.execute("SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?)", f"FillKill.{name}")
                present = {row[0] for row in cur.fetchall()}
            # A column O2's view doesn't have yet (its script not run) comes back empty.
            cols = ", ".join(f"[{c}]" if c in present else f"NULL AS [{c}]" for c in FILLKILL_VIEWS[name])
            cur.execute(sql.format(cols=cols))
            names = [d[0] for d in cur.description]
            found[name] = [{k: _plain(v) for k, v in zip(names, row)} for row in cur.fetchall()]
    finally:
        conn.rollback()
        conn.close()
    return found


# --- the server ----------------------------------------------------------------------------

def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", choices=("sample", "o2"), default="sample",
                        help="sample: made-up kill lines around today (default); o2: O2's, read-only")
    parser.add_argument("--port", type=int, default=5099)
    args = parser.parse_args(argv)

    from app import db
    from app.models import now_ny_naive
    from app.models.auth import User
    from app.utility import session_policy

    app = make_app()
    rows = o2_rows() if args.data == "o2" else sample_rows(now_ny_naive().date())
    if "vw_Vendor" in rows:  # Infor's vendors instead of the tests' four
        with app.app_context(), db.engine.begin() as conn:
            conn.exec_driver_sql('DELETE FROM "FillKill"."vw_Vendor"')
    for name, view_rows in rows.items():
        add_view_rows(app, name, view_rows)
        print(f"{name}: {len(view_rows)} rows")
    if args.data == "sample":
        print(f"vw_Vendor: {len(TEST_VENDORS)} rows (the tests')")

    user_ids = {who: make_user(app, f"{who}@example.org", role=role, plm=None, fillkill=roles)
                for who, (role, roles) in USERS.items()}

    @app.route("/dev-login")
    def dev_login():
        who = request.args.get("as", "all")
        if who not in user_ids:
            return f"Unknown user {who!r}: one of {', '.join(user_ids)}", 404
        logout_user()
        login_user(db.session.get(User, user_ids[who]))
        session_policy.mark_login()
        target = request.args.get("next") or ""
        return redirect(target if target.startswith("/") and not target.startswith("//") else "/fillkill/")

    print(f"Open http://127.0.0.1:{args.port}/dev-login (or ?as={'|'.join(USERS)})", flush=True)
    # One request at a time: the in-memory database is a single shared connection.
    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False, threaded=False)


if __name__ == "__main__":
    main()
