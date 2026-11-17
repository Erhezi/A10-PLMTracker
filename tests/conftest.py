import re
import sqlite3
import sys
from datetime import date, datetime, time
from pathlib import Path

import pytest

# Dates and times as ISO text in SQLite, as the Fill/Kill queries compare them (Python 3.12+ no
# longer adapts them by default).
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_adapter(datetime, lambda d: d.isoformat(sep=" "))
sqlite3.register_adapter(time, lambda t: t.isoformat())

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def sqlite_app_factory():
    """Build the real app (create_app) on in-memory SQLite, with PLM and FillKill attached as schemas.

    Nothing touches SQL Server, and CSRF protection is on, as in production.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from sqlalchemy.pool import StaticPool

    from app import create_app, db

    def attach_schemas(dbapi_conn, _record):
        if type(dbapi_conn).__module__.startswith("sqlite3"):
            cursor = dbapi_conn.cursor()
            for schema in ("PLM", "FillKill", "OrderTiming"):
                cursor.execute(f"ATTACH DATABASE ':memory:' AS \"{schema}\"")
            cursor.close()

    built = []

    def build(url_prefix=None):
        app = create_app("development", url_prefix=url_prefix, config_overrides={
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "poolclass": StaticPool,
                "connect_args": {"check_same_thread": False},
            },
            "ENABLE_BURN_RATE_REFRESH": False,
            # Order Timing's sample days follow today, some of them 40 days back: no go-live day
            # (tests/test_ordertiming.py sets one where it checks it).
            "ORDERTIMING_FIRST_DAY": None,
        })
        create_fillkill_views(app)
        create_ordertiming_views(app)
        built.append(app)
        return app

    event.listen(Engine, "connect", attach_schemas)
    try:
        yield build
        for app in built:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
    finally:
        event.remove(Engine, "connect", attach_schemas)


@pytest.fixture
def sqlite_app(sqlite_app_factory):
    return sqlite_app_factory()


# The Fill/Kill views exist only on SQL Server (db/fillkill/10-13). On SQLite, tables with the same
# names and columns stand in for them, so the module's SQL runs unchanged.
FILLKILL_VIEWS = {
    "vw_MedlineFillKillQtyAgg": [
        "Order Date", "Sold-To", "Sold-To Name", "Medline Item", "UM", "Customer Item #", "Mfr. Item #",
        "Manufacturer Name", "Total Ordered Qty", "Total Filled Qty", "Total Killed Qty", "Total PO Line Count",
    ],
    "vw_MedlineFillKillItemCollection": [
        "Medline Item", "UM", "Customer Item #", "Mfr. Item #", "Manufacturer Name", "Item.UOMConversion",
        "VendorItem.UOMConversion", "UOM_QOE_VARS", "Medline.Sub", "Medline.ParentItem", "SUB_VARS",
        "Item Description", "Infor Item", "INFOR_ITEM_VARS", "Infor Item Consistency", "Item.Active",
        "Item.Description", "Item.LongDescription", "CommodityCode", "CommodityCode.Description",
    ],
    "vw_MedlineFillKill": [
        "Sold-To", "Sold-To Name", "Ship-To", "Ship-To Name", "Ship-To Name 2", "Order Date", "Order Time",
        "Sales Order #", "Order Line #", "Item", "Customer Item #", "Order Qty", "UM", "Filled Qty", "PO", "POLine",
        "Internal Order Comments from SAP (Z106)", "ReasonTypeText", "Reason", "Reason Date", "Ship-To Code",
    ],
    "vw_FillKillLastLoad": ["last_success", "last_line_update", "last_file"],
    "vw_ContractLineSearch": [
        "vendor_id", "vendor_name", "vendor_item", "vendor_item_stripped", "manufacturer_number",
        "manufacturer_number_stripped", "description", "uom", "qoe", "infor_item", "item_type", "contract",
        "contract_name", "base_cost", "is_mhs",
    ],
    "vw_Vendor": ["vendor_id", "vendor_name", "legal_name", "search_name", "vendor_status"],
    # Empty unless a test adds rows: UOMs stay as typed.
    "vw_UomAlias": ["external_value", "lawson_value"],
}

# Order Timing's views (db/ordertiming/01_views.sql), stood in the same way: the columns the app reads.
ORDERTIMING_VIEWS = {
    "vw_MedlineOrderLine": [
        "Report Date", "Order #", "Order Line", "PO#", "PO", "POLine", "PO Type", "Sold-To #", "Sold-To Name",
        "Ship-To #", "Ship-To Name", "Buyer Name", "Medline Item #", "Cust Item #", "Item # on PO", "Mfr Item #",
        "Manufacturer", "Item Description", "Order Qty", "Open Qty", "Shipped Qty", "UM", "Line Type", "Bad Line",
        "Rej Code", "Received At", "Order Created At", "Confirmed At", "Mins  to Order Create", "Mins to Confirm",
        "ASN Created At", "Line Status", "Short Qty",
    ],
    "vw_OrderTimingLastLoad": ["last_success", "last_line_load", "last_file"],
}

# Infor vendors every Fill/Kill test can use as a sub's vendor ID.
CARDINAL, OWENS, MEDLINE = "1000001", "1000002", "1000931"
TEST_VENDORS = [
    {"vendor_id": CARDINAL, "vendor_name": "CARDINAL HEALTH", "legal_name": "CARDINAL HEALTH 110 LLC",
     "search_name": "CARDINAL HEALTH MEDICAL PRODUCTS", "vendor_status": "Active"},
    {"vendor_id": OWENS, "vendor_name": "OWENS & MINOR", "legal_name": "OWENS & MINOR DISTRIBUTION INC",
     "search_name": "OWENS AND MINOR", "vendor_status": "Active"},
    {"vendor_id": MEDLINE, "vendor_name": "MEDLINE INDUSTRIES INC", "legal_name": "MEDLINE INDUSTRIES LP",
     "search_name": "MEDLINE INDUSTRIES INC", "vendor_status": "Active"},
    {"vendor_id": "1000099", "vendor_name": "OLD SUPPLY CO", "legal_name": "OLD SUPPLY COMPANY",
     "search_name": "OLD SUPPLY CO", "vendor_status": "Inactive"},
]


def create_fillkill_views(app):
    from app import db

    with app.app_context():
        with db.engine.begin() as conn:
            for name, columns in FILLKILL_VIEWS.items():
                cols = ", ".join(f'"{c}"' for c in columns)
                conn.exec_driver_sql(f'CREATE TABLE IF NOT EXISTS "FillKill"."{name}" ({cols})')
    add_view_rows(app, "vw_Vendor", TEST_VENDORS)


def create_ordertiming_views(app):
    from app import db

    with app.app_context():
        with db.engine.begin() as conn:
            for name, columns in ORDERTIMING_VIEWS.items():
                cols = ", ".join(f'"{c}"' for c in columns)
                conn.exec_driver_sql(f'CREATE TABLE IF NOT EXISTS "OrderTiming"."{name}" ({cols})')


def add_view_rows(app, name, rows, schema=None):
    """Insert rows (dicts keyed by column name) into a stand-in view table (in FillKill, or in
    OrderTiming for its views)."""
    from app import db

    schema = schema or ("OrderTiming" if name in ORDERTIMING_VIEWS else "FillKill")
    with app.app_context():
        with db.engine.begin() as conn:
            for row in rows:
                cols = ", ".join(f'"{c}"' for c in row)
                marks = ", ".join("?" for _ in row)
                conn.exec_driver_sql(f'INSERT INTO "{schema}"."{name}" ({cols}) VALUES ({marks})',
                                     tuple(row.values()))


ROLE_PRESETS = {
    # today's user_role -> (user_role, PLM role), as on O2 after 03_unify_roles.sql
    # ('view-only' stays until 04_after_deploy.sql)
    "admin": ("admin", "editor"),
    "user": ("user", "editor"),
    "view-only": ("view-only", "viewer"),
    None: ("user", None),
}

_UNSET = object()


def make_user(app, email, *, role="user", plm=_UNSET, fillkill=(), active=True, password="pw",
              requested=None):
    """Create a user with module roles.

    ``role`` is a preset named after today's roles (see ROLE_PRESETS); ``plm``
    overrides the PLM role (None = no PLM access); ``fillkill`` adds Fill/Kill roles.
    """
    from app import db
    from app.models.auth import User, UserModuleRole

    user_role, plm_role = ROLE_PRESETS[role]
    if plm is not _UNSET:
        plm_role = plm

    with app.app_context():
        user = User(
            email=email,
            name=email.split("@")[0],
            is_active=active,
            requested_modules=requested,
            user_role=user_role,
        )
        user.set_password(password)
        if plm_role:
            user.module_roles.append(UserModuleRole(module="plm", role=plm_role))
        for code in fillkill:
            user.module_roles.append(UserModuleRole(module="fillkill", role=code))
        db.session.add(user)
        db.session.commit()
        return user.user_id


def csrf_from(html: str) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert match, "page has no csrf-token meta tag"
    return match.group(1)


def login(client, email, password="pw", next_path=None):
    """Log in through the real form, CSRF token included."""
    page = client.get("/auth/login")
    data = {"email": email, "password": password, "csrf_token": csrf_from(page.get_data(as_text=True))}
    if next_path is not None:
        data["next"] = next_path
    return client.post("/auth/login", data=data)
