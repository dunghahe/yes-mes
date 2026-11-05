from sqlalchemy import text

from app.core.db import SessionLocal


def test_application_database_role_cannot_update_or_delete_audit_log() -> None:
    with SessionLocal() as db:
        can_update, can_delete = db.execute(
            text(
                "SELECT has_table_privilege(current_user, 'audit_log', 'UPDATE'), "
                "has_table_privilege(current_user, 'audit_log', 'DELETE')"
            )
        ).one()

    assert can_update is False
    assert can_delete is False
