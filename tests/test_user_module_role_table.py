"""The table the app creates must match db/fillkill/02_user_module_role.sql.

If the app starts before the script has run, db.create_all() creates
PLM.UserModuleRole from the model, so the model carries the script's
constraint names, the cascade and the role CHECK.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import mssql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from conftest import make_user


def test_model_ddl_matches_the_script():
    from app.models.auth import UserModuleRole

    ddl = str(CreateTable(UserModuleRole.__table__).compile(dialect=mssql.dialect()))
    assert "CONSTRAINT [PK_UserModuleRole] PRIMARY KEY (user_id, module, role)" in ddl
    assert "CONSTRAINT [FK_UserModuleRole_users] FOREIGN KEY(user_id) REFERENCES [PLM].users (user_id) ON DELETE CASCADE" in ddl
    assert "CONSTRAINT [CK_UserModuleRole_role] CHECK" in ddl
    assert "(module = 'plm' AND role IN ('viewer', 'editor'))" in ddl
    assert "granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP" in ddl


def test_model_index_allows_one_plm_role_per_user():
    from app.models.auth import UserModuleRole
    from sqlalchemy.schema import CreateIndex

    (index,) = [i for i in UserModuleRole.__table__.indexes if i.name == "UX_UserModuleRole_one_plm_role"]
    ddl = str(CreateIndex(index).compile(dialect=mssql.dialect()))
    assert "CREATE UNIQUE INDEX [UX_UserModuleRole_one_plm_role]" in ddl
    assert "WHERE module = 'plm'" in ddl


@pytest.mark.parametrize("module, role, allowed", [
    ("app", "admin", False),  # admin is users.user_role, not a module role
    ("plm", "editor", True),
    ("plm", "admin", False),
    ("fillkill", "materials", True),
    ("fillkill", "boss", False),
    ("othermodule", "anything", False),
])
def test_table_accepts_only_known_roles_per_module(sqlite_app, module, role, allowed):
    from app import db

    user_id = make_user(sqlite_app, "someone@example.org", role=None)
    insert = text(
        'INSERT INTO "PLM"."UserModuleRole" (user_id, module, role) VALUES (:uid, :module, :role)'
    )
    with sqlite_app.app_context():
        if allowed:
            db.session.execute(insert, {"uid": user_id, "module": module, "role": role})
            db.session.commit()
        else:
            with pytest.raises(IntegrityError):
                db.session.execute(insert, {"uid": user_id, "module": module, "role": role})
            db.session.rollback()


def test_table_refuses_a_second_plm_role(sqlite_app):
    from app import db

    user_id = make_user(sqlite_app, "someone@example.org", role="view-only")
    with sqlite_app.app_context():
        with pytest.raises(IntegrityError):
            db.session.execute(text(
                'INSERT INTO "PLM"."UserModuleRole" (user_id, module, role) VALUES (:uid, :module, :role)'
            ), {"uid": user_id, "module": "plm", "role": "editor"})
        db.session.rollback()
