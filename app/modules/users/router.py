from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, csrf_token_for_request, set_csrf_cookie
from app.core.db import get_db
from app.core.permissions import require_admin
from app.modules.auth.models import User
from app.modules.users.models import PERMISSION_MODULES
from app.modules.users.schemas import PermissionInput, Role, UserCreate, UserUpdate
from app.modules.users.service import (
    UserManagementError,
    count_users,
    create_user,
    get_user,
    list_user_permissions,
    list_users,
    reset_password,
    set_user_permission,
    update_user,
)

router = APIRouter(prefix="/admin/users", tags=["users"])
templates = Jinja2Templates(directory="app/templates")
ROLES: tuple[tuple[Role, str], ...] = (
    ("admin", "Admin"),
    ("planning", "Kế hoạch"),
    ("engineering", "Kỹ thuật"),
    ("warehouse", "Kho NVL"),
    ("data_entry", "Nhập liệu"),
    ("manager", "Quản lý"),
)
MODULE_LABELS = {
    "master": "Dữ liệu dùng chung",
    "orders": "PO",
    "schedules": "Lịch sản xuất",
    "blank_requests": "Yêu cầu phôi",
    "daily_reports": "Báo cáo ngày",
    "qc": "QC, NG và sửa chữa",
    "repairs": "Sửa chữa",
    "reports": "Báo cáo và OEE",
    "audit": "Nhật ký sửa đổi",
}


def _render(
    request: Request,
    name: str,
    context: dict[str, object],
    *,
    status_code: int = status.HTTP_200_OK,
    no_store: bool = False,
) -> HTMLResponse:
    csrf_token = csrf_token_for_request(request)
    response = templates.TemplateResponse(
        request=request,
        name=name,
        context={**context, "csrf_token": csrf_token},
        status_code=status_code,
    )
    set_csrf_cookie(response, csrf_token)
    if no_store:
        response.headers["Cache-Control"] = "private, no-store"
    return response


def _field_errors(error: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for item in error.errors():
        field = str(item["loc"][0]) if item["loc"] else "form"
        errors[field] = "Giá trị không hợp lệ hoặc vượt giới hạn cho phép."
    return errors


def _account_form_context(
    *,
    title: str,
    user: User | None = None,
    error: str | None = None,
    errors: dict[str, str] | None = None,
    submitted: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "title": title,
        "user": user,
        "roles": ROLES,
        "error": error,
        "errors": errors or {},
        "submitted": submitted or {},
    }


def _permission_context(db: Session, user: User) -> dict[str, object]:
    permissions = {item.module: item for item in list_user_permissions(db, user.id)}
    return {
        "modules": PERMISSION_MODULES,
        "module_labels": MODULE_LABELS,
        "permissions": permissions,
    }


@router.get("", response_class=HTMLResponse)
def users_page(
    request: Request,
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
) -> HTMLResponse:
    page_size = 100
    total = count_users(db)
    return _render(
        request,
        "users/list.html",
        {
            "title": "Quản lý tài khoản",
            "users": list_users(db, limit=page_size, offset=(page - 1) * page_size),
            "page": page,
            "page_count": max(1, (total + page_size - 1) // page_size),
            "actor": actor,
            "role_labels": dict(ROLES),
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_user_page(
    request: Request,
    _actor: Annotated[User, Depends(require_admin)],
) -> HTMLResponse:
    return _render(
        request,
        "users/form.html",
        _account_form_context(title="Tạo tài khoản"),
    )


@router.post("", response_class=HTMLResponse)
def create_user_submit(
    request: Request,
    csrf_token: Annotated[str, Form()],
    username: Annotated[str, Form()],
    display_name: Annotated[str, Form()],
    role: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {"username": username, "display_name": display_name, "role": role}
    try:
        data = UserCreate.model_validate(submitted)
        user, temporary_password = create_user(db, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render(
            request,
            "users/form.html",
            _account_form_context(
                title="Tạo tài khoản",
                errors=_field_errors(exc),
                submitted=submitted,
            ),
            status_code=422,
        )
    except UserManagementError as exc:
        db.rollback()
        return _render(
            request,
            "users/form.html",
            _account_form_context(title="Tạo tài khoản", error=str(exc), submitted=submitted),
            status_code=422,
        )
    except IntegrityError:
        db.rollback()
        return _render(
            request,
            "users/form.html",
            _account_form_context(
                title="Tạo tài khoản",
                error="Tên đăng nhập này đã được sử dụng.",
                submitted=submitted,
            ),
            status_code=422,
        )
    return _render(
        request,
        "users/temporary_password.html",
        {
            "title": "Mật khẩu tạm thời",
            "username": user.username,
            "temporary_password": temporary_password,
            "message": (
                "Mật khẩu này chỉ hiển thị một lần. Hãy chuyển cho người dùng qua kênh riêng."
            ),
        },
        no_store=True,
    )


@router.get("/{user_id}", response_class=HTMLResponse)
def edit_user_page(
    request: Request,
    user_id: int,
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    user = get_user(db, user_id)
    if user is None:
        return Response("Không tìm thấy tài khoản.", status_code=404)
    context = _account_form_context(title="Sửa tài khoản", user=user)
    context.update(_permission_context(db, user))
    return _render(request, "users/edit.html", context)


@router.post("/{user_id}", response_class=HTMLResponse)
def update_user_submit(
    request: Request,
    user_id: int,
    csrf_token: Annotated[str, Form()],
    username: Annotated[str, Form()],
    display_name: Annotated[str, Form()],
    role: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    is_active: Annotated[bool, Form()] = False,
    version: Annotated[int, Form()] = 1,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {
        "username": username,
        "display_name": display_name,
        "role": role,
        "is_active": is_active,
        "version": version,
    }
    try:
        data = UserUpdate.model_validate(submitted)
        update_user(db, data, actor.id, user_id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        user = get_user(db, user_id)
        if user is None:
            return Response("Không tìm thấy tài khoản.", status_code=404)
        context = _account_form_context(
            title="Sửa tài khoản",
            user=user,
            errors=_field_errors(exc),
            submitted={
                key: value if key == "is_active" else str(value) for key, value in submitted.items()
            },
        )
        context.update(_permission_context(db, user))
        return _render(request, "users/edit.html", context, status_code=422)
    except (UserManagementError, IntegrityError) as exc:
        db.rollback()
        user = get_user(db, user_id)
        if user is None:
            return Response("Không tìm thấy tài khoản.", status_code=404)
        message = (
            str(exc)
            if isinstance(exc, UserManagementError)
            else "Tên đăng nhập này đã được sử dụng."
        )
        context = _account_form_context(title="Sửa tài khoản", user=user, error=message)
        context.update(_permission_context(db, user))
        return _render(request, "users/edit.html", context, status_code=422)
    return RedirectResponse(f"/admin/users/{user_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{user_id}/reset-password", response_class=HTMLResponse)
def reset_user_password(
    request: Request,
    user_id: int,
    csrf_token: Annotated[str, Form()],
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        temporary_password = reset_password(db, _actor.id, user_id)
        user = get_user(db, user_id)
        db.commit()
    except UserManagementError as exc:
        db.rollback()
        return Response(str(exc), status_code=404)
    return _render(
        request,
        "users/temporary_password.html",
        {
            "title": "Mật khẩu tạm thời",
            "username": user.username,
            "temporary_password": temporary_password,
            "message": (
                "Mọi phiên cũ đã bị thu hồi. Mật khẩu chỉ hiện một lần; hãy chuyển qua kênh riêng."
            ),
        },
        no_store=True,
    )


@router.post("/{user_id}/permissions/{module}")
def update_user_permission(
    request: Request,
    user_id: int,
    module: str,
    csrf_token: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    can_view: Annotated[bool, Form()] = False,
    can_create: Annotated[bool, Form()] = False,
    can_edit: Annotated[bool, Form()] = False,
    can_delete: Annotated[bool, Form()] = False,
    version: Annotated[int, Form()] = 0,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        data = PermissionInput(
            module=module,
            can_view=can_view,
            can_create=can_create,
            can_edit=can_edit,
            can_delete=can_delete,
            version=version,
        )
        set_user_permission(db, user_id, data, actor.id)
        db.commit()
    except ValidationError:
        db.rollback()
        return Response("Mô-đun hoặc quyền được chọn không hợp lệ.", status_code=422)
    except (UserManagementError, IntegrityError) as exc:
        db.rollback()
        user = get_user(db, user_id)
        if user is None:
            return Response("Không tìm thấy tài khoản.", status_code=404)
        context = _account_form_context(title="Sửa tài khoản", user=user)
        context.update(_permission_context(db, user))
        context.update(
            {
                "permission_form_module": module,
                "permission_form_values": {
                    "can_view": can_view,
                    "can_create": can_create,
                    "can_edit": can_edit,
                    "can_delete": can_delete,
                },
                "permission_form_error": (
                    str(exc) if isinstance(exc, UserManagementError) else "Không thể lưu quyền này."
                ),
            }
        )
        return _render(request, "users/edit.html", context, status_code=422)
    return RedirectResponse(f"/admin/users/{user_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{user_id}/permissions")
async def update_all_user_permissions(
    request: Request,
    user_id: int,
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    form = await request.form()
    csrf_token = str(form.get("csrf_token", ""))
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    user = get_user(db, user_id)
    if user is None:
        return Response("Không tìm thấy tài khoản.", status_code=404)
    values: dict[str, dict[str, bool | int]] = {}
    try:
        for module in PERMISSION_MODULES:
            prefix = f"perm_{module}_"
            values[module] = {
                "can_view": form.get(prefix + "can_view") == "true",
                "can_create": form.get(prefix + "can_create") == "true",
                "can_edit": form.get(prefix + "can_edit") == "true",
                "can_delete": form.get(prefix + "can_delete") == "true",
            }
        permission_inputs = [
            PermissionInput(
                module=module,
                **values[module],
                version=int(form.get(f"perm_{module}_version", "0")),
            )
            for module in PERMISSION_MODULES
        ]
        for data in permission_inputs:
            set_user_permission(db, user_id, data, actor.id)
        db.commit()
    except (ValidationError, ValueError):
        db.rollback()
        user = get_user(db, user_id)
        if user is None:
            return Response("Không tìm thấy tài khoản.", status_code=404)
        context = _account_form_context(
            title="Sửa tài khoản",
            user=user,
            error="Thông tin quyền không hợp lệ. Hãy chọn Xem nếu cấp quyền Tạo, Sửa hoặc Xóa.",
        )
        context.update(_permission_context(db, user))
        context["submitted_permissions"] = values
        return _render(request, "users/edit.html", context, status_code=422)
    except (UserManagementError, IntegrityError) as exc:
        db.rollback()
        user = get_user(db, user_id)
        if user is None:
            return Response("Không tìm thấy tài khoản.", status_code=404)
        context = _account_form_context(
            title="Sửa tài khoản",
            user=user,
            error=(
                str(exc)
                if isinstance(exc, UserManagementError)
                else "Quyền đã thay đổi. Hãy tải lại trang."
            ),
        )
        context.update(_permission_context(db, user))
        context["submitted_permissions"] = values
        return _render(request, "users/edit.html", context, status_code=409)
    return RedirectResponse(f"/admin/users/{user_id}", status_code=status.HTTP_303_SEE_OTHER)
