from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.modules.auth.dependencies import require_active_user
from app.modules.auth.models import User

Permission = tuple[str, str]

ROLE_PERMISSIONS: dict[str, frozenset[Permission] | None] = {
    "admin": None,
    "planning": frozenset(
        {
            ("accounts", "view"),
            ("master_data", "view"),
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
            ("accounts", "view"),
            ("master_data", "view"),
            ("orders", "view"),
            ("schedules", "view"),
            ("blank_requests", "view"),
            ("blank_requests", "create"),
            ("reports", "view"),
        }
    ),
    "warehouse": frozenset(
        {
            ("accounts", "view"),
            ("master_data", "view"),
            ("orders", "view"),
            ("schedules", "view"),
            ("blank_requests", "view"),
            ("blank_requests", "deliver"),
            ("reports", "view"),
        }
    ),
    "data_entry": frozenset(
        {
            ("accounts", "view"),
            ("master_data", "view"),
            ("orders", "view"),
            ("schedules", "view"),
            ("blank_requests", "view"),
            ("blank_requests", "edit"),
            ("daily_reports", "view"),
            ("daily_reports", "create"),
            ("daily_reports", "edit"),
            ("reports", "view"),
        }
    ),
    "manager": frozenset(
        {
            ("accounts", "view"),
            ("master_data", "view"),
            ("orders", "view"),
            ("schedules", "view"),
            ("daily_reports", "view"),
            ("reports", "view"),
            ("audit_log", "view"),
        }
    ),
}


def has_permission(role: str, module: str, action: str) -> bool:
    permissions = ROLE_PERMISSIONS.get(role)
    return permissions is None if role == "admin" else (module, action) in (permissions or ())


def require_permission(module: str, action: str) -> Callable[..., User]:
    def check_permission(
        user: Annotated[User, Depends(require_active_user)],
    ) -> User:
        if not has_permission(user.role, module, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền thực hiện chức năng này.",
            )
        return user

    return check_permission
