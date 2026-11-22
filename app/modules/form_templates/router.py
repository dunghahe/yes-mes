from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, csrf_token_for_request, set_csrf_cookie
from app.core.db import get_db
from app.core.permissions import require_admin
from app.modules.auth.models import User
from app.modules.form_templates.service import (
    FormTemplateError,
    active_template,
    preview_template_pages,
    template_status,
    upload_template,
)

router = APIRouter(prefix="/admin/form-templates", tags=["form-templates"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def form_templates_page(
    request: Request,
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    token = csrf_token_for_request(request)
    response = templates.TemplateResponse(
        request=request,
        name="form_templates/manage.html",
        context={
            "title": "Mẫu biểu in",
            "active_template": template_status(db),
            "csrf_token": token,
        },
    )
    set_csrf_cookie(response, token)
    return response


@router.get("/current.xlsx")
def download_current_template(
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    return Response(
        content=active_template(db),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="mau-bieu-dang-dung.xlsx"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/preview", response_class=HTMLResponse)
def preview_current_template(
    request: Request,
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    try:
        pages = preview_template_pages(active_template(db))
    except FormTemplateError as exc:
        return Response(str(exc), status_code=422)
    response = templates.TemplateResponse(
        request=request,
        name="form_templates/preview.html",
        context={
            "title": "Xem trước mẫu biểu đang dùng",
            "pages": pages,
            "auto_print": False,
            "request_number": None,
        },
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/preview.pdf")
def legacy_template_preview() -> RedirectResponse:
    return RedirectResponse("/admin/form-templates/preview", status_code=303)


@router.post("")
async def replace_form_template(
    request: Request,
    csrf_token: Annotated[str, Form()],
    workbook: Annotated[UploadFile, File()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        content = await workbook.read(10 * 1024 * 1024 + 1)
        upload_template(db, workbook.filename or "mau-bieu.xlsx", content, actor.id)
        db.commit()
    except FormTemplateError as exc:
        db.rollback()
        return Response(str(exc), status_code=422)
    return RedirectResponse("/admin/form-templates", status_code=303)
