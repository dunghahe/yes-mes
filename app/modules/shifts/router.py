from datetime import time
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, csrf_token_for_request, set_csrf_cookie
from app.core.db import get_db
from app.core.permissions import require_admin
from app.modules.auth.models import User
from app.modules.shifts.schemas import ShiftCreate, ShiftUpdate
from app.modules.shifts.service import (
    ShiftManagementError,
    create_shift,
    list_shifts,
    update_shift,
)

router = APIRouter(prefix="/admin/shifts", tags=["shifts"])
templates = Jinja2Templates(directory="app/templates")


def _render(
    request: Request,
    db: Session,
    *,
    error: str | None = None,
    submitted: dict[str, object] | None = None,
    errors: dict[str, str] | None = None,
) -> HTMLResponse:
    csrf_token = csrf_token_for_request(request)
    response = templates.TemplateResponse(
        request=request,
        name="shifts/manage.html",
        context={
            "title": "Quản lý kíp",
            "shifts": list_shifts(db),
            "error": error,
            "submitted": submitted or {},
            "errors": errors or {},
            "csrf_token": csrf_token,
        },
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY if error or errors else status.HTTP_200_OK,
    )
    set_csrf_cookie(response, csrf_token)
    return response


def _validation_errors(error: ValidationError) -> dict[str, str]:
    field_names = {
        "name": "Tên kíp",
        "start_time": "Giờ bắt đầu",
        "end_time": "Giờ kết thúc",
        "planned_break_minutes": "Thời gian nghỉ",
        "crosses_midnight": "Cờ qua nửa đêm",
    }
    errors: dict[str, str] = {}
    for item in error.errors():
        field = str(item["loc"][0]) if item["loc"] else "form"
        label = field_names.get(field, "Thông tin kíp")
        errors[field] = f"{label} không hợp lệ. Kiểm tra giờ qua nửa đêm và thời gian nghỉ."
    return errors


@router.get("", response_class=HTMLResponse)
def shifts_page(
    request: Request,
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    return _render(request, db)


@router.post("")
def create_shift_submit(
    request: Request,
    csrf_token: Annotated[str, Form()],
    name: Annotated[str, Form()],
    start_time: Annotated[time, Form()],
    end_time: Annotated[time, Form()],
    planned_break_minutes: Annotated[int, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    crosses_midnight: Annotated[bool, Form()] = False,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {
        "name": name,
        "start_time": start_time.isoformat(timespec="minutes"),
        "end_time": end_time.isoformat(timespec="minutes"),
        "planned_break_minutes": planned_break_minutes,
        "crosses_midnight": crosses_midnight,
    }
    try:
        data = ShiftCreate.model_validate(submitted)
        create_shift(db, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render(request, db, submitted=submitted, errors=_validation_errors(exc))
    except (ShiftManagementError, IntegrityError) as exc:
        db.rollback()
        message = (
            str(exc) if isinstance(exc, ShiftManagementError) else "Tên kíp này đã được sử dụng."
        )
        return _render(request, db, submitted=submitted, error=message)
    return RedirectResponse("/admin/shifts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{shift_id}")
def update_shift_submit(
    request: Request,
    shift_id: int,
    csrf_token: Annotated[str, Form()],
    name: Annotated[str, Form()],
    start_time: Annotated[time, Form()],
    end_time: Annotated[time, Form()],
    planned_break_minutes: Annotated[int, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    crosses_midnight: Annotated[bool, Form()] = False,
    is_active: Annotated[bool, Form()] = False,
    version: Annotated[int, Form()] = 1,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {
        "name": name,
        "start_time": start_time.isoformat(timespec="minutes"),
        "end_time": end_time.isoformat(timespec="minutes"),
        "planned_break_minutes": planned_break_minutes,
        "crosses_midnight": crosses_midnight,
        "is_active": is_active,
    }
    try:
        data = ShiftUpdate.model_validate({**submitted, "version": version})
        update_shift(db, shift_id, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render(request, db, submitted=submitted, errors=_validation_errors(exc))
    except (ShiftManagementError, IntegrityError) as exc:
        db.rollback()
        message = (
            str(exc) if isinstance(exc, ShiftManagementError) else "Tên kíp này đã được sử dụng."
        )
        return _render(request, db, error=message)
    return RedirectResponse("/admin/shifts", status_code=status.HTTP_303_SEE_OTHER)
