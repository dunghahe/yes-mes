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
from app.modules.orders.models import PROCESS_TYPES
from app.modules.orders.schemas import OrderCreate, OrderUpdate
from app.modules.orders.service import (
    OrderManagementError,
    create_order,
    get_order,
    list_orders,
    update_order,
)
from app.modules.products.service import list_active_products
from app.modules.users.models import UserPermission

router = APIRouter(prefix="/orders", tags=["orders"])
templates = Jinja2Templates(directory="app/templates")
PROCESS_LABELS = {
    "FULL": "Đầy đủ (SX và Bavia)",
    "SX_ONLY": "Chỉ sản xuất",
    "BAVIA_ONLY": "Chỉ Bavia",
}
FIELD_ERRORS = {
    "po_no": "Nhập số PO từ 1 đến 100 ký tự.",
    "product_id": "Chọn một mã hàng đang sử dụng.",
    "ordered_quantity": "Số lượng đặt phải là số nguyên dương.",
    "process_type": "Chọn loại công đoạn.",
    "raw_material_code": "Nhập mã nguyên vật liệu.",
    "drawing_number": "Nhập mã bản vẽ.",
    "revision": "Nhập REV.",
    "material": "Nhập chất liệu.",
    "blank_size": "Nhập kích cỡ phôi.",
    "order_received_date": "Chọn ngày nhận đơn hàng.",
}


def _render(
    request: Request,
    db: Session,
    template_name: str,
    context: dict[str, object],
    *,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    token = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            **context,
            "title": context.get("title", "Quản lý PO"),
            "products": list_active_products(db),
            "process_types": PROCESS_TYPES,
            "process_labels": PROCESS_LABELS,
            "csrf_token": token,
        },
        status_code=status_code,
    )
    set_csrf_cookie(response, token)
    return response


def _validation_errors(error: ValidationError) -> dict[str, str]:
    result = {}
    for item in error.errors():
        field = str(item["loc"][0]) if item["loc"] else "form"
        result[field] = FIELD_ERRORS.get(field, "Giá trị không hợp lệ.")
    return result


def _can_order_action(db: Session, actor: User, action: str) -> bool:
    extra_permissions = frozenset(
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
    return has_permission(actor.role, "orders", action, extra_permissions)


def _submitted_values(
    po_no: str,
    product_id: int,
    ordered_quantity: int,
    process_type: str,
    raw_material_code: str,
    drawing_number: str,
    revision: str,
    material: str,
    blank_size: str,
    order_received_date: date,
    notes: str | None,
) -> dict[str, object]:
    return {
        "po_no": po_no,
        "product_id": product_id,
        "ordered_quantity": ordered_quantity,
        "process_type": process_type,
        "raw_material_code": raw_material_code,
        "drawing_number": drawing_number,
        "revision": revision,
        "material": material,
        "blank_size": blank_size,
        "order_received_date": order_received_date.isoformat(),
        "notes": notes or "",
    }


@router.get("", response_class=HTMLResponse)
def orders_page(
    request: Request,
    actor: Annotated[User, Depends(require_permission("orders", "view"))],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    return _render(
        request,
        db,
        "orders/list.html",
        {
            "title": "Danh sách PO",
            "orders": list_orders(db),
            "can_create": _can_order_action(db, actor, "create"),
            "can_edit": _can_order_action(db, actor, "edit"),
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_order_page(
    request: Request,
    _actor: Annotated[User, Depends(require_permission("orders", "create"))],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    return _render(
        request,
        db,
        "orders/form.html",
        {
            "title": "Tạo PO",
            "order": None,
            "product": None,
            "submitted": {},
            "errors": {},
            "error": None,
        },
    )


@router.post("", response_class=HTMLResponse)
def create_order_submit(
    request: Request,
    csrf_token: Annotated[str, Form()],
    po_no: Annotated[str, Form()],
    product_id: Annotated[int, Form()],
    ordered_quantity: Annotated[int, Form()],
    process_type: Annotated[str, Form()],
    raw_material_code: Annotated[str, Form()],
    drawing_number: Annotated[str, Form()],
    revision: Annotated[str, Form()],
    material: Annotated[str, Form()],
    blank_size: Annotated[str, Form()],
    order_received_date: Annotated[date, Form()],
    actor: Annotated[User, Depends(require_permission("orders", "create"))],
    db: Annotated[Session, Depends(get_db)],
    notes: Annotated[str | None, Form()] = None,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = _submitted_values(
        po_no,
        product_id,
        ordered_quantity,
        process_type,
        raw_material_code,
        drawing_number,
        revision,
        material,
        blank_size,
        order_received_date,
        notes,
    )
    try:
        create_order(db, OrderCreate.model_validate(submitted), actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render(
            request,
            db,
            "orders/form.html",
            {
                "title": "Tạo PO",
                "order": None,
                "product": None,
                "submitted": submitted,
                "errors": _validation_errors(exc),
                "error": None,
            },
            status_code=422,
        )
    except (OrderManagementError, IntegrityError) as exc:
        db.rollback()
        message = (
            str(exc) if isinstance(exc, OrderManagementError) else "Số PO này đã được sử dụng."
        )
        return _render(
            request,
            db,
            "orders/form.html",
            {
                "title": "Tạo PO",
                "order": None,
                "product": None,
                "submitted": submitted,
                "errors": {},
                "error": message,
            },
            status_code=422,
        )
    return RedirectResponse("/orders", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{order_id}", response_class=HTMLResponse)
def edit_order_page(
    request: Request,
    order_id: int,
    _actor: Annotated[User, Depends(require_permission("orders", "edit"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    row = get_order(db, order_id)
    if row is None:
        return Response("Không tìm thấy PO.", status_code=404)
    order, product = row
    return _render(
        request,
        db,
        "orders/form.html",
        {
            "title": "Sửa PO",
            "order": order,
            "product": product,
            "submitted": {},
            "errors": {},
            "error": None,
        },
    )


@router.post("/{order_id}", response_class=HTMLResponse)
def update_order_submit(
    request: Request,
    order_id: int,
    csrf_token: Annotated[str, Form()],
    po_no: Annotated[str, Form()],
    product_id: Annotated[int, Form()],
    ordered_quantity: Annotated[int, Form()],
    process_type: Annotated[str, Form()],
    raw_material_code: Annotated[str, Form()],
    drawing_number: Annotated[str, Form()],
    revision: Annotated[str, Form()],
    material: Annotated[str, Form()],
    blank_size: Annotated[str, Form()],
    order_received_date: Annotated[date, Form()],
    actor: Annotated[User, Depends(require_permission("orders", "edit"))],
    db: Annotated[Session, Depends(get_db)],
    notes: Annotated[str | None, Form()] = None,
    version: Annotated[int, Form()] = 1,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = _submitted_values(
        po_no,
        product_id,
        ordered_quantity,
        process_type,
        raw_material_code,
        drawing_number,
        revision,
        material,
        blank_size,
        order_received_date,
        notes,
    )
    try:
        update_order(
            db, order_id, OrderUpdate.model_validate({**submitted, "version": version}), actor.id
        )
        db.commit()
    except ValidationError as exc:
        db.rollback()
        row = get_order(db, order_id)
        if row is None:
            return Response("Không tìm thấy PO.", status_code=404)
        order, product = row
        return _render(
            request,
            db,
            "orders/form.html",
            {
                "title": "Sửa PO",
                "order": order,
                "product": product,
                "submitted": submitted,
                "errors": _validation_errors(exc),
                "error": None,
            },
            status_code=422,
        )
    except (OrderManagementError, IntegrityError) as exc:
        db.rollback()
        row = get_order(db, order_id)
        if row is None:
            return Response("Không tìm thấy PO.", status_code=404)
        order, product = row
        message = (
            str(exc) if isinstance(exc, OrderManagementError) else "Số PO này đã được sử dụng."
        )
        return _render(
            request,
            db,
            "orders/form.html",
            {
                "title": "Sửa PO",
                "order": order,
                "product": product,
                "submitted": submitted,
                "errors": {},
                "error": message,
            },
            status_code=422,
        )
    return RedirectResponse("/orders", status_code=status.HTTP_303_SEE_OTHER)
