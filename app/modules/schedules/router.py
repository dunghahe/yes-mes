import secrets
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, set_csrf_cookie
from app.core.db import get_db
from app.core.permissions import has_permission, require_permission
from app.modules.auth.models import User
from app.modules.orders.models import ProductionOrder
from app.modules.schedules.models import ProductionSchedule
from app.modules.schedules.schemas import ScheduleBatchCreate, ScheduleUpdate
from app.modules.schedules.service import (
    ScheduleManagementError,
    create_schedule_batch,
    get_schedule,
    list_schedules,
    soft_delete_schedule,
    update_schedule,
)
from app.modules.shifts.models import Shift
from app.modules.users.models import UserPermission

router = APIRouter(prefix="/schedules", tags=["schedules"])
templates = Jinja2Templates(directory="app/templates")


def _render(
    request: Request,
    db: Session,
    *,
    actor: User | None = None,
    schedule: ProductionSchedule | None = None,
    submitted: dict[str, object] | None = None,
    errors: dict[str, str] | None = None,
    error: str | None = None,
    warning: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    token = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        request=request,
        name="schedules/list.html",
        context={
            "title": "Lịch sản xuất",
            "schedules": list_schedules(db),
            "active_orders": list(
                db.execute(
                    select(ProductionOrder)
                    .where(ProductionOrder.deleted_at.is_(None))
                    .order_by(ProductionOrder.po_no)
                ).scalars()
            ),
            "active_shifts": list(
                db.scalars(
                    select(Shift)
                    .where(Shift.is_active.is_(True), Shift.deleted_at.is_(None))
                    .order_by(Shift.start_time, Shift.id)
                )
            ),
            "schedule": schedule,
            "can_create": actor is not None and _can_schedule_action(db, actor, "create"),
            "can_edit": actor is not None and _can_schedule_action(db, actor, "edit"),
            "submitted": submitted or {},
            "errors": errors or {},
            "error": error,
            "warning": warning,
            "csrf_token": token,
        },
        status_code=status_code,
    )
    set_csrf_cookie(response, token)
    return response


def _can_schedule_action(db: Session, actor: User, action: str) -> bool:
    extras = frozenset(
        (permission.module, permitted_action)
        for permission in db.scalars(
            select(UserPermission).where(
                UserPermission.user_id == actor.id,
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
    return has_permission(actor.role, "schedules", action, extras)


def _schema_errors(error: ValidationError) -> dict[str, str]:
    mapping = {
        "production_dates": "Chọn ít nhất một ngày, không chọn trùng và tối đa 62 ngày mỗi lần.",
        "shift_id": "Chọn kíp đang sử dụng.",
        "order_id": "Chọn PO đang sử dụng.",
        "planned_quantity": "Số lượng kế hoạch phải là số nguyên dương.",
        "production_date": "Chọn ngày sản xuất.",
    }
    return {
        str(item["loc"][0]) if item["loc"] else "form": mapping.get(
            str(item["loc"][0]) if item["loc"] else "form", "Giá trị không hợp lệ."
        )
        for item in error.errors()
    }


@router.get("", response_class=HTMLResponse)
def schedules_page(
    request: Request,
    actor: Annotated[User, Depends(require_permission("schedules", "view"))],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    return _render(request, db, actor=actor)


@router.post("", response_class=HTMLResponse)
def create_schedule_submit(
    request: Request,
    csrf_token: Annotated[str, Form()],
    production_dates: Annotated[list[date], Form()],
    shift_id: Annotated[int, Form()],
    order_id: Annotated[int, Form()],
    planned_quantity: Annotated[int, Form()],
    actor: Annotated[User, Depends(require_permission("schedules", "create"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {
        "production_dates": [item.isoformat() for item in production_dates],
        "shift_id": shift_id,
        "order_id": order_id,
        "planned_quantity": planned_quantity,
    }
    try:
        schedules, exceeds_order = create_schedule_batch(
            db, ScheduleBatchCreate.model_validate(submitted), actor.id
        )
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render(
            request,
            db,
            actor=actor,
            submitted=submitted,
            errors=_schema_errors(exc),
            status_code=422,
        )
    except (ScheduleManagementError, IntegrityError) as exc:
        db.rollback()
        message = (
            str(exc) if isinstance(exc, ScheduleManagementError) else "Dữ liệu lịch không hợp lệ."
        )
        return _render(
            request, db, actor=actor, submitted=submitted, error=message, status_code=422
        )
    message = f"Đã lưu {len(schedules)} dòng lịch."
    warning = "Tổng kế hoạch của PO vượt số lượng đặt." if exceeds_order else None
    return _render(request, db, actor=actor, warning=warning or message)


@router.get("/{schedule_id}", response_class=HTMLResponse)
def edit_schedule_page(
    request: Request,
    schedule_id: int,
    actor: Annotated[User, Depends(require_permission("schedules", "edit"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    row = get_schedule(db, schedule_id)
    if row is None:
        return Response("Không tìm thấy dòng lịch.", status_code=404)
    return _render(request, db, actor=actor, schedule=row[0])


@router.post("/{schedule_id}", response_class=HTMLResponse)
def update_schedule_submit(
    request: Request,
    schedule_id: int,
    csrf_token: Annotated[str, Form()],
    production_date: Annotated[date, Form()],
    shift_id: Annotated[int, Form()],
    order_id: Annotated[int, Form()],
    planned_quantity: Annotated[int, Form()],
    version: Annotated[int, Form()],
    actor: Annotated[User, Depends(require_permission("schedules", "edit"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    values = {
        "production_date": production_date,
        "shift_id": shift_id,
        "order_id": order_id,
        "planned_quantity": planned_quantity,
        "version": version,
    }
    try:
        _, exceeds_order = update_schedule(
            db, schedule_id, ScheduleUpdate.model_validate(values), actor.id
        )
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render(
            request,
            db,
            actor=actor,
            submitted={key: str(value) for key, value in values.items()},
            errors=_schema_errors(exc),
            status_code=422,
        )
    except (ScheduleManagementError, IntegrityError) as exc:
        db.rollback()
        row = get_schedule(db, schedule_id)
        message = (
            str(exc) if isinstance(exc, ScheduleManagementError) else "Dữ liệu lịch không hợp lệ."
        )
        return _render(
            request,
            db,
            actor=actor,
            schedule=row[0] if row else None,
            error=message,
            status_code=422,
        )
    warning = (
        "Tổng kế hoạch của PO vượt số lượng đặt." if exceeds_order else "Đã cập nhật dòng lịch."
    )
    return _render(request, db, actor=actor, warning=warning)


@router.post("/{schedule_id}/delete", response_class=HTMLResponse)
def delete_schedule_submit(
    request: Request,
    schedule_id: int,
    csrf_token: Annotated[str, Form()],
    confirm_delete: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_permission("schedules", "edit"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    if confirm_delete != "yes":
        return Response("Hãy xác nhận xóa dòng lịch.", status_code=422)
    try:
        soft_delete_schedule(db, schedule_id, actor.id)
        db.commit()
    except ScheduleManagementError as exc:
        db.rollback()
        return _render(request, db, actor=actor, error=str(exc), status_code=404)
    return RedirectResponse("/schedules", status_code=status.HTTP_303_SEE_OTHER)
