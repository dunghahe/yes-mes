from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy import update as sql_update

from app.core.db import SessionLocal
from app.core.permissions import has_permission
from app.modules.auth.models import AuditLog, User
from app.modules.auth.service import (
    create_login_session,
    resolve_login_session,
    verify_password,
)
from app.modules.users.schemas import PermissionInput, UserCreate, UserUpdate
from app.modules.users.service import (
    ConcurrentUserChange,
    UserManagementError,
    create_user,
    reset_password,
    set_user_permission,
    update_user,
)


def _new_user(db, *, role: str = "admin", username: str | None = None) -> User:
    user = User(
        username=username or f"users-test-{uuid4().hex}",
        display_name="Admin thử nghiệm",
        password_hash="$2b$12$J8j07.GUFqUX1O4nEUokquq3ukpxnrmvKgb65UfA8wpbpgLfsXMou",
        role=role,
        must_change_password=False,
        password_changed_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()
    return user


def test_create_user_generates_temporary_password_and_audits_without_secret() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _new_user(db)
        user, temporary_password = create_user(
            db,
            UserCreate(username="new.operator", display_name="Người nhập liệu", role="data_entry"),
            actor.id,
        )
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.table_name == "users", AuditLog.record_id == user.id)
            .order_by(AuditLog.id.desc())
        )

        assert user.must_change_password
        assert user.is_active
        assert user.role == "data_entry"
        assert verify_password(temporary_password, user.password_hash)
        assert len(temporary_password) >= 24
        assert audit.actor_id == actor.id
        assert temporary_password not in str(audit.old_values)
        assert temporary_password not in str(audit.new_values)
    finally:
        db.rollback()
        db.close()


def test_create_user_rejects_duplicate_active_username() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _new_user(db)
        data = UserCreate(username="same-login", display_name="Một", role="planning")
        create_user(db, data, actor.id)
        with pytest.raises(UserManagementError, match="đã được sử dụng"):
            create_user(
                db,
                UserCreate(username="same-login", display_name="Hai", role="warehouse"),
                actor.id,
            )
    finally:
        db.rollback()
        db.close()


def test_account_updates_block_self_lock_and_preserve_last_active_admin() -> None:
    db = SessionLocal()
    try:
        db.begin()
        db.execute(sql_update(User).where(User.role == "admin").values(is_active=False))
        first_admin = _new_user(db, username=f"admin-one-{uuid4().hex}")
        second_admin = _new_user(db, username=f"admin-two-{uuid4().hex}")

        with pytest.raises(UserManagementError, match="không thể tự khóa"):
            update_user(
                db,
                UserUpdate(
                    username=first_admin.username,
                    display_name=first_admin.display_name,
                    role="admin",
                    is_active=False,
                    version=first_admin.version,
                ),
                first_admin.id,
                first_admin.id,
            )

        update_user(
            db,
            UserUpdate(
                username=second_admin.username,
                display_name=second_admin.display_name,
                role="manager",
                is_active=True,
                version=second_admin.version,
            ),
            first_admin.id,
            second_admin.id,
        )
        with pytest.raises(UserManagementError, match="Admin hoạt động cuối cùng"):
            update_user(
                db,
                UserUpdate(
                    username=first_admin.username,
                    display_name=first_admin.display_name,
                    role="manager",
                    is_active=True,
                    version=first_admin.version,
                ),
                first_admin.id,
                first_admin.id,
            )
    finally:
        db.rollback()
        db.close()


def test_user_optimistic_version_blocks_stale_update() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _new_user(db)
        target = _new_user(db, role="planning")
        first_update = UserUpdate(
            username=target.username,
            display_name="Tên mới",
            role="planning",
            is_active=True,
            version=target.version,
        )
        update_user(db, first_update, actor.id, target.id)
        with pytest.raises(ConcurrentUserChange):
            update_user(db, first_update, actor.id, target.id)
    finally:
        db.rollback()
        db.close()


def test_password_reset_revokes_sessions_and_requires_change() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _new_user(db)
        target = _new_user(db, role="planning")
        old_token, old_session = create_login_session(db, target.id)

        temporary_password = reset_password(db, actor.id, target.id)

        assert verify_password(temporary_password, target.password_hash)
        assert not verify_password("password-incorrect", target.password_hash)
        assert target.must_change_password
        assert old_session.revoked_at is not None
        assert resolve_login_session(db, old_token) is None
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.table_name == "users", AuditLog.record_id == target.id)
            .order_by(AuditLog.id.desc())
        )
        assert temporary_password not in str(audit.new_values)
    finally:
        db.rollback()
        db.close()


def test_permission_additions_require_view_and_are_additive() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _new_user(db)
        target = _new_user(db, role="planning")
        with pytest.raises(UserManagementError, match="phải đi kèm quyền xem"):
            set_user_permission(
                db,
                target.id,
                PermissionInput(module="qc", can_edit=True),
                actor.id,
            )

        permission = set_user_permission(
            db,
            target.id,
            PermissionInput(module="qc", can_view=True, can_edit=True),
            actor.id,
        )
        assert permission is not None
        extras = frozenset({("qc", "view"), ("qc", "edit")})
        assert has_permission(target.role, "orders", "edit", extras)
        assert has_permission(target.role, "qc", "edit", extras)
        assert not has_permission(target.role, "qc", "delete", extras)

        set_user_permission(
            db,
            target.id,
            PermissionInput(module="qc", version=permission.version),
            actor.id,
        )
        assert permission.deleted_at is not None
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.table_name == "user_permissions", AuditLog.record_id == permission.id)
            .order_by(AuditLog.id.desc())
        )
        assert audit.actor_id == actor.id
    finally:
        db.rollback()
        db.close()
