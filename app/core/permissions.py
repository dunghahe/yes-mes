from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.auth.dependencies import require_active_user
from app.modules.auth.models import User
from app.modules.users.models import UserPermission

Permission = tuple[str, str]

ROLE_PERMISSIONS: dict[str, frozenset[Permission] | None] = {
    "admin": None,
    "planning": frozenset(
        {
            ("master", "view"),
            ("orders", "view"),
            ("orders", "create"),
            ("orders", "edit"),
            ("schedules", "view"),
            ("schedules", "create"),
            ("schedules", "edit"),
            ("reports", "view"),
        }
    ),
    "engineering": frozenset(
        {
            ("master", "view"),
            ("orders", "view"),
            ("schedules", "view"),
            ("blank_requests", "view"),
            ("blank_requests", "create"),
            ("reports", "view"),
        }
    ),
    "warehouse": frozenset(
        {
            ("master", "view"),
            ("orders", "view"),
            ("schedules", "view"),
            ("blank_requests", "view"),
            ("blank_requests", "deliver"),
            ("reports", "view"),
        }
    ),
    "data_entry": frozenset(
        {
            ("master", "view"),
            ("orders", "view"),
            ("schedules", "view"),
            ("blank_requests", "view"),
            ("blank_requests", "edit"),
            ("daily_reports", "view"),
            ("daily_reports", "create"),
            ("daily_reports", "edit"),
            ("qc", "view"),
            ("qc", "create"),
            ("qc", "edit"),
            ("repairs", "view"),
            ("repairs", "create"),
            ("repairs", "edit"),
            ("reports", "view"),
        }
    ),
    "manager": frozenset(
        {
            ("master", "view"),
            ("orders", "view"),
            ("schedules", "view"),
            ("daily_reports", "view"),
            ("reports", "view"),
            ("qc", "view"),
            ("repairs", "view"),
            ("audit", "view"),
        }
    ),
}


def has_permission(
    role: str,
    module: str,
    action: str,
    extra_permissions: frozenset[Permission] = frozenset(),
) -> bool:
    permissions = ROLE_PERMISSIONS.get(role)
    if role == "admin":
        return True
    if permissions is None:
        return False
    return (module, action) in (permissions or ()) or (module, action) in extra_permissions


def require_admin(
    user: Annotated[User, Depends(require_active_user)],
) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chức năng này chỉ dành cho Admin.",
        )
    return user


def require_permission(module: str, action: str) -> Callable[..., User]:
    def check_permission(
        request: Request,
        user: Annotated[User, Depends(require_active_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> User:
        if user.role == "admin":
            return user
        extras = getattr(request.state, "extra_permissions", None)
        if extras is None:
            extras = frozenset(
                (permission.module, permitted_action)
                for permission in db.scalars(
                    select(UserPermission).where(
                        UserPermission.user_id == user.id,
                        UserPermission.deleted_at.is_(None),
                    )
                )
                for permitted_action, allowed in (
                    ("view", permission.can_view),
                    ("create", permission.can_create),
                    ("edit", permission.can_edit),
                    ("delete", permission.can_delete),
                )
                if allowed
            )
        if not has_permission(user.role, module, action, extras):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền thực hiện chức năng này.",
            )
        return user

    return check_permission
