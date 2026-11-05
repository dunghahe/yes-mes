import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, set_csrf_cookie
from app.core.db import get_db
from app.core.permissions import has_permission, require_permission
from app.modules.auth.models import User
from app.modules.blank_requests.schemas import BlankRequestCreate
from app.modules.blank_requests.service import (
    BlankRequestManagementError,
    active_groups,
    active_operators,
    active_pairs_for_group,
    available_schedules,
    create_blank_request,
    list_blank_requests,
    request_resources,
)
from app.modules.users.models import UserPermission

router = APIRouter(prefix="/blank-requests", tags=["blank-requests"])
templates = Jinja2Templates(directory="app/templates")
STATUS_LABELS = {"submitted": "Chờ kho giao", "cancelled": "Đã hủy", "delivered": "Đã giao"}


def _render(
    request: Request,
    db: Session,
    *,
    actor: User,
    schedule_id: int | None = None,
    group_id: int | None = None,
    submitted: dict[str, object] | None = None,
    errors: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    token = secrets.token_urlsafe(32)
    available = available_schedules(db)
    schedule_valid = schedule_id is None or any(row[0].id == schedule_id for row in available)
    pair_options = active_pairs_for_group(db, group_id) if group_id else []
    request_rows = list_blank_requests(db)
    resources = request_resources(db, [row[0].id for row in request_rows])
    response = templates.TemplateResponse(
        request=request,
        name="blank_requests/list.html",
        context={
            "title": "Yêu cầu xuất phôi",
            "requests": request_rows,
            "request_resources": resources,
            "schedule_options": available,
            "schedule_id": schedule_id,
            "schedule_valid": schedule_valid,
            "group_options": active_groups(db),
            "group_id": group_id,
            "pair_options": pair_options,
            "operator_options": active_operators(db),
            "selected_pairs": set((submitted or {}).get("machine_pair_ids", [])),
            "selected_operators": set((submitted or {}).get("operator_ids", [])),
            "submitted": submitted or {},
            "errors": errors or {},
            "error": error,
            "status_labels": STATUS_LABELS,
            "can_create": _can_create(db, actor),
            "csrf_token": token,
        },
        status_code=status_code,
    )
    set_csrf_cookie(response, token)
    return response


def _can_create(db: Session, actor: User) -> bool:
    extras = frozenset(
        (permission.module, "create")
        for permission in db.scalars(
            select(UserPermission).where(
                UserPermission.user_id == actor.id,
                UserPermission.deleted_at.is_(None),
            )
        )
        if permission.can_create
    )
    return has_permission(actor.role, "blank_requests", "create", extras)


def _field_errors(error: ValidationError) -> dict[str, str]:
    mapping = {
        "schedule_id": "Chọn dòng lịch đang sử dụng.",
        "blank_quantity": "Số lượng phôi phải là số nguyên dương.",
        "machine_group_id": "Chọn nhóm máy đang sử dụng.",
        "machine_pair_ids": "Chọn ít nhất một cặp máy đang thuộc nhóm đã chọn.",
        "operator_ids": "Chọn ít nhất một người vận hành đang sử dụng.",
    }
    return {
        str(item["loc"][0]) if item["loc"] else "form": mapping.get(
            str(item["loc"][0]) if item["loc"] else "form", "Giá trị không hợp lệ."
        )
        for item in error.errors()
    }


@router.get("", response_class=HTMLResponse)
def blank_requests_page(
    request: Request,
    actor: Annotated[User, Depends(require_permission("blank_requests", "view"))],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    return _render(request, db, actor=actor)


@router.get("/new", response_class=HTMLResponse)
def new_blank_request_page(
    request: Request,
    actor: Annotated[User, Depends(require_permission("blank_requests", "create"))],
    db: Annotated[Session, Depends(get_db)],
    schedule_id: int | None = None,
    machine_group_id: int | None = None,
) -> HTMLResponse:
    return _render(request, db, actor=actor, schedule_id=schedule_id, group_id=machine_group_id)


@router.post("", response_class=HTMLResponse)
def create_blank_request_submit(
    request: Request,
    csrf_token: Annotated[str, Form()],
    schedule_id: Annotated[int, Form()],
    blank_quantity: Annotated[int, Form()],
    machine_group_id: Annotated[int, Form()],
    actor: Annotated[User, Depends(require_permission("blank_requests", "create"))],
    db: Annotated[Session, Depends(get_db)],
    machine_pair_ids: Annotated[list[int] | None, Form()] = None,
    operator_ids: Annotated[list[int] | None, Form()] = None,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {
        "schedule_id": schedule_id,
        "blank_quantity": blank_quantity,
        "machine_group_id": machine_group_id,
        "machine_pair_ids": machine_pair_ids or [],
        "operator_ids": operator_ids or [],
    }
    try:
        data = BlankRequestCreate.model_validate(submitted)
        create_blank_request(db, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render(
            request,
            db,
            actor=actor,
            schedule_id=schedule_id,
            group_id=machine_group_id,
            submitted=submitted,
            errors=_field_errors(exc),
            status_code=422,
        )
    except BlankRequestManagementError as exc:
        db.rollback()
        return _render(
            request,
            db,
            actor=actor,
            schedule_id=schedule_id,
            group_id=machine_group_id,
            submitted=submitted,
            error=str(exc),
            status_code=422,
        )
    return RedirectResponse("/blank-requests", status_code=status.HTTP_303_SEE_OTHER)
