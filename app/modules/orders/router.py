from datetime import date
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, csrf_token_for_request, set_csrf_cookie
from app.core.db import get_db
from app.core.excel_imports import discard_preview, get_preview, parse_xlsx, store_preview
from app.core.permissions import has_permission, require_permission
from app.modules.auth.models import User
from app.modules.orders.lifecycle import close_order_manually
from app.modules.orders.models import PROCESS_TYPES, ProductionOrder
from app.modules.orders.schemas import OrderCreate, OrderUpdate
from app.modules.orders.service import (
    OrderManagementError,
    count_orders,
    create_order,
    get_order,
    list_orders,
    order_progress_summary,
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
ORDER_STATUS_LABELS = {
    "open": "Đang mở",
    "in_progress": "Đang sản xuất",
    "done": "Hoàn thành",
    "cancelled": "Đã hủy",
}
FIELD_ERRORS = {
    "po_no": "Nhập số PO từ 1 đến 100 ký tự.",
    "product_id": "Chọn một mã hàng đang sử dụng.",
    "ordered_quantity": "Số lượng đặt phải là số nguyên dương.",
    "lot_size": "Số lượng mỗi lô phải là số nguyên dương.",
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
    token = csrf_token_for_request(request)
    render_context = dict(context)
    if template_name == "orders/list.html":
        order_rows = context.get("orders", [])
        render_context["order_progress"] = order_progress_summary(
            db, [row[0].id for row in order_rows]
        )
    response = templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            **render_context,
            "title": render_context.get("title", "Quản lý PO"),
            "products": list_active_products(db),
            "process_types": PROCESS_TYPES,
            "process_labels": PROCESS_LABELS,
            "order_status_labels": ORDER_STATUS_LABELS,
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
    product_id: str | int,
    ordered_quantity: str | int,
    lot_size: str | int,
    process_type: str,
    raw_material_code: str,
    drawing_number: str,
    revision: str,
    material: str,
    blank_size: str,
    order_received_date: str | date,
    notes: str | None,
) -> dict[str, object]:
    return {
        "po_no": po_no,
        "product_id": product_id,
        "ordered_quantity": ordered_quantity,
        "lot_size": lot_size,
        "process_type": process_type,
        "raw_material_code": raw_material_code,
        "drawing_number": drawing_number,
        "revision": revision,
        "material": material,
        "blank_size": blank_size,
        "order_received_date": (
            order_received_date.isoformat()
            if isinstance(order_received_date, date)
            else order_received_date
        ),
        "notes": notes or "",
    }


@router.get("", response_class=HTMLResponse)
def orders_page(
    request: Request,
    actor: Annotated[User, Depends(require_permission("orders", "view"))],
    db: Annotated[Session, Depends(get_db)],
    new: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
) -> HTMLResponse:
    page_size = 100
    total = count_orders(db)
    return _render(
        request,
        db,
        "orders/list.html",
        {
            "title": "Danh sách PO",
            "orders": list_orders(db, limit=page_size, offset=(page - 1) * page_size),
            "page": page,
            "page_count": max(1, (total + page_size - 1) // page_size),
            "can_create": _can_order_action(db, actor, "create"),
            "can_edit": _can_order_action(db, actor, "edit"),
            "open_create": new,
            "submitted": {},
            "errors": {},
            "error": None,
            "open_import": False,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_order_page(
    request: Request,
    _actor: Annotated[User, Depends(require_permission("orders", "create"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    return RedirectResponse("/orders?new=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("", response_class=HTMLResponse)
def create_order_submit(
    request: Request,
    csrf_token: Annotated[str, Form()],
    po_no: Annotated[str, Form()],
    product_id: Annotated[str, Form()],
    ordered_quantity: Annotated[str, Form()],
    lot_size: Annotated[str, Form()],
    process_type: Annotated[str, Form()],
    raw_material_code: Annotated[str, Form()],
    drawing_number: Annotated[str, Form()],
    revision: Annotated[str, Form()],
    material: Annotated[str, Form()],
    blank_size: Annotated[str, Form()],
    order_received_date: Annotated[str, Form()],
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
        lot_size,
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
            "orders/list.html",
            {
                "title": "Danh sách PO",
                "orders": list_orders(db),
                "can_create": True,
                "can_edit": _can_order_action(db, actor, "edit"),
                "open_create": True,
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
            "orders/list.html",
            {
                "title": "Danh sách PO",
                "orders": list_orders(db),
                "can_create": True,
                "can_edit": _can_order_action(db, actor, "edit"),
                "open_create": True,
                "submitted": submitted,
                "error": None,
                "errors": {"po_no" if "PO" in message else "product_id": message},
            },
            status_code=422,
        )
    return RedirectResponse("/orders", status_code=status.HTTP_303_SEE_OTHER)


ORDER_IMPORT_HEADERS = [
    "Số PO",
    "Mã hàng",
    "Số lượng đặt",
    "Số lượng mỗi lô",
    "Công đoạn (FULL/SX_ONLY/BAVIA_ONLY)",
    "Mã nguyên vật liệu",
    "Mã bản vẽ",
    "REV",
    "Chất liệu",
    "Kích cỡ phôi",
    "Ngày nhận đơn (YYYY-MM-DD)",
    "Ghi chú",
]


@router.get("/import/template")
def order_import_template(
    _actor: Annotated[User, Depends(require_permission("orders", "create"))],
) -> StreamingResponse:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Orders"
    sheet.append(ORDER_IMPORT_HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1D4ED8")
    for index, width in enumerate((20, 22, 18, 20, 34, 24, 22, 14, 18, 20, 24, 32), start=1):
        sheet.column_dimensions[chr(64 + index)].width = width
    sheet.freeze_panes = "A2"
    process_choices = DataValidation(
        type="list", formula1='"FULL,SX_ONLY,BAVIA_ONLY"', allow_blank=False
    )
    sheet.add_data_validation(process_choices)
    process_choices.add("E2:E5001")
    guide = workbook.create_sheet("HuongDan")
    guide.append(["HƯỚNG DẪN NHẬP PO"])
    guide.append(["Mỗi dòng trên sheet Orders là một PO."])
    guide.append(["Không đổi tên sheet hoặc hàng tiêu đề."])
    guide.append(["Mã hàng phải được khai báo và đang hoạt động trong hệ thống."])
    guide.append(["Công đoạn: FULL, SX_ONLY hoặc BAVIA_ONLY (chọn từ danh sách)."])
    guide.append(
        ["Số lượng mỗi lô phải là số nguyên dương; PO được tự chia lô, lô cuối có thể ít hơn."]
    )
    guide.append(["Ngày nhận đơn nhập theo năm-tháng-ngày, ví dụ 2026-11-14."])
    guide.append(
        ["Điền đủ thông tin kho nguyên vật liệu; tải file lên để kiểm tra rồi xác nhận nhập."]
    )
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="mau-po.xlsx"'},
    )


@router.post("/import/preview", response_class=HTMLResponse)
async def order_import_preview(
    request: Request,
    actor: Annotated[User, Depends(require_permission("orders", "create"))],
    db: Annotated[Session, Depends(get_db)],
    csrf_token: Annotated[str, Form()],
    upload: Annotated[UploadFile, File()],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    if not upload.filename or not upload.filename.lower().endswith(".xlsx"):
        return _render(
            request,
            db,
            "orders/list.html",
            {
                "title": "Danh sách PO",
                "orders": list_orders(db),
                "can_create": True,
                "can_edit": _can_order_action(db, actor, "edit"),
                "open_create": False,
                "open_import": True,
                "submitted": {},
                "errors": {},
                "error": "Chỉ nhận file .xlsx.",
            },
            status_code=422,
        )
    try:
        rows = parse_xlsx(await upload.read(10 * 1024 * 1024 + 1), "Orders", ORDER_IMPORT_HEADERS)
    except ValueError as exc:
        return _render(
            request,
            db,
            "orders/list.html",
            {
                "title": "Danh sách PO",
                "orders": list_orders(db),
                "can_create": True,
                "can_edit": _can_order_action(db, actor, "edit"),
                "open_create": False,
                "open_import": True,
                "submitted": {},
                "errors": {},
                "error": str(exc),
            },
            status_code=422,
        )

    products = {product.code.casefold(): product for product in list_active_products(db)}
    existing_po = {
        value.casefold()
        for value in db.scalars(
            select(ProductionOrder.po_no).where(ProductionOrder.deleted_at.is_(None))
        )
    }
    seen: set[str] = set()
    errors: list[dict[str, int | str]] = []
    for row in rows:
        po_no = row["Số PO"].strip()
        product = products.get(row["Mã hàng"].casefold())
        if not po_no or len(po_no) > 100:
            errors.append(
                {"row": int(row["__row__"]), "message": "Số PO bắt buộc, tối đa 100 ký tự."}
            )
        elif po_no.casefold() in existing_po or po_no.casefold() in seen:
            errors.append(
                {"row": int(row["__row__"]), "message": f"Số PO '{po_no}' đã tồn tại hoặc bị lặp."}
            )
        if po_no:
            seen.add(po_no.casefold())
        if product is None:
            errors.append(
                {
                    "row": int(row["__row__"]),
                    "message": f"Mã hàng '{row['Mã hàng']}' chưa tồn tại hoặc đã ngừng dùng.",
                }
            )
            continue
        values = {
            "po_no": po_no,
            "product_id": product.id,
            "ordered_quantity": row["Số lượng đặt"],
            "lot_size": row["Số lượng mỗi lô"],
            "process_type": row["Công đoạn (FULL/SX_ONLY/BAVIA_ONLY)"],
            "raw_material_code": row["Mã nguyên vật liệu"],
            "drawing_number": row["Mã bản vẽ"],
            "revision": row["REV"],
            "material": row["Chất liệu"],
            "blank_size": row["Kích cỡ phôi"],
            "order_received_date": row["Ngày nhận đơn (YYYY-MM-DD)"],
            "notes": row["Ghi chú"] or None,
        }
        try:
            OrderCreate.model_validate(values)
        except ValidationError as exc:
            fields = _validation_errors(exc)
            errors.append({"row": int(row["__row__"]), "message": "; ".join(fields.values())})
    token = store_preview(db, actor.id, "orders", rows, errors) if not errors else ""
    if token:
        db.commit()
    response = _render(
        request,
        "imports/preview.html",
        {
            "title": "Kiểm tra file PO",
            "resource": "orders",
            "rows": rows,
            "errors": errors,
            "token": token,
            "confirm_url": f"/orders/import/{token}/confirm" if token else "",
            "return_url": "/orders",
        },
    )
    return response


@router.post("/import/{token}/confirm", response_class=HTMLResponse)
def order_import_confirm(
    request: Request,
    token: str,
    csrf_token: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_permission("orders", "create"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    preview = get_preview(db, token, actor.id, "orders")
    if preview is None:
        return Response("Phiên xem trước đã hết hạn. Hãy tải file lên lại.", status_code=410)
    if preview.errors:
        return Response("File còn lỗi, chưa thể nhập.", status_code=422)
    products = {product.code.casefold(): product for product in list_active_products(db)}
    try:
        for row in preview.rows:
            product = products.get(row["Mã hàng"].casefold())
            if product is None:
                raise OrderManagementError(f"Mã hàng '{row['Mã hàng']}' không còn sử dụng.")
            data = OrderCreate.model_validate(
                {
                    "po_no": row["Số PO"],
                    "product_id": product.id,
                    "ordered_quantity": row["Số lượng đặt"],
                    "lot_size": row["Số lượng mỗi lô"],
                    "process_type": row["Công đoạn (FULL/SX_ONLY/BAVIA_ONLY)"],
                    "raw_material_code": row["Mã nguyên vật liệu"],
                    "drawing_number": row["Mã bản vẽ"],
                    "revision": row["REV"],
                    "material": row["Chất liệu"],
                    "blank_size": row["Kích cỡ phôi"],
                    "order_received_date": row["Ngày nhận đơn (YYYY-MM-DD)"],
                    "notes": row["Ghi chú"] or None,
                }
            )
            create_order(db, data, actor.id)
        discard_preview(db, preview)
        db.commit()
    except (ValidationError, OrderManagementError, IntegrityError) as exc:
        db.rollback()
        return Response(f"Không nhập được file; không dòng nào được lưu. {exc}", status_code=422)
    return RedirectResponse("/orders", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{order_id}/close")
def close_order_submit(
    order_id: int,
    request: Request,
    reason: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_permission("orders", "edit"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        close_order_manually(db, order_id, actor.id, reason)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return Response(str(exc), status_code=409)
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
    lot_size: Annotated[int, Form()],
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
        lot_size,
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
