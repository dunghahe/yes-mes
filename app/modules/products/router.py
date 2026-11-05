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
from app.modules.products.models import PROCESS_TYPES, Product
from app.modules.products.schemas import ProductCreate, ProductUpdate
from app.modules.products.service import (
    ProductManagementError,
    create_product,
    list_products,
    update_product,
)

router = APIRouter(prefix="/admin/products", tags=["products"])
templates = Jinja2Templates(directory="app/templates")
PROCESS_TYPE_LABELS = {
    "FULL": "Đầy đủ (SX và Bavia)",
    "SX_ONLY": "Chỉ sản xuất",
    "BAVIA_ONLY": "Chỉ Bavia",
}


def _render(
    request: Request,
    template_name: str,
    context: dict[str, object],
    *,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    csrf_token = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        request=request,
        name=template_name,
        context={**context, "csrf_token": csrf_token},
        status_code=status_code,
    )
    set_csrf_cookie(response, csrf_token)
    return response


def _field_errors(error: ValidationError) -> dict[str, str]:
    messages = {
        "code": "Nhập mã hàng từ 1 đến 100 ký tự.",
        "name": "Nhập tên hàng từ 1 đến 200 ký tự.",
        "cycle_time_seconds": "Cycle time phải lớn hơn 0 và tối đa 3 chữ số thập phân.",
        "default_process_type": "Chọn loại công đoạn mặc định hợp lệ.",
        "version": "Dữ liệu biểu mẫu không còn mới. Hãy tải lại trang.",
    }
    return {
        str(item["loc"][0]) if item["loc"] else "form": messages.get(
            str(item["loc"][0]) if item["loc"] else "form",
            "Giá trị không hợp lệ.",
        )
        for item in error.errors()
    }


def _form_context(
    *,
    product: Product | None = None,
    error: str | None = None,
    errors: dict[str, str] | None = None,
    submitted: dict[str, str | bool] | None = None,
) -> dict[str, object]:
    return {
        "title": "Sửa mã hàng" if product else "Tạo mã hàng",
        "product": product,
        "process_types": PROCESS_TYPES,
        "process_type_labels": PROCESS_TYPE_LABELS,
        "error": error,
        "errors": errors or {},
        "submitted": submitted or {},
    }


@router.get("", response_class=HTMLResponse)
def product_list_page(
    request: Request,
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    return _render(
        request,
        "products/list.html",
        {
            "title": "Quản lý mã hàng",
            "products": list_products(db),
            "process_type_labels": PROCESS_TYPE_LABELS,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_product_page(
    request: Request,
    _actor: Annotated[User, Depends(require_admin)],
) -> HTMLResponse:
    return _render(request, "products/form.html", _form_context())


@router.post("", response_class=HTMLResponse)
def create_product_submit(
    request: Request,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    cycle_time_seconds: Annotated[str, Form()],
    default_process_type: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {
        "code": code,
        "name": name,
        "cycle_time_seconds": cycle_time_seconds,
        "default_process_type": default_process_type,
    }
    try:
        data = ProductCreate.model_validate(submitted)
        create_product(db, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render(
            request,
            "products/form.html",
            _form_context(errors=_field_errors(exc), submitted=submitted),
            status_code=422,
        )
    except (ProductManagementError, IntegrityError) as exc:
        db.rollback()
        message = (
            str(exc) if isinstance(exc, ProductManagementError) else "Mã hàng này đã được sử dụng."
        )
        return _render(
            request,
            "products/form.html",
            _form_context(error=message, submitted=submitted),
            status_code=422,
        )
    return RedirectResponse("/admin/products", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{product_id}", response_class=HTMLResponse)
def edit_product_page(
    request: Request,
    product_id: int,
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    product = db.get(Product, product_id)
    if product is None or product.deleted_at is not None:
        return Response("Không tìm thấy mã hàng.", status_code=404)
    return _render(request, "products/form.html", _form_context(product=product))


@router.post("/{product_id}", response_class=HTMLResponse)
def update_product_submit(
    request: Request,
    product_id: int,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    cycle_time_seconds: Annotated[str, Form()],
    default_process_type: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    is_active: Annotated[bool, Form()] = False,
    version: Annotated[int, Form()] = 1,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {
        "code": code,
        "name": name,
        "cycle_time_seconds": cycle_time_seconds,
        "default_process_type": default_process_type,
        "is_active": is_active,
        "version": version,
    }
    try:
        data = ProductUpdate.model_validate(submitted)
        update_product(db, product_id, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        product = db.get(Product, product_id)
        if product is None or product.deleted_at is not None:
            return Response("Không tìm thấy mã hàng.", status_code=404)
        return _render(
            request,
            "products/form.html",
            _form_context(
                product=product,
                errors=_field_errors(exc),
                submitted={
                    key: value if key == "is_active" else str(value)
                    for key, value in submitted.items()
                },
            ),
            status_code=422,
        )
    except (ProductManagementError, IntegrityError) as exc:
        db.rollback()
        product = db.get(Product, product_id)
        if product is None or product.deleted_at is not None:
            return Response("Không tìm thấy mã hàng.", status_code=404)
        message = (
            str(exc) if isinstance(exc, ProductManagementError) else "Mã hàng này đã được sử dụng."
        )
        return _render(
            request,
            "products/form.html",
            _form_context(product=product, error=message),
            status_code=422,
        )
    return RedirectResponse("/admin/products", status_code=status.HTTP_303_SEE_OTHER)
