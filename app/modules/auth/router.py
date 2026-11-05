import base64
import secrets
from io import BytesIO
from ipaddress import ip_address
from typing import Annotated

import qrcode
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.csrf import csrf_is_valid, set_csrf_cookie
from app.core.db import get_db
from app.modules.auth.dependencies import (
    SESSION_COOKIE_NAME,
    require_password_change,
    require_session_context,
    require_totp_setup,
)
from app.modules.auth.models import AuthEvent, LoginSession, User
from app.modules.auth.service import (
    AuthenticationError,
    RateLimitError,
    authenticate_password,
    begin_admin_totp_enrollment,
    change_password,
    complete_login,
    confirm_admin_totp_enrollment,
    create_login_session,
    next_auth_state,
    record_login_factor_failure,
    revoke_user_sessions,
    verify_admin_totp,
)
from app.modules.auth.totp import decrypt_totp_secret, provisioning_uri

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


def _request_ip(request: Request) -> str | None:
    if get_settings().app_env == "production":
        forwarded_ip = request.headers.get("cf-connecting-ip", "").strip()
        try:
            return str(ip_address(forwarded_ip))
        except ValueError:
            return None
    return request.client.host if request.client else None


def _login_page(
    request: Request,
    *,
    error: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    csrf_token = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"title": "Đăng nhập", "error": error, "csrf_token": csrf_token},
        status_code=status_code,
    )
    set_csrf_cookie(response, csrf_token)
    return response


def _render_page(
    request: Request,
    name: str,
    context: dict[str, object],
    *,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    csrf_token = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        request=request,
        name=name,
        context={**context, "csrf_token": csrf_token},
        status_code=status_code,
    )
    set_csrf_cookie(response, csrf_token)
    return response


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=get_settings().session_idle_timeout_minutes * 60,
    )


def _qr_data_uri(value: str) -> str:
    buffer = BytesIO()
    qrcode.make(value).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@router.get("/login", response_class=HTMLResponse, name="login")
def login_page(request: Request) -> HTMLResponse:
    return _login_page(request)


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
    totp_code: Annotated[str, Form()] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _login_page(
            request, error="Phiên biểu mẫu không hợp lệ. Vui lòng tải lại trang.", status_code=403
        )
    ip = _request_ip(request)
    if ip is None:
        return _login_page(
            request, error="Không xác định được địa chỉ IP đăng nhập.", status_code=400
        )

    try:
        user = authenticate_password(db, username, password, ip)
    except RateLimitError as exc:
        db.commit()
        return _login_page(request, error=str(exc), status_code=429)
    except AuthenticationError:
        db.commit()
        return _login_page(
            request,
            error="Tên đăng nhập hoặc mật khẩu không đúng, hoặc tài khoản bị khóa.",
            status_code=401,
        )

    if user.role == "admin" and user.totp_enabled:
        if not verify_admin_totp(db, user, totp_code):
            try:
                record_login_factor_failure(db, user, ip)
            except RateLimitError as exc:
                db.commit()
                return _login_page(request, error=str(exc), status_code=429)
            db.commit()
            return _login_page(
                request,
                error="Tên đăng nhập, mật khẩu hoặc mã xác thực không đúng.",
                status_code=401,
            )

    complete_login(db, user, ip)
    auth_state = next_auth_state(user)
    raw_token, _session = create_login_session(db, user.id, auth_state=auth_state)
    db.commit()
    response = RedirectResponse(
        url={
            "password_change": "/auth/change-password",
            "totp_setup": "/auth/totp/setup",
            "active": "/",
        }[auth_state],
        status_code=status.HTTP_303_SEE_OTHER,
    )
    _set_session_cookie(response, raw_token)
    return response


@router.post("/logout")
def logout(
    request: Request,
    csrf_token: Annotated[str, Form()],
    context: Annotated[tuple[User, LoginSession], Depends(require_session_context)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    user, session = context
    revoke_user_sessions(db, user.id)
    request.state.raw_session_token = None
    db.add(
        AuthEvent(
            user_id=user.id,
            username_attempt=user.username,
            event_type="logout",
        )
    )
    db.commit()
    response = RedirectResponse("/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax"
    )
    return response


@router.get("/change-password", response_class=HTMLResponse)
def change_password_page(
    request: Request,
    context: Annotated[tuple[User, LoginSession], Depends(require_password_change)],
) -> HTMLResponse:
    user, _session = context
    return _render_page(
        request,
        "auth/change_password.html",
        {"title": "Đổi mật khẩu", "display_name": user.display_name},
    )


@router.post("/change-password", response_class=HTMLResponse)
def change_password_submit(
    request: Request,
    csrf_token: Annotated[str, Form()],
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    context: Annotated[tuple[User, LoginSession], Depends(require_password_change)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    user, _old_session = context
    if new_password != confirm_password:
        error = "Mật khẩu mới nhập lại chưa khớp."
        return _render_page(
            request,
            "auth/change_password.html",
            {"title": "Đổi mật khẩu", "display_name": user.display_name, "error": error},
            status_code=422,
        )
    try:
        raw_token, new_session = change_password(
            db,
            user,
            current_password,
            new_password,
        )
    except (AuthenticationError, ValueError) as exc:
        db.commit()
        return _render_page(
            request,
            "auth/change_password.html",
            {"title": "Đổi mật khẩu", "display_name": user.display_name, "error": str(exc)},
            status_code=422,
        )
    db.commit()
    request.state.raw_session_token = None
    response = RedirectResponse(
        url=("/auth/totp/setup" if new_session.auth_state == "totp_setup" else "/"),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    _set_session_cookie(response, raw_token)
    return response


@router.get("/totp/setup", response_class=HTMLResponse)
def totp_setup_page(
    request: Request,
    context: Annotated[tuple[User, LoginSession], Depends(require_totp_setup)],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    user, _session = context
    secret = decrypt_totp_secret(user.totp_secret_encrypted) if user.totp_secret_encrypted else None
    return _render_page(
        request,
        "auth/totp_setup.html",
        {
            "title": "Thiết lập xác thực hai lớp",
            "secret": secret,
            "provisioning_uri": provisioning_uri(user.username, secret) if secret else None,
            "qr_data_uri": _qr_data_uri(provisioning_uri(user.username, secret))
            if secret
            else None,
        },
    )


@router.post("/totp/setup/begin", response_class=HTMLResponse)
def totp_setup_begin(
    request: Request,
    csrf_token: Annotated[str, Form()],
    context: Annotated[tuple[User, LoginSession], Depends(require_totp_setup)],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    user, _session = context
    _secret, uri = begin_admin_totp_enrollment(db, user)
    db.commit()
    return _render_page(
        request,
        "auth/totp_setup.html",
        {
            "title": "Thiết lập xác thực hai lớp",
            "secret": decrypt_totp_secret(user.totp_secret_encrypted),
            "provisioning_uri": uri,
            "qr_data_uri": _qr_data_uri(uri),
        },
    )


@router.post("/totp/setup/confirm", response_class=HTMLResponse)
def totp_setup_confirm(
    request: Request,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    context: Annotated[tuple[User, LoginSession], Depends(require_totp_setup)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    user, session = context
    recovery_codes = confirm_admin_totp_enrollment(db, user, code)
    if recovery_codes is None:
        return _render_page(
            request,
            "auth/totp_setup.html",
            {
                "title": "Thiết lập xác thực hai lớp",
                "secret": decrypt_totp_secret(user.totp_secret_encrypted),
                "provisioning_uri": provisioning_uri(
                    user.username, decrypt_totp_secret(user.totp_secret_encrypted)
                ),
                "qr_data_uri": _qr_data_uri(
                    provisioning_uri(user.username, decrypt_totp_secret(user.totp_secret_encrypted))
                ),
                "error": "Mã xác thực chưa đúng hoặc đã hết hạn.",
            },
            status_code=422,
        )

    session.auth_state = "active"
    db.commit()
    return _render_page(
        request,
        "auth/recovery_codes.html",
        {"title": "Mã dự phòng TOTP", "recovery_codes": recovery_codes},
    )
