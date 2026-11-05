import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, set_csrf_cookie
from app.core.db import get_db
from app.core.permissions import require_admin
from app.modules.auth.models import User
from app.modules.defects.models import DETECTION_PROCESSES
from app.modules.defects.schemas import DefectCodeCreate, DefectCodeUpdate
from app.modules.defects.service import (
    DefectCodeError,
    create_defect_code,
    list_defect_codes,
    update_defect_code,
)

router = APIRouter(prefix="/admin/defect-codes", tags=["defect-codes"])
templates = Jinja2Templates(directory="app/templates")
PROCESS_LABELS = {"SX": "QC sản xuất", "BAVIA": "QC Bavia"}


def _render(
    request: Request,
    db: Session,
    *,
    error: str | None = None,
    submitted: dict[str, object] | None = None,
    errors: dict[str, str] | None = None,
) -> HTMLResponse:
    csrf_token = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        request=request,
        name="defects/manage.html",
        context={
            "title": "Danh mục mã lỗi",
            "defect_codes": list_defect_codes(db),
            "processes": DETECTION_PROCESSES,
            "process_labels": PROCESS_LABELS,
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
def defect_codes_page(
    request: Request,
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    return _render(request, db)


@router.post("")
def create_defect_code_submit(
    request: Request,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    defect_group: Annotated[str, Form()],
    detected_at: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {
        "code": code,
        "name": name,
        "defect_group": defect_group,
        "detected_at": detected_at,
    }
    try:
        create_defect_code(db, DefectCodeCreate.model_validate(submitted), actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        errors = {
            str(item["loc"][0]): "Giá trị không hợp lệ hoặc vượt giới hạn cho phép."
            for item in exc.errors()
            if item["loc"]
        }
        return _render(request, db, submitted=submitted, errors=errors)
    except (DefectCodeError, IntegrityError) as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, DefectCodeError) else "Mã lỗi này đã được sử dụng."
        return _render(request, db, submitted=submitted, error=message)
    return RedirectResponse("/admin/defect-codes", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{defect_code_id}")
def update_defect_code_submit(
    request: Request,
    defect_code_id: int,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    defect_group: Annotated[str, Form()],
    detected_at: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    is_active: Annotated[bool, Form()] = False,
    version: Annotated[int, Form()] = 1,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        data = DefectCodeUpdate(
            code=code,
            name=name,
            defect_group=defect_group,
            detected_at=detected_at,
            is_active=is_active,
            version=version,
        )
        update_defect_code(db, defect_code_id, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        errors = {
            str(item["loc"][0]): "Giá trị không hợp lệ hoặc vượt giới hạn cho phép."
            for item in exc.errors()
            if item["loc"]
        }
        return _render(request, db, errors=errors)
    except (DefectCodeError, IntegrityError) as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, DefectCodeError) else "Mã lỗi này đã được sử dụng."
        return _render(request, db, error=message)
    return RedirectResponse("/admin/defect-codes", status_code=status.HTTP_303_SEE_OTHER)
