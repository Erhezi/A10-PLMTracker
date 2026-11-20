"""The workflow tables the app creates must match db/fillkill/12_workflow_tables.sql.

If the app starts before the script has run, db.create_all() creates Sub,
SubVendorItem, SubOrder and History from the models, so the models carry the script's
constraint and index names and the same checks. Only the defaults differ: the
app always sets every value, and the script adds any missing default.
"""

import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import mssql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable

SCRIPT = Path(__file__).resolve().parents[1] / "db" / "fillkill" / "12_workflow_tables.sql"


def _model_ddl() -> str:
    from app.models.fillkill import History, ItemInstruction, Sub, SubOrder, VendorItem

    parts = []
    for model in (Sub, VendorItem, SubOrder, History, ItemInstruction):
        parts.append(str(CreateTable(model.__table__).compile(dialect=mssql.dialect())))
        parts += [str(CreateIndex(ix).compile(dialect=mssql.dialect())) for ix in model.__table__.indexes]
    return "\n".join(parts)


def _names(ddl: str) -> set[str]:
    return set(re.findall(r"CONSTRAINT \[(\w+)\]", ddl)) | set(re.findall(r"CREATE (?:UNIQUE )?INDEX \[(\w+)\]", ddl))


def _checks(ddl: str) -> dict[str, str]:
    """CHECK name -> its expression, with brackets, parentheses, spaces and case removed."""
    found = {}
    for match in re.finditer(r"CONSTRAINT \[(\w+)\] CHECK \(", ddl):
        depth, i = 1, match.end()
        while depth:
            depth += {"(": 1, ")": -1}.get(ddl[i], 0)
            i += 1
        expression = ddl[match.end():i - 1]
        found[match.group(1)] = re.sub(r"[\[\]()\s]", "", expression).lower()
    return found


def test_models_and_script_name_the_same_constraints_and_indexes():
    script = SCRIPT.read_text(encoding="utf-8")
    script_names = {n for n in _names(script) if not n.startswith("DF_")}  # defaults: script only
    assert script_names == _names(_model_ddl())


def test_models_and_script_check_the_same_things():
    assert _checks(SCRIPT.read_text(encoding="utf-8")) == _checks(_model_ddl())


def test_identity_keys():
    ddl = _model_ddl()
    assert "sub_id INTEGER NOT NULL IDENTITY" in ddl
    assert "vendor_item_id INTEGER NOT NULL IDENTITY" in ddl
    assert "order_id INTEGER NOT NULL IDENTITY" in ddl
    assert "history_id BIGINT NOT NULL IDENTITY" in ddl


INSERT_SUB = text(
    'INSERT INTO "FillKill"."Sub" (medline_item, reference_sku, status, is_picked, source, '
    "entered_by, create_dt, update_dt) VALUES (:item, :part, :status, :picked, :source, 'me', "
    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
)
INSERT_VENDOR_ITEM = text(
    'INSERT INTO "FillKill"."SubVendorItem" (sub_id, vendor_part, vendor, vendor_id, uom, entered_by, '
    "create_dt, update_dt) VALUES (1, :part, 'V', :vendor_id, :uom, 'me', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
)


@pytest.mark.parametrize("status, picked, source, allowed", [
    ("pending_review", 0, "manual", True),
    ("approved", 1, "medline_pbo", True),
    # Which of Medline's lists a sub came from (2026-11-19).
    ("approved", 0, "medline_autosub", True),
    ("approved", 0, "medline_preferred", True),
    ("pending_review", 0, "medline_possible", True),
    ("hold", 1, "manual", False),        # only an approved sub can be picked
    ("wait", 0, "manual", False),        # renamed to hold
    ("approved", 0, "somewhere", False),
])
def test_sub_table_enforces_its_rules(sqlite_app, status, picked, source, allowed):
    from app import db

    params = {"item": "MDS1", "part": "P1", "status": status, "picked": picked, "source": source}
    with sqlite_app.app_context():
        if allowed:
            db.session.execute(INSERT_SUB, params)
            db.session.commit()
        else:
            with pytest.raises(IntegrityError):
                db.session.execute(INSERT_SUB, params)
            db.session.rollback()


def test_one_live_sub_per_item_and_reference_sku(sqlite_app):
    from app import db

    params = {"item": "MDS1", "part": "P1", "status": "pending_review", "picked": 0, "source": "manual"}
    with sqlite_app.app_context():
        db.session.execute(INSERT_SUB, params)
        db.session.commit()
        with pytest.raises(IntegrityError):
            db.session.execute(INSERT_SUB, params)
        db.session.rollback()


def test_a_void_needs_who_when_and_why(sqlite_app):
    from app import db

    with sqlite_app.app_context():
        db.session.execute(INSERT_SUB, {"item": "MDS1", "part": "P1", "status": "approved", "picked": 1,
                                        "source": "manual"})
        insert = text(
            'INSERT INTO "FillKill"."SubOrder" (sub_id, medline_item, quantity, vendor_part, uom, vendor, ordered_by, '
            "ordered_dt, voided_by, voided_at, void_reason, create_dt, update_dt) VALUES (1, 'MDS1', 5, 'P1', 'BX', "
            "'V', 'me', CURRENT_TIMESTAMP, :by, :at, :why, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        with pytest.raises(IntegrityError):
            db.session.execute(insert, {"by": "me", "at": None, "why": None})
        db.session.rollback()


def test_a_deleted_sub_needs_who_when_and_why_and_doesnt_block_a_new_one(sqlite_app):
    from app import db

    params = {"item": "MDS1", "part": "P1", "status": "pending_review", "picked": 0, "source": "manual"}
    delete = text('UPDATE "FillKill"."Sub" SET deleted_at = CURRENT_TIMESTAMP, deleted_by = :by, '
                  "delete_reason = :why WHERE sub_id = 1")
    with sqlite_app.app_context():
        db.session.execute(INSERT_SUB, params)
        db.session.commit()
        with pytest.raises(IntegrityError):
            db.session.execute(delete, {"by": "me", "why": None})
        db.session.rollback()
        db.session.execute(delete, {"by": "me", "why": "duplicate"})
        db.session.execute(INSERT_SUB, params)  # the same item, vendor and part, live again
        db.session.commit()


def test_one_live_vendor_item_per_sub_vendor_id_vendor_part_and_uom(sqlite_app):
    from app import db

    delete = text('UPDATE "FillKill"."SubVendorItem" SET deleted_at = CURRENT_TIMESTAMP, deleted_by = :by, '
                  "delete_reason = :why WHERE vendor_item_id = 1")
    with sqlite_app.app_context():
        db.session.execute(INSERT_SUB, {"item": "MDS1", "part": "930103", "status": "approved", "picked": 1, "source": "manual"})
        db.session.execute(INSERT_VENDOR_ITEM, {"part": "B-D930103CSZ", "vendor_id": "1000931", "uom": "BX"})
        db.session.execute(INSERT_VENDOR_ITEM, {"part": "B-D930103CS", "vendor_id": "1000931", "uom": "CA"})
        db.session.execute(INSERT_VENDOR_ITEM, {"part": "B-D930103CSZ", "vendor_id": "1017968", "uom": "BX"})
        db.session.commit()
        with pytest.raises(IntegrityError):
            db.session.execute(INSERT_VENDOR_ITEM, {"part": "B-D930103CSZ", "vendor_id": "1000931", "uom": "BX"})
        db.session.rollback()
        with pytest.raises(IntegrityError):  # a vendor item needs its UOM
            db.session.execute(INSERT_VENDOR_ITEM, {"part": "X", "vendor_id": "1000931", "uom": None})
        db.session.rollback()
        with pytest.raises(IntegrityError):  # deleted: who and why
            db.session.execute(delete, {"by": "me", "why": None})
        db.session.rollback()
        db.session.execute(delete, {"by": "me", "why": "no longer sold"})
        db.session.execute(INSERT_VENDOR_ITEM, {"part": "B-D930103CSZ", "vendor_id": "1000931", "uom": "BX"})  # live again
        db.session.commit()
