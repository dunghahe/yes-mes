import secrets
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog, User
from app.modules.auth.service import hash_password, revoke_user_sessions
from app.modules.users.models import UserPermission
from app.modules.users.schemas import PermissionInput, UserCreate, UserUpdate


class UserManagementError(Exception):
    """A user management rule rejected the requested change."""


class ConcurrentUserChange(UserManagementError):
    """The record changed since the administrator loaded it."""


def create_user(db: Session, data: UserCreate, actor_id: int) -> tuple[User, str]:
    _require_admin_actor(db, actor_id)
    username = data.username.strip()
    if db.scalar(select(User.id).where(User.username == username, User.deleted_at.is_(None))):
        raise UserManagementError("Tên đăng nhập này đã được sử dụng.")

    temporary_password = secrets.token_urlsafe(18)
    user = User(
        username=username,
        display_name=data.display_name.strip(),
        password_hash=hash_password(temporary_password),
        role=data.role,
        is_active=True,
        must_change_password=True,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(user)
    db.flush()
    _write_audit(
        db,
        actor_id=actor_id,
        user_id=user.id,
        action="create",
        old_values=None,
        new_values=_user_values(user),
        reason="Admin tạo tài khoản",
    )
    return user, temporary_password


def update_user(db: Session, data: UserUpdate, actor_id: int, target_id: int) -> User:
    _require_admin_actor(db, actor_id)
    user = _load_user_for_update(db, target_id)
    if user.version != data.version:
        raise ConcurrentUserChange("Tài khoản đã được thay đổi. Hãy tải lại trang rồi thử lại.")
    if data.username != user.username and db.scalar(
        select(User.id).where(
            User.username == data.username,
            User.deleted_at.is_(None),
            User.id != user.id,
        )
    ):
        raise UserManagementError("Tên đăng nhập này đã được sử dụng.")

    if actor_id == user.id and user.is_active and not data.is_active:
        raise UserManagementError("Bạn không thể tự khóa tài khoản của mình.")
    if user.is_active and user.role == "admin" and (not data.is_active or data.role != "admin"):
        _ensure_another_active_admin(db, user.id)

    old_values = _user_values(user)
    changed_access = user.role != data.role or user.is_active != data.is_active
    user.username = data.username
    user.display_name = data.display_name
    user.role = data.role
    user.is_active = data.is_active
    user.updated_at = datetime.now(UTC)
    user.updated_by = actor_id
    user.version += 1
    if changed_access:
        revoke_user_sessions(db, user.id)
    _write_audit(
        db,
        actor_id=actor_id,
        user_id=user.id,
        action="update",
        old_values=old_values,
        new_values=_user_values(user),
        reason="Admin cập nhật tài khoản, vai trò hoặc trạng thái",
    )
    return user


def reset_password(db: Session, actor_id: int, target_id: int) -> str:
    _require_admin_actor(db, actor_id)
    user = _load_user_for_update(db, target_id)
    temporary_password = secrets.token_urlsafe(18)
    old_values = {"must_change_password": user.must_change_password}
    user.password_hash = hash_password(temporary_password)
    user.must_change_password = True
    user.password_changed_at = datetime.now(UTC)
    user.failed_login_count = 0
    user.locked_until = None
    user.version += 1
    user.updated_at = datetime.now(UTC)
    user.updated_by = actor_id
    revoke_user_sessions(db, user.id)
    _write_audit(
        db,
        actor_id=actor_id,
        user_id=user.id,
        action="update",
        old_values=old_values,
        new_values={"must_change_password": True},
        reason="Admin đặt lại mật khẩu; mật khẩu tạm không ghi vào nhật ký",
    )
    return temporary_password


def set_user_permission(
    db: Session,
    target_id: int,
    data: PermissionInput,
    actor_id: int,
) -> UserPermission | None:
    _require_admin_actor(db, actor_id)
    user = _load_user_for_update(db, target_id)
    if (data.can_create or data.can_edit or data.can_delete) and not data.can_view:
        raise UserManagementError("Quyền thêm, sửa hoặc xóa phải đi kèm quyền xem.")

    permission = db.scalar(
        select(UserPermission)
        .where(
            UserPermission.user_id == target_id,
            UserPermission.module == data.module,
            UserPermission.deleted_at.is_(None),
        )
        .with_for_update()
    )
    current_version = permission.version if permission else 0
    if current_version != data.version:
        raise ConcurrentUserChange("Quyền tài khoản đã được thay đổi. Hãy tải lại trang.")

    new_values = {
        "user_id": user.id,
        "module": data.module,
        "can_view": data.can_view,
        "can_create": data.can_create,
        "can_edit": data.can_edit,
        "can_delete": data.can_delete,
    }
    if permission is None and not any(
        (data.can_view, data.can_create, data.can_edit, data.can_delete)
    ):
        return None

    now = datetime.now(UTC)
    if permission is None:
        permission = UserPermission(
            **{
                **new_values,
                "created_by": actor_id,
                "updated_by": actor_id,
            }
        )
        db.add(permission)
        db.flush()
        action = "create"
        old_values = None
    else:
        old_values = _permission_values(permission)
        if not any((data.can_view, data.can_create, data.can_edit, data.can_delete)):
            permission.deleted_at = now
        else:
            permission.can_view = data.can_view
            permission.can_create = data.can_create
            permission.can_edit = data.can_edit
            permission.can_delete = data.can_delete
        permission.updated_at = now
        permission.updated_by = actor_id
        permission.version += 1
        action = "update"

    _write_audit(
        db,
        actor_id=actor_id,
        user_id=permission.id,
        table_name="user_permissions",
        action=action,
        old_values=old_values,
        new_values=new_values if permission.deleted_at is None else {"deleted": True},
        reason="Admin cấp, sửa hoặc thu hồi quyền bổ sung",
    )
    return permission


def list_user_permissions(db: Session, target_id: int) -> list[UserPermission]:
    return list(
        db.scalars(
            select(UserPermission)
            .where(
                UserPermission.user_id == target_id,
                UserPermission.deleted_at.is_(None),
            )
            .order_by(UserPermission.module)
        )
    )


def list_users(db: Session, *, limit: int | None = None, offset: int = 0) -> list[User]:
    query = (
        select(User)
        .where(User.deleted_at.is_(None))
        .order_by(User.username, User.id)
        .offset(offset)
    )
    if limit is not None:
        query = query.limit(limit)
    return list(db.scalars(query))


def count_users(db: Session) -> int:
    return db.scalar(select(func.count(User.id)).where(User.deleted_at.is_(None))) or 0


def get_user(db: Session, target_id: int) -> User | None:
    return db.scalar(select(User).where(User.id == target_id, User.deleted_at.is_(None)))


def _load_user_for_update(db: Session, target_id: int) -> User:
    user = db.scalar(
        select(User).where(User.id == target_id, User.deleted_at.is_(None)).with_for_update()
    )
    if user is None:
        raise UserManagementError("Không tìm thấy tài khoản.")
    return user


def _require_admin_actor(db: Session, actor_id: int) -> None:
    actor = db.scalar(
        select(User).where(
            User.id == actor_id,
            User.role == "admin",
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    if actor is None:
        raise UserManagementError("Chỉ Admin đang hoạt động được quản lý tài khoản.")


def _ensure_another_active_admin(db: Session, current_user_id: int) -> None:
    db.execute(select(func.pg_advisory_xact_lock(6_753_214_091)))
    db.flush()
    count = db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.role == "admin",
            User.is_active.is_(True),
            User.deleted_at.is_(None),
            User.id != current_user_id,
        )
    )
    if not count:
        raise UserManagementError("Không thể khóa hoặc hạ vai trò Admin hoạt động cuối cùng.")


def _user_values(user: User) -> dict[str, object]:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
    }


def _permission_values(permission: UserPermission) -> dict[str, object]:
    return {
        "user_id": permission.user_id,
        "module": permission.module,
        "can_view": permission.can_view,
        "can_create": permission.can_create,
        "can_edit": permission.can_edit,
        "can_delete": permission.can_delete,
    }


def _write_audit(
    db: Session,
    *,
    actor_id: int,
    user_id: int,
    action: str,
    old_values: dict[str, object] | None,
    new_values: dict[str, object] | None,
    reason: str,
    table_name: str = "users",
) -> None:
    db.add(
        AuditLog(
            table_name=table_name,
            record_id=user_id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            actor_id=actor_id,
        )
    )
