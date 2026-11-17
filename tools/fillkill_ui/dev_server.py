"""Fill/Kill local UI server: the real app on an in-memory SQLite database, for trying the pages in a
browser and for smoke.mjs. Nothing it does reaches O2 except reads.

    python tools/fillkill_ui/dev_server.py                 # sample data, dated around today
    python tools/fillkill_ui/dev_server.py --data o2       # O2's Fill/Kill data, copied read-only

Then open http://127.0.0.1:5099/dev-login, or /dev-login?as=<who> for one role (see USERS). The
/dev-login route exists only in this script, never in the app, and the server only listens on this
computer. Its database lives in memory: every start is fresh, and nothing is kept.

The views (db/fillkill/10-13, db/ordertiming/01) exist only on SQL Server; tests/conftest.py makes
SQLite tables with their names and columns, which this fills. Order Timing's Main is at /ordertiming/.
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

from conftest import (  # noqa: E402
    FILLKILL_VIEWS, ORDERTIMING_VIEWS, TEST_VENDORS, add_view_rows, create_fillkill_views, create_ordertiming_views,
    make_user,
)

O2 = r"DRIVER={ODBC Driver 17 for SQL Server};SERVER=YNBBSTVWP02\PROCDATASRVPROD;DATABASE=PLM;Trusted_Connection=yes;"

# Who /dev-login?as=<who> signs in: (app role, Fill/Kill roles).
USERS = {
    "all": ("admin", ("sub_finder", "sub_approver", "materials_manager", "scm")),
    "nurse": ("user", ("sub_approver",)),
    "mm": ("user", ("materials_manager",)),
    "scm": ("user", ("scm",)),  # guides the sites' Materials Managers (2026-10-27; "lead" until 11-02)
    "finder": ("user", ("sub_finder",)),
    "viewer": ("user", ("viewer",)),
}


def attach_schemas(dbapi_conn, _record):
    if type(dbapi_conn).__module__.startswith("sqlite3"):
        cur = dbapi_conn.cursor()
        for schema in ("PLM", "FillKill", "OrderTiming"):
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
    create_ordertiming_views(app)
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
    # (days ago, time, site, ship-to, Medline item, UM, ordered, filled, Medline's reason type, comment,
    # Est Avail Date: the Reason Date, 2026-11-16; an Allocated Item line's is its order date)
    kills = [
        (0, "09:12:00", SITE_A, ("INTENS CARE UNIT", "PWLREICU"), "DYND70294BH", "EA", 5, 0, "Backorder",
         "MBO - ERD is 11/18/2026", "2026-11-18"),
        (1, "14:05:00", SITE_B, ("KLAU 6", "PMOSK6"), "DYND70294BH", "EA", 3, 0, "Backorder",
         "NEW USAGE - ETA is 10/30/2026", "2026-10-30"),
        (0, "08:40:00", SITE_A, ("OR", "PWLREO3"), "MDS2585H", "BX", 4, 1, "Allocated Item",
         "Allocation limit has been reached", day(0)),
        (1, "10:30:00", SITE_A, ("INTENS CARE UNIT", "PWLREICU"), "MDS2585HC", "CS", 2, 0, "Custom",
         "CUSTOM ITEM - ETA is 12/01/2026", "2026-12-01"),
        (2, "16:20:00", SITE_B, ("KLAU 6", "PMOSK6"), "SAMPLE0001", "EA", 6, 0, "Disco`d",
         "Discontinued by the manufacturer", None),
    ]
    customer = {row["Medline Item"]: row["Customer Item #"] for row in items}
    lines, qty = [], {}
    for n, (ago, at, (code, name), (ship_to, ship_code), item, um, ordered, filled, reason, comment, avail) in enumerate(
            kills, start=1):
        lines.append({
            "Sold-To": code, "Sold-To Name": name, "Ship-To": code, "Ship-To Name": ship_to,
            "Ship-To Name 2": f"{ship_code} - UBOAT", "Order Date": day(ago),
            "Order Time": at, "Sales Order #": f"S{n:04d}", "Order Line #": "10", "Item": item,
            "Customer Item #": customer[item], "Order Qty": ordered, "UM": um, "Filled Qty": filled,
            "PO": f"26000{n:05d}", "POLine": n, "Internal Order Comments from SAP (Z106)": comment,
            "ReasonTypeText": reason, "Reason": reason, "Reason Date": avail, "Ship-To Code": ship_code,
            "Is Test": 0, "Test Purpose": None,
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
    order_lines = order_timing_rows(today)
    contract = {"vendor_id": "1000001", "vendor_name": "CARDINAL HEALTH", "vendor_item": "88885",
                "vendor_item_stripped": "88885", "manufacturer_number": "N88885", "manufacturer_number_stripped": "N88885",
                "description": "GLOVE EXAM NITRILE MEDIUM", "uom": "BX", "qoe": 100, "infor_item": "200001",
                "item_type": "Itemmast"}
    return {
        "vw_MedlineFillKillItemCollection": items,
        "vw_MedlineFillKill": lines,
        "vw_MedlineFillKillQtyAgg": list(qty.values()),
        "vw_FillKillLastLoad": [{"last_success": now, "last_line_update": now}],
        "vw_MedlineOrderLine": order_lines,
        "vw_OrderTimingLastLoad": [{"last_success": now, "last_line_load": now}],
        # The search groups lines per vendor item and UOM: 88885 BX on two contracts (one MHS's), and
        # a case of it from another vendor on a non-MHS contract only.
        "vw_ContractLineSearch": [
            {**contract, "contract": "C-MHS-1", "contract_name": "Sample MHS contract", "base_cost": 7.5, "is_mhs": "Yes"},
            {**contract, "contract": "C-OTHER-2", "contract_name": "Sample other contract", "base_cost": 7.1, "is_mhs": "No"},
            {**contract, "vendor_id": "1000002", "vendor_name": "OWENS & MINOR", "vendor_item": "88885-CS",
             "vendor_item_stripped": "88885CS", "description": "GLOVE EXAM NITRILE MEDIUM CASE", "uom": "CS", "qoe": 1000,
             "infor_item": "200002", "contract": "C-OTHER-3", "contract_name": "Sample other contract", "base_cost": 70,
             "is_mhs": "No"},
            # ChloraPrep lines as O2 has them (descriptions often run words together): more than
            # the list shows at once, and "930103 chloraprep" finds one.
            # B-D930103CS(Z) is BD's 930103 sold by Medline: a nurse may enter either number.
            *[{"vendor_id": vid, "vendor_name": vname, "vendor_item": part, "vendor_item_stripped": part.replace("-", ""),
               "manufacturer_number": mfr, "manufacturer_number_stripped": mfr, "description": desc, "uom": uom,
               "qoe": qoe, "infor_item": infor, "item_type": "Itemmast" if infor else "Special",
               "contract": "C-CHG", "contract_name": "Sample prep contract", "base_cost": 1, "is_mhs": mhs}
              for vid, vname, part, mfr, desc, uom, qoe, infor, mhs in [
                  ("1000931", "MEDLINE INDUSTRIES INC", "B-D930700", "930700", "APPLICATORCHLORAPREP10.5ML", "CA", 100,
                   "108304", "Yes"),
                  ("1000931", "MEDLINE INDUSTRIES INC", "B-D930415", "930415",
                   "APPLICATOR SKIN PREP CHLORAPREP HI-LITE SWAB 3ML", "CA", 100, None, "Yes"),
                  ("1017968", "MEDLINE INDUSTRIES INC-PHYSICIAN OFFICE-LUM", "B-D930103CS", "930103",
                   "MBO-SWABSTICKSTRIPLE5.25MLCHLORAPREP", "CA", 400, None, "No"),
                  ("1017968", "MEDLINE INDUSTRIES INC-PHYSICIAN OFFICE-LUM", "B-D930103CSZ", "930103",
                   "MBO-SWABSTICKSTRIPLE5.25MLCHLORAPREP", "BX", 40, None, "No"),
                  ("1037888", "MEDLINE INDUSTRIES-JIT HOSPITAL TOTE PROGRAM (WPH-SLC-MMC)", "B-D930400", "930400",
                   "MBO-APPLICATORCHLORAPREP3ML", "CA", 100, "107896", "No"),
                  ("1000307", "BECTON DICKINSON COMPANY INC", "260815", "260815", "CHLORAPREP ONE-STEP 26ML", "CS", 25,
                   None, "Yes"),
                  # The killed cup itself, from Medline: listed, but not a sub of itself (2026-10-20).
                  ("1000931", "MEDLINE INDUSTRIES INC", "DYND70294BH", "DYND70294B", "CUP,DENTURE,8OZ", "EA", 1,
                   "100339", "Yes"),
              ]],
        ],
        # Infor's UOM for one typed another way (MDM_EDI_SUB_UOM), a few of O2's 32.
        "vw_UomAlias": [{"external_value": ext, "lawson_value": infor}
                        for ext, infor in [("CS", "CA"), ("VL", "VI"), ("GL", "GA"), ("BT", "BO"), ("PH", "PK")]],
        # Infor's vendors: the tests' four and a few more, several Cardinal Health ones among them.
        "vw_Vendor": TEST_VENDORS + [
            {"vendor_id": vid, "vendor_name": name, "legal_name": legal, "search_name": search, "vendor_status": status}
            for vid, name, legal, search, status in [
                ("1000307", "BECTON DICKINSON COMPANY INC", "BECTON DICKINSON AND COMPANY", "BD BECTON DICKINSON", "Active"),
                ("1000367", "CARDINAL HEALTH 414 INC DBA NUCLEAR PHARMACY", "CARDINAL HEALTH 414 INC",
                 "CARDINAL HEALTH 414 INC DBA NUCLEAR PHARMACY SERVICES", "Active"),
                ("1000385", "CARDINAL HEALTH DBA CARDINAL PHARMACEUTICAL", "CARDINAL HEALTH 110 LLC", "CARDINAL HEALTH PHARMA",
                 "Active"),
                ("1000557", "CARDINAL HEALTH MEDICAL PRODUCTS", "CARDINAL HEALTH MEDICAL PRODUCTS",
                 "CARDINAL HEALTH MEDICAL PRODUCTS", "Active"),
                ("1001206", "CARDINAL HEALTH -340B", "CARDINAL HEALTH 110 LLC", "CARDINAL HEALTH -340B CARDINAL HEALTH 110 LLC",
                 "Active"),
                ("1000732", "3M HEALTH CARE", "3M COMPANY", "3M HEALTH CARE", "Active"),
                ("1017968", "MEDLINE INDUSTRIES INC-PHYSICIAN OFFICE-LUM", "MEDLINE INDUSTRIES LP",
                 "MEDLINE PHYSICIAN OFFICE", "Active"),
                ("1037888", "MEDLINE INDUSTRIES-JIT HOSPITAL TOTE PROGRAM (WPH-SLC-MMC)", "MEDLINE INDUSTRIES LP",
                 "MEDLINE JIT", "Active"),
            ]
        ],
    }


def order_timing_rows(today: date) -> list[dict]:
    """Order Timing's sample (2026-11-16): six orders over the last ten days, every line status
    among them, five in the last 7 days, which Main opens on; twenty more within the last 30 days
    (26 then: two pages), and one forty days old that Main can't reach."""
    def at(ago, hhmm):
        return f"{(today - timedelta(days=ago)).isoformat()} {hhmm}:00" if hhmm else None

    items = {  # Medline item: (customer item, manufacturer item, manufacturer, description, UM)
        "DYND70294BH": ("100339", "D70294", "MEDLINE", "CUP,DENTURE,8OZ", "CS"),
        "MDS2585H": ("999999", "MDS2585H", "MEDLINE", "GLOVE,EXAM,NITRILE,M", "BX"),
        "B-D930103CS": ("101494", "930103", "BD", "CHLORAPREP APPLICATOR 1ML", "CA"),
        "INVALID PART": ("123456", "XYZ-1", "ACME", "SPONGE,GAUZE,4X4", "CS"),
    }
    # (order, days ago, site, received, confirmed, [(item, qty, shipped, open, status, rej code, ASN)])
    orders = [
        (1, 0, SITE_A, "09:02", "09:06", [
            ("DYND70294BH", 10, 0, 10, "confirmed", None, None),
            ("INVALID PART", 4, 0, None, "rejected", "E1", None),  # a bad line
            ("MDS2585H", 6, 6, None, "asn", None, "12:17"),
        ]),
        (2, 0, SITE_B, "11:55", None, [("B-D930103CS", 2, 0, 2, "not_confirmed", None, None)]),
        (3, 0, SITE_A, "08:15", "08:19", [("MDS2585H", 12, 0, 12, "confirmed", None, None)]),
        (4, 1, SITE_B, "14:30", "14:33", [
            ("DYND70294BH", 3, 2, None, "asn", None, "16:05"),  # one short
            ("B-D930103CS", 1, 0, 1, "confirmed", None, None),
        ]),
        (5, 3, SITE_A, "10:05", "10:09", [("MDS2585H", 20, 20, None, "asn", None, "13:45")]),
        (6, 10, SITE_A, "09:30", "09:34", [("DYND70294BH", 5, 5, None, "asn", None, "12:00")]),
    ]
    # Twenty more over the rest of the last 30 days, so "Last 30 days" has two pages of 20; and one
    # forty days old, past the 30 days Main reaches.
    for k in range(20):
        shipped = k % 4 == 0
        orders.append((7 + k, 8 + k, SITE_B if k % 3 == 0 else SITE_A, "10:00", "10:04", [
            ("MDS2585H" if k % 2 else "DYND70294BH", 4, 4 if shipped else 0, None if shipped else 4,
             "asn" if shipped else "confirmed", None, "13:00" if shipped else None)]))
    orders.append((27, 40, SITE_A, "10:00", "10:04", [("DYND70294BH", 1, 1, None, "asn", None, "13:00")]))
    rows = []
    for number, ago, (code, name), received, confirmed, lines in orders:
        for n, (item, qty, shipped, still_open, status, rej, asn) in enumerate(lines, start=1):
            cust, mfr, maker, description, um = items[item]
            rows.append({
                "Report Date": (today - timedelta(days=ago)).isoformat(), "Order #": f"11483000{number:02d}",
                "Order Line": f"{n * 10:06d}", "PO#": f"30006000{number:02d}-STPO", "PO": f"30006000{number:02d}",
                "POLine": str(n), "PO Type": "EDI", "Sold-To #": code, "Sold-To Name": name, "Ship-To #": "0002464430",
                "Ship-To Name": "4 WEST", "Buyer Name": "Sample, Buyer", "Medline Item #": item, "Cust Item #": cust,
                "Item # on PO": item if item != "INVALID PART" else "ACM-XYZ1", "Mfr Item #": mfr,
                "Manufacturer": maker, "Item Description": description, "Order Qty": qty, "Open Qty": still_open,
                "Shipped Qty": shipped, "UM": um, "Line Type": "STD", "Bad Line": "YES" if rej else None,
                "Rej Code": rej, "Received At": at(ago, received), "Order Created At": at(ago, received),
                "Confirmed At": at(ago, confirmed), "Mins  to Order Create": 2,
                "Mins to Confirm": 4 if confirmed else None, "ASN Created At": at(ago, asn), "Line Status": status,
            })
    return rows


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
    # Order Timing's views are read through the repo's 01_views.sql too (O2 may not have them yet).
    timing = (REPO / "db" / "ordertiming" / "01_views.sql").read_text(encoding="utf-8")

    def view_body(name):
        head = f"CREATE OR ALTER VIEW [OrderTiming].[{name}] AS"
        begin = timing.index(head) + len(head)
        return timing[begin:timing.index("\nGO", begin)].strip().rstrip(";")

    copies = {
        "vw_MedlineFillKillQtyAgg": "SELECT {cols} FROM FillKill.vw_MedlineFillKillQtyAgg",
        "vw_MedlineFillKillItemCollection": "SELECT {cols} FROM FillKill.vw_MedlineFillKillItemCollection",
        "vw_MedlineFillKill": "SELECT {cols} FROM FillKill.vw_MedlineFillKill",
        "vw_FillKillLastLoad": "SELECT {cols} FROM FillKill.vw_FillKillLastLoad",
        "vw_ContractLineSearch": ("SELECT TOP 2000 {cols} FROM (" + contract_sql + ") AS v WHERE vendor_item IN "
                                  "(SELECT DISTINCT Item FROM FillKill.vw_MedlineFillKill) OR description LIKE '%GLOVE%NITRILE%'"),
        "vw_Vendor": ("SELECT {cols} FROM (SELECT Vendor AS vendor_id, VendorName AS vendor_name, LegalName AS legal_name, "
                      "VendorSearchName AS search_name, VendorStatus AS vendor_status "
                      "FROM PLMPreprocessorShared.infor.MDM_VENDOR) AS v"),
        "vw_UomAlias": ("SELECT {cols} FROM (SELECT DISTINCT UPPER(LTRIM(RTRIM(ExternalValue))) AS external_value, "
                        "UPPER(LTRIM(RTRIM(LawsonValue))) AS lawson_value "
                        "FROM PLMPreprocessorShared.infor.MDM_EDI_SUB_UOM) AS v"),
        "vw_MedlineOrderLine": "SELECT {cols} FROM (\n" + view_body("vw_MedlineOrderLine") + "\n) AS v",
        "vw_OrderTimingLastLoad": "SELECT {cols} FROM (\n" + view_body("vw_OrderTimingLastLoad") + "\n) AS v",
    }
    columns = {**FILLKILL_VIEWS, **ORDERTIMING_VIEWS}
    as_defined = ("vw_ContractLineSearch", "vw_Vendor", "vw_UomAlias", "vw_MedlineOrderLine", "vw_OrderTimingLastLoad")
    found = {}
    conn = pyodbc.connect(O2, readonly=True)
    try:
        cur = conn.cursor()
        for name, sql in copies.items():
            if name in as_defined:  # read as 13 (or Order Timing's 01) defines them
                present = set(columns[name])
            else:
                cur.execute("SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?)", f"FillKill.{name}")
                present = {row[0] for row in cur.fetchall()}
            # A column O2's view doesn't have yet (its script not run) comes back empty.
            cols = ", ".join(f"[{c}]" if c in present else f"NULL AS [{c}]" for c in columns[name])
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
    with app.app_context(), db.engine.begin() as conn:  # these vendors instead of the tests' four
        conn.exec_driver_sql('DELETE FROM "FillKill"."vw_Vendor"')
    for name, view_rows in rows.items():
        add_view_rows(app, name, view_rows)
        print(f"{name}: {len(view_rows)} rows")

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
