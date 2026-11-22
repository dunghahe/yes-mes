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
from app.modules.assets.schemas import MachineInput, MachineUpdate
from app.modules.assets.service import (
    AssetManagementError,
    create_machine,
    create_pair,
    list_active_machines,
    list_machines,
    list_pairs,
    update_machine,
    update_pair_status,
)
from app.modules.auth.models import User

router = APIRouter(prefix="/admin/machines", tags=["machines"])
templates = Jinja2Templates(directory="app/templates")


def _render(request: Request, db: Session, error: str | None = None) -> HTMLResponse:
    token = csrf_token_for_request(request)
    response = templates.TemplateResponse(
        request=request,
        name="assets/manage.html",
        context={
            "title": "Máy và cặp máy",
            "machines": list_machines(db),
            "active_machines": list_active_machines(db),
            "pairs": list_pairs(db),
            "error": error,
            "csrf_token": token,
        },
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY if error else status.HTTP_200_OK,
    )
    set_csrf_cookie(response, token)
    return response


def _form_error(error: Exception) -> str:
    if isinstance(error, AssetManagementError):
        return str(error)
    if isinstance(error, ValidationError):
        return "Thông tin chưa hợp lệ. Hãy kiểm tra các trường bắt buộc và định dạng."
    return "Mã đã được sử dụng hoặc dữ liệu đang được tham chiếu. Hãy tải lại rồi thử lại."


def _csrf_error(request: Request, token: str) -> bool:
    return csrf_is_valid(request, token)


@router.get("", response_class=HTMLResponse)
def manage_assets_page(
    request: Request,
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    return _render(request, db)


@router.post("/machines")
def add_machine(
    request: Request,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    production_area: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not _csrf_error(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        create_machine(
            db, MachineInput(code=code, name=name, production_area=production_area), actor.id
        )
        db.commit()
    except (ValidationError, AssetManagementError, IntegrityError) as exc:
        db.rollback()
        return _render(request, db, _form_error(exc))
    return RedirectResponse("/admin/machines", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/pairs")
def add_pair(
    request: Request,
    csrf_token: Annotated[str, Form()],
    machine_1_id: Annotated[int, Form()],
    machine_2_id: Annotated[int, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not _csrf_error(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        create_pair(db, machine_1_id, machine_2_id, actor.id)
        db.commit()
    except (AssetManagementError, IntegrityError) as exc:
        db.rollback()
        return _render(request, db, _form_error(exc))
    return RedirectResponse("/admin/machines", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/machines/{machine_id}")
def edit_machine(
    request: Request,
    machine_id: int,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    production_area: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    is_active: Annotated[bool, Form()] = False,
    version: Annotated[int, Form()] = 1,
) -> Response:
    if not _csrf_error(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        update_machine(
            db,
            machine_id,
            MachineUpdate(
                code=code,
                name=name,
                production_area=production_area,
                is_active=is_active,
                version=version,
            ),
            actor.id,
        )
        db.commit()
    except (ValidationError, AssetManagementError, IntegrityError) as exc:
        db.rollback()
        return _render(request, db, _form_error(exc))
    return RedirectResponse("/admin/machines", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/pairs/{pair_id}/status")
def edit_pair_status(
    request: Request,
    pair_id: int,
    csrf_token: Annotated[str, Form()],
    is_active: Annotated[bool, Form()],
    version: Annotated[int, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not _csrf_error(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        update_pair_status(db, pair_id, is_active, version, actor.id)
        db.commit()
    except (AssetManagementError, IntegrityError) as exc:
        db.rollback()
        return _render(request, db, _form_error(exc))
    return RedirectResponse("/admin/machines", status_code=status.HTTP_303_SEE_OTHER)
