from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, csrf_token_for_request, set_csrf_cookie
from app.core.db import get_db
from app.core.permissions import has_permission, require_permission
from app.modules.auth.models import User
from app.modules.blank_requests.schemas import (
    BlankRequestCancel,
    BlankRequestCreate,
    BlankRequestDelivery,
    BlankRequestUpdate,
)
from app.modules.blank_requests.service import (
    BlankRequestManagementError,
    active_operators,
    active_pairs,
    available_schedules,
    can_edit_request,
    cancel_blank_request,
    confirm_delivery,
    count_blank_request_rows,
    create_blank_request,
    get_blank_request,
    get_printable_request,
    list_blank_requests,
    operators_for_request,
    print_resource_details,
    queue_print_stats,
    register_print,
    request_pair_assignments,
    request_pair_options,
    request_resources,
    update_blank_request,
)
from app.modules.form_templates.service import (
    FormTemplateError,
    active_template,
    pdf_pages_as_data_urls,
    render_lot_qc_batch_pdf,
    render_template_pdf,
    template_replacements,
)
from app.modules.orders.models import ProductionLot, ProductionOrder
from app.modules.products.models import Product
from app.modules.users.models import UserPermission

router = APIRouter(prefix="/blank-requests", tags=["blank-requests"])
warehouse_router = APIRouter(prefix="/warehouse/blank-requests", tags=["warehouse"])
templates = Jinja2Templates(directory="app/templates")
STATUS_LABELS = {"submitted": "Chờ Kho NVL giao", "cancelled": "Đã hủy", "delivered": "Đã giao"}


def _render(
    request: Request,
    db: Session,
    *,
    actor: User,
    schedule_id: int | None = None,
    submitted: dict[str, object] | None = None,
    errors: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = status.HTTP_200_OK,
    page: int = 1,
    open_create: bool = False,
) -> HTMLResponse:
    token = csrf_token_for_request(request)
    available = available_schedules(db)
    schedule_valid = schedule_id is None or any(row[0].id == schedule_id for row in available)
    pair_options = active_pairs(db)
    page_size = 100
    total = count_blank_request_rows(db)
    request_rows = list_blank_requests(db, limit=page_size, offset=(page - 1) * page_size)
    resources = request_resources(db, [row[0].id for row in request_rows])
    response = templates.TemplateResponse(
        request=request,
        name="blank_requests/list.html",
        context={
            "title": "Yêu cầu xuất phôi",
            "requests": request_rows,
            "page": page,
            "page_count": max(1, (total + page_size - 1) // page_size),
            "request_resources": resources,
            "schedule_options": available,
            "schedule_id": schedule_id,
            "schedule_valid": schedule_valid,
            "open_create": open_create or schedule_id is not None or submitted is not None,
            "pair_options": pair_options,
            "operator_options": active_operators(db),
            "selected_pairs": set((submitted or {}).get("machine_pair_ids", [])),
            "selected_operators": set((submitted or {}).get("operator_ids", [])),
            "assignment_rows": _assignment_rows(submitted),
            "submitted": submitted or {},
            "errors": errors or {},
            "error": error,
            "status_labels": STATUS_LABELS,
            "can_create": _can_create(db, actor),
            "can_edit": _can_edit(db, actor),
            "actor_role": actor.role,
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


def _can_edit(db: Session, actor: User) -> bool:
    extras = frozenset(
        (permission.module, "edit")
        for permission in db.scalars(
            select(UserPermission).where(
                UserPermission.user_id == actor.id,
                UserPermission.deleted_at.is_(None),
            )
        )
        if permission.can_edit
    )
    return has_permission(actor.role, "blank_requests", "edit", extras)


def _field_errors(error: ValidationError) -> dict[str, str]:
    mapping = {
        "schedule_id": "Chọn dòng lịch đang sử dụng.",
        "machine_pair_ids": (
            "Mỗi cặp máy phải có đúng một người làm; hãy kiểm tra các dòng đã chọn."
        ),
        "operator_ids": "Mỗi cặp máy phải có đúng một người làm; hãy kiểm tra các dòng đã chọn.",
        "reason": "Nhập lý do từ 3 đến 500 ký tự.",
        "version": "Phiên bản yêu cầu không hợp lệ; hãy tải lại trang.",
    }
    return {
        str(item["loc"][0]) if item["loc"] else "form": mapping.get(
            str(item["loc"][0]) if item["loc"] else "form",
            "Mỗi cặp máy phải có đúng một người làm."
            if "Mỗi cặp máy" in str(item.get("msg", ""))
            else "Giá trị không hợp lệ.",
        )
        for item in error.errors()
    }


def _render_edit(
    request: Request,
    db: Session,
    actor: User,
    request_id: int,
    *,
    submitted: dict[str, object] | None = None,
    errors: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    row = get_blank_request(db, request_id)
    if row is None:
        return Response("Không tìm thấy yêu cầu phôi.", status_code=404)
    blank_request = row[0]
    pair_ids, operator_ids = request_resources(db, [request_id])[request_id]
    assignments = request_pair_assignments(db, request_id)
    token = csrf_token_for_request(request)
    response = templates.TemplateResponse(
        request=request,
        name="blank_requests/form.html",
        context={
            "title": f"Sửa yêu cầu {blank_request.req_no}",
            "request_row": row,
            "process_type": row[2].process_type,
            "pair_options": request_pair_options(db, pair_ids),
            "operator_options": operators_for_request(db, operator_ids),
            "selected_pairs": set(
                (submitted or {}).get(
                    "machine_pair_ids",
                    pair_ids,
                )
            ),
            "selected_operators": set((submitted or {}).get("operator_ids", operator_ids)),
            "assignments": assignments,
            "assignment_rows": _assignment_rows(submitted, assignments),
            "submitted": submitted or {},
            "errors": errors or {},
            "error": error,
            "can_cancel": blank_request.status == "submitted",
            "csrf_token": token,
        },
        status_code=status_code,
    )
    set_csrf_cookie(response, token)
    return response


def _assignment_rows(
    submitted: dict[str, object] | None,
    assignments: list[tuple[int, int | None]] | None = None,
) -> list[tuple[int | None, int | None]]:
    if submitted is not None and ("machine_pair_ids" in submitted or "operator_ids" in submitted):
        pairs = submitted.get("machine_pair_ids", [])
        operators = submitted.get("operator_ids", [])
        if isinstance(pairs, list) and isinstance(operators, list):
            rows = list(zip(pairs, operators, strict=False))
            return rows or [(None, None)]
    return assignments or [(None, None)]


@router.get("", response_class=HTMLResponse)
def blank_requests_page(
    request: Request,
    actor: Annotated[User, Depends(require_permission("blank_requests", "view"))],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
) -> HTMLResponse:
    return _render(request, db, actor=actor, page=page)


@router.get("/new", response_class=HTMLResponse)
def new_blank_request_page(
    request: Request,
    actor: Annotated[User, Depends(require_permission("blank_requests", "create"))],
    db: Annotated[Session, Depends(get_db)],
    schedule_id: int | None = None,
) -> HTMLResponse:
    return _render(request, db, actor=actor, schedule_id=schedule_id, open_create=True)


@router.post("", response_class=HTMLResponse)
def create_blank_request_submit(
    request: Request,
    csrf_token: Annotated[str, Form()],
    schedule_id: Annotated[int, Form()],
    actor: Annotated[User, Depends(require_permission("blank_requests", "create"))],
    db: Annotated[Session, Depends(get_db)],
    machine_pair_ids: Annotated[list[int] | None, Form()] = None,
    operator_ids: Annotated[list[int] | None, Form()] = None,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {
        "schedule_id": schedule_id,
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
            submitted=submitted,
            error=str(exc),
            status_code=422,
        )
    return RedirectResponse("/blank-requests", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{request_id}", response_class=HTMLResponse)
def edit_blank_request_page(
    request: Request,
    request_id: int,
    actor: Annotated[User, Depends(require_permission("blank_requests", "edit"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    row = get_blank_request(db, request_id)
    if row is None:
        return Response("Không tìm thấy yêu cầu phôi.", status_code=404)
    if not can_edit_request(row[0], actor.role):
        return Response("Yêu cầu này chỉ Admin được sửa sau khi đã giao.", status_code=403)
    return _render_edit(request, db, actor, request_id)


@router.post("/{request_id}", response_class=HTMLResponse)
def update_blank_request_submit(
    request: Request,
    request_id: int,
    csrf_token: Annotated[str, Form()],
    reason: Annotated[str, Form()],
    version: Annotated[int, Form()],
    actor: Annotated[User, Depends(require_permission("blank_requests", "edit"))],
    db: Annotated[Session, Depends(get_db)],
    machine_pair_ids: Annotated[list[int] | None, Form()] = None,
    operator_ids: Annotated[list[int] | None, Form()] = None,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {
        "machine_pair_ids": machine_pair_ids or [],
        "operator_ids": operator_ids or [],
        "reason": reason,
        "version": version,
    }
    try:
        data = BlankRequestUpdate.model_validate(submitted)
        update_blank_request(db, request_id, data, actor.id, actor.role)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render_edit(
            request,
            db,
            actor,
            request_id,
            submitted=submitted,
            errors=_field_errors(exc),
            status_code=422,
        )
    except BlankRequestManagementError as exc:
        db.rollback()
        return _render_edit(
            request,
            db,
            actor,
            request_id,
            submitted=submitted,
            error=str(exc),
            status_code=409,
        )
    return RedirectResponse("/blank-requests", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{request_id}/cancel", response_class=HTMLResponse)
def cancel_blank_request_submit(
    request: Request,
    request_id: int,
    csrf_token: Annotated[str, Form()],
    reason: Annotated[str, Form()],
    version: Annotated[int, Form()],
    actor: Annotated[User, Depends(require_permission("blank_requests", "edit"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        data = BlankRequestCancel.model_validate({"reason": reason, "version": version})
        cancel_blank_request(db, request_id, data.reason, data.version, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render_edit(
            request,
            db,
            actor,
            request_id,
            errors=_field_errors(exc),
            status_code=422,
        )
    except BlankRequestManagementError as exc:
        db.rollback()
        return _render_edit(request, db, actor, request_id, error=str(exc), status_code=409)
    return RedirectResponse("/blank-requests", status_code=status.HTTP_303_SEE_OTHER)


def _queue_context(db: Session, request_status: str = "submitted") -> dict[str, object]:
    request_status = request_status if request_status in {"submitted", "delivered"} else "submitted"
    requests = list_blank_requests(db, status=request_status)
    request_ids = [row[0].id for row in requests]
    return {
        "requests": requests,
        "print_stats": queue_print_stats(db, request_ids),
        "request_resources": request_resources(db, request_ids),
        "queue_count": len(requests),
        "queue_status": request_status,
        "queue_url": f"/warehouse/blank-requests/queue-fragment?status_filter={request_status}",
    }


@warehouse_router.get("", response_class=HTMLResponse)
def warehouse_queue_page(
    request: Request,
    _actor: Annotated[User, Depends(require_permission("blank_requests", "deliver"))],
    db: Annotated[Session, Depends(get_db)],
    status_filter: str = "submitted",
    delivered: bool = False,
    quantity_mismatch: bool = False,
    lot_order_id: int | None = None,
    lot_from: int = 1,
    lot_count: int = 10,
) -> HTMLResponse:
    status_filter = status_filter if status_filter in {"submitted", "delivered"} else "submitted"
    token = csrf_token_for_request(request)
    selected_lots = (
        list(
            db.scalars(
                select(ProductionLot)
                .join(ProductionOrder, ProductionOrder.id == ProductionLot.order_id)
                .where(
                    ProductionLot.order_id == lot_order_id,
                    ProductionLot.lot_number >= max(lot_from, 1),
                    ProductionLot.deleted_at.is_(None),
                    ProductionOrder.deleted_at.is_(None),
                    ProductionOrder.status != "cancelled",
                    ProductionOrder.process_type != "BAVIA_ONLY",
                )
                .order_by(ProductionLot.lot_number)
                .limit(min(max(lot_count, 1), 100))
            )
        )
        if lot_order_id
        else []
    )
    from app.modules.qc.models import LotQcInspection

    qc_done_lot_ids = (
        set(
            db.scalars(
                select(LotQcInspection.production_lot_id).where(
                    LotQcInspection.production_lot_id.in_([lot.id for lot in selected_lots]),
                    LotQcInspection.deleted_at.is_(None),
                )
            )
        )
        if selected_lots
        else set()
    )
    response = templates.TemplateResponse(
        request=request,
        name="warehouse/queue.html",
        context={
            "title": "Yêu cầu phôi",
            "queue_status": status_filter,
            "csrf_token": token,
            "delivery_notice": delivered,
            "quantity_mismatch": quantity_mismatch,
            "lot_orders": list(
                db.execute(
                    select(ProductionOrder, Product)
                    .join(Product, Product.id == ProductionOrder.product_id)
                    .where(
                        ProductionOrder.deleted_at.is_(None),
                        ProductionOrder.status != "cancelled",
                        ProductionOrder.process_type != "BAVIA_ONLY",
                    )
                    .order_by(ProductionOrder.po_no)
                )
            ),
            "lot_order_id": lot_order_id,
            "lot_from": lot_from,
            "lot_count": lot_count,
            "lots_for_print": selected_lots,
            "qc_done_lot_ids": qc_done_lot_ids,
            **_queue_context(db, status_filter),
        },
    )
    set_csrf_cookie(response, token)
    return response


@warehouse_router.post("/qc-lots/print", response_class=HTMLResponse)
async def print_lot_forms(
    request: Request,
    actor: Annotated[User, Depends(require_permission("blank_requests", "deliver"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    from app.modules.auth.models import AuditLog

    form = await request.form()
    if not csrf_is_valid(request, str(form.get("csrf_token", ""))):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        order_id = int(str(form.get("lot_order_id", "")))
        lot_ids = list(dict.fromkeys(int(value) for value in form.getlist("lot_id")))
    except ValueError:
        return Response("Chọn PO và các lô cần in.", status_code=422)
    if not lot_ids or len(lot_ids) > 100:
        return Response("Chọn từ 1 đến 100 lô cho mỗi lần in.", status_code=422)
    rows = list(
        db.scalars(
            select(ProductionLot)
            .where(
                ProductionLot.id.in_(lot_ids),
                ProductionLot.order_id == order_id,
                ProductionLot.deleted_at.is_(None),
            )
            .order_by(ProductionLot.lot_number)
            .with_for_update()
        )
    )
    if {row.id for row in rows} != set(lot_ids):
        return Response("Có lô không còn thuộc PO đã chọn.", status_code=409)
    order_row = db.execute(
        select(ProductionOrder, Product)
        .join(Product, Product.id == ProductionOrder.product_id)
        .where(
            ProductionOrder.id == order_id,
            ProductionOrder.deleted_at.is_(None),
            ProductionOrder.status != "cancelled",
            ProductionOrder.process_type != "BAVIA_ONLY",
        )
    ).first()
    if order_row is None:
        return Response("Không tìm thấy PO.", status_code=404)
    order, product = order_row
    lot_total = (
        db.scalar(
            select(func.count(ProductionLot.id)).where(
                ProductionLot.order_id == order.id,
                ProductionLot.deleted_at.is_(None),
            )
        )
        or 0
    )
    now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    process_labels = {
        "FULL": "Đầy đủ (SX và Bavia)",
        "SX_ONLY": "Chỉ sản xuất",
        "BAVIA_ONLY": "Chỉ Bavia",
    }
    lot_pages = []
    for lot in rows:
        replacements = {
            "ma_san_pham": product.code,
            "ten_san_pham": product.name,
            "ma_ban_ve": order.drawing_number,
            "rev": order.revision,
            "qr_yeu_cau": "",
            "ma_yeu_cau": lot.lot_code,
            "ma_lo": lot.lot_code,
            "ma_nvl": order.raw_material_code,
            "chat_lieu": order.material,
            "ngay_nhan_dh": order.order_received_date.strftime("%d/%m/%Y"),
            "ma_don_hang": order.po_no,
            "kich_co_phoi": order.blank_size,
            "ngay_xuat_phoi": "",
            "nguoi_giao": "",
            "nguoi_nhan": "",
            "ngay_san_xuat": "",
            "kip": "",
            "ngay_in": now.strftime("%d/%m/%Y %H:%M"),
            "nguoi_lam": "",
            "so_bieu": f"{lot.lot_number} / {lot_total}",
            "so_luong_lo": str(lot.quantity),
            "cong_doan": process_labels[order.process_type],
        }
        lot_pages.append((replacements, lot.lot_code))

    try:
        pdf_content = render_lot_qc_batch_pdf(active_template(db), lot_pages)
        rendered_pages = pdf_pages_as_data_urls(pdf_content, max_pages=100)
        if len(rendered_pages) != len(rows):
            raise FormTemplateError("Số trang PDF không khớp số lô đã chọn.")
    except FormTemplateError as exc:
        db.rollback()
        return Response(str(exc), status_code=422)

    for lot in rows:
        old_printed_at = lot.printed_at.isoformat() if lot.printed_at else None
        lot.printed_at = now
        lot.updated_at = now
        lot.updated_by = actor.id
        db.add(
            AuditLog(
                table_name="production_lots",
                record_id=lot.id,
                action="print_form",
                old_values={"printed_at": old_printed_at},
                new_values={"printed_at": now.isoformat(), "lot_code": lot.lot_code},
                reason="Kho NVL gửi biểu QC theo lô đi in",
                actor_id=actor.id,
            )
        )
    db.commit()
    return templates.TemplateResponse(
        request=request,
        name="qc/lot_print_batch.html",
        context={
            "title": "Biểu QC theo lô",
            "pages": rendered_pages,
        },
    )


@warehouse_router.get("/queue-fragment", response_class=HTMLResponse)
def warehouse_queue_fragment(
    request: Request,
    _actor: Annotated[User, Depends(require_permission("blank_requests", "deliver"))],
    db: Annotated[Session, Depends(get_db)],
    status_filter: str = "submitted",
) -> HTMLResponse:
    status_filter = status_filter if status_filter in {"submitted", "delivered"} else "submitted"
    return templates.TemplateResponse(
        request=request,
        name="warehouse/queue_fragment.html",
        context={
            **_queue_context(db, status_filter),
            "csrf_token": csrf_token_for_request(request),
        },
    )


@warehouse_router.get("/{request_id}/delivery", response_class=HTMLResponse)
def blank_request_delivery_page(
    request: Request,
    request_id: int,
    _actor: Annotated[User, Depends(require_permission("blank_requests", "deliver"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    row = get_printable_request(db, request_id)
    if row is None:
        return Response("Không tìm thấy yêu cầu phôi.", status_code=404)
    if row[0].status != "submitted":
        return Response("Yêu cầu này không còn chờ xác nhận giao.", status_code=409)
    token = csrf_token_for_request(request)
    response = templates.TemplateResponse(
        request=request,
        name="warehouse/delivery.html",
        context={
            "title": "Xác nhận giao phôi",
            "blank_request": row[0],
            "schedule": row[1],
            "order": row[2],
            "product": row[3],
            "shift": row[4],
            "csrf_token": token,
        },
    )
    set_csrf_cookie(response, token)
    return response


@warehouse_router.post("/{request_id}/delivery", response_class=HTMLResponse)
def confirm_blank_request_delivery(
    request: Request,
    request_id: int,
    csrf_token: Annotated[str, Form()],
    version: Annotated[int, Form()],
    actor: Annotated[User, Depends(require_permission("blank_requests", "deliver"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        data = BlankRequestDelivery.model_validate({"version": version})
        confirm_delivery(db, request_id, data.actual_quantity, data.version, actor.id)
        db.commit()
    except ValidationError:
        db.rollback()
        return Response(
            "Phiên bản phiếu không hợp lệ. Tải lại hàng chờ rồi thử lại.", status_code=422
        )
    except BlankRequestManagementError as exc:
        db.rollback()
        return Response(str(exc), status_code=409)
    return RedirectResponse(
        "/warehouse/blank-requests?delivered=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _render_blank_request_forms(
    request: Request,
    row: tuple,
    form_type: Literal["production"],
    actor: User,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    try:
        pairs, operators, pair_workers = print_resource_details(db, row[0].id)
        sender_id = row[0].delivered_by or actor.id
        sender = db.get(User, sender_id)
        receiver = db.get(User, row[0].created_by) if row[0].created_by else None
        replacements = template_replacements(
            row,
            pairs,
            operators,
            sender_name=sender.display_name if sender else "",
            receiver_name=receiver.display_name if receiver else "",
            pair_workers=pair_workers,
        )
        workbook = active_template(db)
        pdf = render_template_pdf(workbook, form_type, replacements, row[0].req_no)
        pages = pdf_pages_as_data_urls(pdf)
    except FormTemplateError as exc:
        return Response(str(exc), status_code=422)
    response = templates.TemplateResponse(
        request=request,
        name="form_templates/preview.html",
        context={
            "title": "Biểu Bavia" if row[2].process_type == "BAVIA_ONLY" else "Biểu sản xuất",
            "request_number": row[0].req_no,
            "pages": pages,
            "auto_print": False,
        },
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _print_and_register(
    request: Request, request_id: int, form_type: Literal["production"], actor: User, db: Session
) -> Response:
    row = get_printable_request(db, request_id)
    if row is None or row[0].status == "cancelled":
        return Response("Không tìm thấy yêu cầu phôi có thể in.", status_code=409)
    response = _render_blank_request_forms(request, row, form_type, actor, db)
    if response.status_code != 200:
        db.rollback()
        return response
    try:
        register_print(db, request_id, form_type, actor.id)
        db.commit()
    except BlankRequestManagementError as exc:
        db.rollback()
        return Response(str(exc), status_code=409)
    return response


@warehouse_router.post("/{request_id}/print/initial", response_class=HTMLResponse)
def print_initial_blank_request_forms(
    request: Request,
    request_id: int,
    csrf_token: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_permission("blank_requests", "deliver"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    return _print_and_register(request, request_id, "production", actor, db)


@warehouse_router.post("/{request_id}/print/{form_type}", response_class=HTMLResponse)
def print_blank_request_form(
    request: Request,
    request_id: int,
    form_type: Literal["production"],
    csrf_token: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_permission("blank_requests", "deliver"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    return _print_and_register(request, request_id, form_type, actor, db)
