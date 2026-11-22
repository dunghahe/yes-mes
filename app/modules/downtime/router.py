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
from app.modules.downtime.schemas import DowntimeReasonCreate, DowntimeReasonUpdate
from app.modules.downtime.service import (
    DowntimeReasonError,
    create_reason,
    list_reasons,
    update_reason,
)

router = APIRouter(prefix="/admin/downtime-reasons", tags=["downtime-reasons"])
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
        name="downtime/manage.html",
        context={
            "title": "Lý do dừng máy",
            "reasons": list_reasons(db),
            "error": error,
            "submitted": submitted or {},
            "errors": errors or {},
            "csrf_token": csrf_token,
        },
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY if error or errors else status.HTTP_200_OK,
    )
    set_csrf_cookie(response, csrf_token)
    return response


@router.get("", response_class=HTMLResponse)
def downtime_reasons_page(
    request: Request,
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    return _render(request, db)


@router.post("")
def create_downtime_reason(
    request: Request,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {"code": code, "name": name}
    try:
        create_reason(db, DowntimeReasonCreate.model_validate(submitted), actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        errors = {
            str(item["loc"][0]): "Giá trị không hợp lệ hoặc vượt giới hạn cho phép."
            for item in exc.errors()
            if item["loc"]
        }
        return _render(request, db, submitted=submitted, errors=errors)
    except (DowntimeReasonError, IntegrityError) as exc:
        db.rollback()
        message = (
            str(exc)
            if isinstance(exc, DowntimeReasonError)
            else "Mã lý do dừng máy này đã được sử dụng."
        )
        return _render(request, db, submitted=submitted, error=message)
    return RedirectResponse("/admin/downtime-reasons", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{reason_id}")
def update_downtime_reason(
    request: Request,
    reason_id: int,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    is_active: Annotated[bool, Form()] = False,
    version: Annotated[int, Form()] = 1,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        update_reason(
            db,
            reason_id,
            DowntimeReasonUpdate(
                code=code,
                name=name,
                is_active=is_active,
                version=version,
            ),
            actor.id,
        )
        db.commit()
    except (ValidationError, DowntimeReasonError, IntegrityError) as exc:
        db.rollback()
        message = (
            str(exc)
            if isinstance(exc, DowntimeReasonError)
            else "Mã hoặc tên lý do dừng máy không hợp lệ."
        )
        return _render(request, db, error=message)
    return RedirectResponse("/admin/downtime-reasons", status_code=status.HTTP_303_SEE_OTHER)
