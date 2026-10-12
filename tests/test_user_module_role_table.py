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
    assert "CONSTRAINT [CK_UserModuleRole_fillkill_role] CHECK" in ddl
    assert "granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP" in ddl


def test_unknown_fillkill_role_is_rejected_by_the_table(sqlite_app):
    from app import db

    user_id = make_user(sqlite_app, "someone@example.org")
    with sqlite_app.app_context():
        with pytest.raises(IntegrityError):
            db.session.execute(text(
                'INSERT INTO "PLM"."UserModuleRole" (user_id, module, role, granted_at) '
                "VALUES (:uid, 'fillkill', 'boss', CURRENT_TIMESTAMP)"
            ), {"uid": user_id})
        db.session.rollback()

        # Other modules aren't restricted by the Fill/Kill role list.
        db.session.execute(text(
            'INSERT INTO "PLM"."UserModuleRole" (user_id, module, role) '
            "VALUES (:uid, 'othermodule', 'anything')"
        ), {"uid": user_id})
        db.session.commit()
