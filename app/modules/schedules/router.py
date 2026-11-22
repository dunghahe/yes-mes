import calendar
from datetime import date, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, csrf_token_for_request, set_csrf_cookie
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
LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


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
    view: str = "month",
    anchor: date | None = None,
    shift_filter: int | None = None,
    order_filter: int | None = None,
    query_text: str = "",
    selected_day: date | None = None,
    open_create: bool = False,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    anchor = anchor or datetime.now(LOCAL_TZ).date()
    if view == "day":
        selected_day = anchor
    if view in {"day", "week"}:
        view = "list"
    elif view not in {"month", "list"}:
        view = "month"
    start_date, end_date, calendar_days, previous, following, calendar_title = _calendar_window(
        view, anchor
    )
    rows = list_schedules(
        db,
        start_date=start_date,
        end_date=end_date,
        shift_id=shift_filter,
        order_id=order_filter,
        query_text=query_text,
    )
    by_date: dict[date, list[tuple]] = {day: [] for day in calendar_days}
    for row in rows:
        by_date[row[0].production_date].append(row)
    if selected_day not in by_date:
        selected_day = None
    visible_rows = by_date[selected_day] if selected_day and view == "list" else rows
    weeks = [calendar_days[i : i + 7] for i in range(0, len(calendar_days), 7)]
    token = csrf_token_for_request(request)
    response = templates.TemplateResponse(
        request=request,
        name="schedules/list.html",
        context={
            "title": "Lịch sản xuất",
            "schedules": visible_rows,
            "week_schedule_count": len(rows),
            "selected_day": selected_day,
            "query_text": query_text,
            "calendar_days": calendar_days,
            "calendar_weeks": weeks,
            "schedules_by_date": by_date,
            "view": view,
            "anchor": anchor.isoformat(),
            "anchor_date": anchor,
            "calendar_title": calendar_title,
            "previous_date": previous.isoformat(),
            "next_date": following.isoformat(),
            "shift_filter": shift_filter,
            "order_filter": order_filter,
            "weekday_names": ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"],
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
            "open_create": open_create,
            "schedule_base_url": "/schedules",
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


def _calendar_window(view: str, anchor: date):
    if view == "day":
        start_date = end_date = anchor
        calendar_days = [anchor]
        previous = following = timedelta(days=1)
        title = anchor.strftime("%d/%m/%Y")
        return start_date, end_date, calendar_days, anchor - previous, anchor + following, title
    if view in {"week", "list"}:
        start_date = anchor - timedelta(days=anchor.weekday())
        end_date = start_date + timedelta(days=6)
        calendar_days = [start_date + timedelta(days=i) for i in range(7)]
        return (
            start_date,
            end_date,
            calendar_days,
            start_date - timedelta(days=7),
            start_date + timedelta(days=7),
            f"{start_date.strftime('%d/%m')} – {end_date.strftime('%d/%m/%Y')}",
        )
    start_date = date(anchor.year, anchor.month, 1)
    last_day = calendar.monthrange(anchor.year, anchor.month)[1]
    end_date = date(anchor.year, anchor.month, last_day)
    calendar_days = [
        day
        for week in calendar.Calendar(firstweekday=0).monthdatescalendar(anchor.year, anchor.month)
        for day in week
    ]
    previous = (start_date - timedelta(days=1)).replace(day=1)
    next_month = date(anchor.year + (anchor.month == 12), anchor.month % 12 + 1, 1)
    title = f"Tháng {anchor.month:02d}/{anchor.year}"
    return start_date, end_date, calendar_days, previous, next_month, title


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
    view: str = "month",
    on: date | None = None,
    shift_id: int | None = None,
    order_id: int | None = None,
    edit: int | None = None,
    q: str = "",
    day: date | None = None,
) -> HTMLResponse:
    schedule = None
    if edit is not None:
        if not _can_schedule_action(db, actor, "edit"):
            return Response("Bạn không có quyền sửa lịch.", status_code=403)
        row = get_schedule(db, edit)
        if row is None:
            return Response("Không tìm thấy dòng lịch.", status_code=404)
        schedule = row[0]
        on = on or schedule.production_date
    return _render(
        request,
        db,
        actor=actor,
        view=view,
        anchor=on,
        shift_filter=shift_id,
        order_filter=order_id,
        query_text=q.strip(),
        selected_day=day,
        schedule=schedule,
        open_create=schedule is not None,
    )


@router.get("/day-details", response_class=HTMLResponse)
def schedule_day_details(
    request: Request,
    actor: Annotated[User, Depends(require_permission("schedules", "view"))],
    db: Annotated[Session, Depends(get_db)],
    on: date,
    shift_id: int | None = None,
    order_id: int | None = None,
    q: str = "",
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="schedules/day_details.html",
        context={
            "schedules": list_schedules(
                db,
                start_date=on,
                end_date=on,
                shift_id=shift_id,
                order_id=order_id,
                query_text=q.strip(),
            ),
            "can_edit": _can_schedule_action(db, actor, "edit"),
        },
    )


@router.get("/manage", include_in_schema=False)
def manage_schedules_page(
    view: str = "month",
    on: date | None = None,
    shift_id: int | None = None,
    order_id: int | None = None,
) -> Response:
    values = {"view": view}
    if on:
        values["on"] = on.isoformat()
    if shift_id:
        values["shift_id"] = shift_id
    if order_id:
        values["order_id"] = order_id
    return RedirectResponse(
        f"/schedules?{urlencode(values)}", status_code=status.HTTP_307_TEMPORARY_REDIRECT
    )


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
    form_mode: Annotated[str, Form()] = "create",
    return_view: Annotated[str, Form()] = "month",
    return_on: Annotated[date | None, Form()] = None,
    return_shift_id: Annotated[int | None, Form()] = None,
    return_order_id: Annotated[int | None, Form()] = None,
    return_query: Annotated[str, Form()] = "",
    return_day: Annotated[date | None, Form()] = None,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    if form_mode != "create":
        return Response(
            "Form đang ở chế độ sửa. Hãy mở lại lịch cần sửa; hệ thống chưa tạo thêm lịch.",
            status_code=409,
        )
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
            open_create=True,
            view=return_view,
            anchor=return_on,
            shift_filter=return_shift_id,
            order_filter=return_order_id,
            query_text=return_query,
            selected_day=return_day,
        )
    except (ScheduleManagementError, IntegrityError) as exc:
        db.rollback()
        message = (
            str(exc) if isinstance(exc, ScheduleManagementError) else "Dữ liệu lịch không hợp lệ."
        )
        return _render(
            request,
            db,
            actor=actor,
            submitted=submitted,
            error=message,
            status_code=422,
            open_create=True,
            view=return_view,
            anchor=return_on,
            shift_filter=return_shift_id,
            order_filter=return_order_id,
            query_text=return_query,
            selected_day=return_day,
        )
    messages = [f"Đã lưu {len(schedules)} dòng lịch."]
    if exceeds_order:
        messages.append("Tổng kế hoạch của PO vượt số lượng đặt.")
    if any(item < datetime.now(LOCAL_TZ).date() for item in production_dates):
        messages.append("Có lịch thuộc ngày đã qua; hãy rà soát lại dữ liệu.")
    warning = " ".join(messages)
    return _render(
        request,
        db,
        actor=actor,
        warning=warning,
        view=return_view,
        anchor=return_on,
        shift_filter=return_shift_id,
        order_filter=return_order_id,
        query_text=return_query,
        selected_day=return_day,
    )


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
    query = urlencode(
        {"view": "day", "on": row[0].production_date.isoformat(), "edit": schedule_id}
    )
    return RedirectResponse(f"/schedules?{query}", status_code=status.HTTP_303_SEE_OTHER)


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
    return_view: Annotated[str, Form()] = "month",
    return_on: Annotated[date | None, Form()] = None,
    return_shift_id: Annotated[int | None, Form()] = None,
    return_order_id: Annotated[int | None, Form()] = None,
    return_query: Annotated[str, Form()] = "",
    return_day: Annotated[date | None, Form()] = None,
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
        row = get_schedule(db, schedule_id)
        return _render(
            request,
            db,
            actor=actor,
            schedule=row[0] if row else None,
            submitted={key: str(value) for key, value in values.items()},
            errors=_schema_errors(exc),
            status_code=422,
            open_create=True,
            view=return_view,
            anchor=return_on,
            shift_filter=return_shift_id,
            order_filter=return_order_id,
            query_text=return_query,
            selected_day=return_day,
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
            submitted={key: str(value) for key, value in values.items()},
            error=message,
            status_code=422,
            open_create=True,
            view=return_view,
            anchor=return_on,
            shift_filter=return_shift_id,
            order_filter=return_order_id,
            query_text=return_query,
            selected_day=return_day,
        )
    messages = ["Đã cập nhật dòng lịch."]
    if exceeds_order:
        messages.append("Tổng kế hoạch của PO vượt số lượng đặt.")
    if production_date < datetime.now(LOCAL_TZ).date():
        messages.append("Ngày lịch đã qua; hãy rà soát lại dữ liệu.")
    warning = " ".join(messages)
    return _render(
        request,
        db,
        actor=actor,
        warning=warning,
        view=return_view,
        anchor=return_on,
        shift_filter=return_shift_id,
        order_filter=return_order_id,
        query_text=return_query,
        selected_day=return_day,
    )


@router.post("/{schedule_id}/delete", response_class=HTMLResponse)
def delete_schedule_submit(
    request: Request,
    schedule_id: int,
    csrf_token: Annotated[str, Form()],
    confirm_delete: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_permission("schedules", "edit"))],
    db: Annotated[Session, Depends(get_db)],
    return_view: Annotated[str, Form()] = "month",
    return_on: Annotated[date | None, Form()] = None,
    return_shift_id: Annotated[int | None, Form()] = None,
    return_order_id: Annotated[int | None, Form()] = None,
    return_query: Annotated[str, Form()] = "",
    return_day: Annotated[date | None, Form()] = None,
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
        row = get_schedule(db, schedule_id)
        return _render(
            request,
            db,
            actor=actor,
            schedule=row[0] if row else None,
            error=str(exc),
            status_code=404,
            open_create=row is not None,
            view=return_view,
            anchor=return_on,
            shift_filter=return_shift_id,
            order_filter=return_order_id,
            query_text=return_query,
            selected_day=return_day,
        )
    query_values = {"view": return_view}
    if return_on:
        query_values["on"] = return_on.isoformat()
    if return_shift_id:
        query_values["shift_id"] = return_shift_id
    if return_order_id:
        query_values["order_id"] = return_order_id
    if return_query:
        query_values["q"] = return_query
    if return_day:
        query_values["day"] = return_day.isoformat()
    return RedirectResponse(
        f"/schedules?{urlencode(query_values)}", status_code=status.HTTP_303_SEE_OTHER
    )
