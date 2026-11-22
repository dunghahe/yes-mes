from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.auth.models import LoginSession, User
from app.modules.auth.service import next_auth_state, resolve_login_session
from app.modules.users.models import PERMISSION_MODULES, UserPermission

SESSION_COOKIE_NAME = "mes_session"


def require_session_context(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> tuple[User, LoginSession]:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    context = resolve_login_session(db, raw_token)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
        )

    user, session = context
    expected_state = next_auth_state(user)
    if expected_state != session.auth_state and session.auth_state == "active":
        session.auth_state = expected_state

    request.state.login_session = session
    if session.auth_state == "active":
        request.state.current_user = user
        if user.role == "admin":
            request.state.extra_permissions = frozenset()
            request.state.navigation_access = {
                module: {action: True for action in ("view", "create", "edit", "delete", "deliver")}
                for module in (*PERMISSION_MODULES, "accounts")
            }
        else:
            permissions = list(
                db.scalars(
                    select(UserPermission).where(
                        UserPermission.user_id == user.id,
                        UserPermission.deleted_at.is_(None),
                    )
                )
            )
            extra_permissions = frozenset(
                (permission.module, action)
                for permission in permissions
                for action, allowed in (
                    ("view", permission.can_view),
                    ("create", permission.can_create),
                    ("edit", permission.can_edit),
                    ("delete", permission.can_delete),
                )
                if allowed
            )
            request.state.extra_permissions = extra_permissions
            from app.core.permissions import has_permission

            request.state.navigation_access = {
                module: {
                    action: has_permission(user.role, module, action, extra_permissions)
                    for action in ("view", "create", "edit", "delete", "deliver")
                }
                for module in (*PERMISSION_MODULES, "accounts")
            }
    request.state.raw_session_token = raw_token
    db.commit()
    return user, session


def require_active_user(
    context: Annotated[tuple[User, LoginSession], Depends(require_session_context)],
) -> User:
    user, session = context
    if session.auth_state != "active":
        destination = {
            "password_change": "/auth/change-password",
            "totp_setup": "/auth/totp/setup",
        }.get(session.auth_state, "/auth/login")
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": destination},
        )
    return user


def require_password_change(
    context: Annotated[tuple[User, LoginSession], Depends(require_session_context)],
) -> tuple[User, LoginSession]:
    user, session = context
    if session.auth_state != "password_change":
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/" if session.auth_state == "active" else "/auth/totp/setup"},
        )
    return context


def require_totp_setup(
    context: Annotated[tuple[User, LoginSession], Depends(require_session_context)],
) -> tuple[User, LoginSession]:
    user, session = context
    if session.auth_state != "totp_setup" or user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={
                "Location": "/" if session.auth_state == "active" else "/auth/change-password"
            },
        )
    return context
