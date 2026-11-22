from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, csrf_token_for_request, set_csrf_cookie
from app.core.db import get_db
from app.core.permissions import has_permission, require_active_user, require_permission
from app.modules.assets.models import Machine
from app.modules.auth.models import User
from app.modules.defects.models import DefectCode
from app.modules.employees.models import Employee
from app.modules.orders.models import ProductionLot
from app.modules.qc.models import LotQcInspection
from app.modules.qc.schemas import LotQcInput
from app.modules.qc.service import (
    QcInspectionError,
    list_printed_lots_for_po,
    lot_qc_context,
    lot_qc_details,
    qc_search_suggestions,
    save_lot_qc,
)
from app.modules.shifts.models import Shift
from app.modules.users.models import UserPermission

router = APIRouter(prefix="/qc", tags=["qc"])
templates = Jinja2Templates(directory="app/templates")


def _can(db: Session, actor: User, action: str) -> bool:
    if actor.role == "admin":
        return True
    extras = frozenset(
        (permission.module, permission_action)
        for permission in db.scalars(
            select(UserPermission).where(
                UserPermission.user_id == actor.id,
                UserPermission.deleted_at.is_(None),
            )
        )
        for permission_action, allowed in (
            ("view", permission.can_view),
            ("create", permission.can_create),
            ("edit", permission.can_edit),
            ("delete", permission.can_delete),
        )
        if allowed
    )
    return has_permission(actor.role, "qc", action, extras)


def _render(
    request: Request,
    db: Session,
    *,
    actor: User,
    lot_code: str = "",
    po_query: str = "",
    error: str | None = None,
    saved: bool = False,
    submitted: dict[str, object] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    context = lot_qc_context(db, lot_code) if lot_code else None
    lot, order, product = context if context else (None, None, None)
    effective_po_query = po_query.strip() or (order.po_no if order else "")
    qc_lots = list_printed_lots_for_po(db, effective_po_query)
    inspection = (
        db.scalar(
            select(LotQcInspection).where(
                LotQcInspection.production_lot_id == lot.id,
                LotQcInspection.deleted_at.is_(None),
            )
        )
        if lot
        else None
    )
    details = lot_qc_details(db, inspection.id) if inspection else []
    old_employees = [
        item
        for item in db.scalars(select(Employee).where(Employee.deleted_at.is_(None)))
        if inspection and item.id == inspection.qc_employee_id
    ]
    employees = list(
        db.scalars(
            select(Employee)
            .where(
                Employee.employee_type == "qc",
                Employee.is_active.is_(True),
                Employee.deleted_at.is_(None),
            )
            .order_by(Employee.code)
        )
    )
    employees.extend(item for item in old_employees if item.id not in {row.id for row in employees})
    shifts = list(
        db.scalars(
            select(Shift)
            .where(Shift.is_active.is_(True), Shift.deleted_at.is_(None))
            .order_by(Shift.start_time)
        )
    )
    if inspection and inspection.shift_id not in {row.id for row in shifts}:
        old_shift = db.get(Shift, inspection.shift_id)
        if old_shift and old_shift.deleted_at is None:
            shifts.append(old_shift)
    defects = list(
        db.scalars(
            select(DefectCode)
            .where(
                DefectCode.detected_at == "SX",
                DefectCode.is_active.is_(True),
                DefectCode.deleted_at.is_(None),
            )
            .order_by(DefectCode.code)
        )
    )
    machines = list(
        db.scalars(
            select(Machine)
            .where(Machine.is_active.is_(True), Machine.deleted_at.is_(None))
            .order_by(Machine.code)
        )
    )
    detail_rows = submitted.get("defects") if submitted else None
    if detail_rows is None:
        detail_rows = [
            {
                "defect_code_id": row["line"].defect_code_id,
                "machine_id": row["line"].machine_id,
                "disposition": row["line"].disposition,
                "quantity": row["line"].quantity,
            }
            for row in details
        ]
    token = csrf_token_for_request(request)
    response = templates.TemplateResponse(
        request=request,
        name="qc/lots.html",
        context={
            "title": "QC theo lô",
            "csrf_token": token,
            "actor": actor,
            "lot_code": lot_code,
            "po_query": effective_po_query,
            "qc_lots": qc_lots,
            "lot": lot,
            "order": order,
            "product": product,
            "inspection": inspection,
            "defect_details": details,
            "detail_rows": detail_rows,
            "employees": employees,
            "shifts": shifts,
            "defects": defects,
            "machines": machines,
            "error": error,
            "saved": saved,
            "submitted": submitted or {},
            "can_create": _can(db, actor, "create"),
            "can_edit": _can(db, actor, "edit"),
            "today": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat(),
        },
        status_code=status_code,
    )
    set_csrf_cookie(response, token)
    return response


@router.get("", response_class=HTMLResponse)
def qc_lots_page(
    request: Request,
    actor: Annotated[User, Depends(require_permission("qc", "view"))],
    db: Annotated[Session, Depends(get_db)],
    lot_code: str = "",
    po_query: str = "",
    saved: bool = False,
) -> HTMLResponse:
    lot_code = lot_code.strip().upper()
    po_query = po_query.strip()
    response = _render(request, db, actor=actor, lot_code=lot_code, po_query=po_query, saved=saved)
    if lot_code and lot_qc_context(db, lot_code) is None:
        return _render(
            request,
            db,
            actor=actor,
            lot_code=lot_code,
            po_query=po_query,
            error="Không tìm thấy mã lô. Kiểm tra lại mã hoặc quét QR lần nữa.",
            status_code=404,
        )
    return response


@router.get("/suggestions", response_class=JSONResponse)
def qc_search_suggestions_page(
    actor: Annotated[User, Depends(require_permission("qc", "view"))],
    db: Annotated[Session, Depends(get_db)],
    field: str = "po",
    q: str = "",
) -> JSONResponse:
    del actor
    if field not in {"po", "lot"}:
        return JSONResponse({"suggestions": []})
    return JSONResponse({"suggestions": qc_search_suggestions(db, field, q)})


@router.post("", response_class=HTMLResponse)
async def save_lot_qc_submit(
    request: Request,
    actor: Annotated[User, Depends(require_active_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    form = await request.form()
    lot_code = str(form.get("lot_code", "")).strip().upper()
    csrf_token = str(form.get("csrf_token", ""))
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    exists = bool(lot_code and lot_qc_context(db, lot_code))
    action = (
        "edit"
        if exists
        and db.scalar(
            select(LotQcInspection.id)
            .join(ProductionLot, ProductionLot.id == LotQcInspection.production_lot_id)
            .where(ProductionLot.lot_code == lot_code, LotQcInspection.deleted_at.is_(None))
        )
        else "create"
    )
    if not _can(db, actor, action):
        return Response("Bạn không có quyền lưu kết quả QC.", status_code=403)

    submitted = {
        key: str(form.get(key, ""))
        for key in (
            "inspected_date",
            "shift_id",
            "qc_employee_id",
            "version",
            "quantity_ok",
            "quantity_ng",
        )
    }
    defect_ids = form.getlist("defect_code_id")
    machine_ids = form.getlist("machine_id")
    dispositions = form.getlist("disposition")
    quantities = form.getlist("defect_quantity")
    if not (len(defect_ids) == len(machine_ids) == len(dispositions) == len(quantities)):
        return _render(
            request,
            db,
            actor=actor,
            lot_code=lot_code,
            error="Chi tiết lỗi không hợp lệ. Kiểm tra từng dòng rồi thử lại.",
            submitted=submitted,
            status_code=422,
        )
    defect_rows = [
        {
            "defect_code_id": defect_id,
            "machine_id": machine_id,
            "disposition": disposition,
            "quantity": quantity,
        }
        for defect_id, machine_id, disposition, quantity in zip(
            defect_ids, machine_ids, dispositions, quantities, strict=True
        )
        if any((defect_id, machine_id, disposition, quantity))
    ]
    scrap_total = sum(
        int(row["quantity"])
        for row in defect_rows
        if row["disposition"] == "scrap" and str(row["quantity"]).isdigit()
    )
    repair_total = sum(
        int(row["quantity"])
        for row in defect_rows
        if row["disposition"] == "repair" and str(row["quantity"]).isdigit()
    )
    submitted["ng_scrap"] = str(scrap_total)
    submitted["ng_repair"] = str(repair_total)
    submitted["defects"] = defect_rows
    try:
        data = LotQcInput.model_validate(
            {
                **submitted,
                "defects": defect_rows,
            }
        )
    except ValidationError as exc:
        messages = "; ".join(item["msg"] for item in exc.errors())
        return _render(
            request,
            db,
            actor=actor,
            lot_code=lot_code,
            error=messages,
            submitted=submitted,
            status_code=422,
        )
    try:
        save_lot_qc(db, lot_code, data, actor.id)
        db.commit()
    except QcInspectionError as exc:
        db.rollback()
        return _render(
            request,
            db,
            actor=actor,
            lot_code=lot_code,
            error=str(exc),
            submitted=submitted,
            status_code=409,
        )
    except IntegrityError:
        db.rollback()
        return _render(
            request,
            db,
            actor=actor,
            lot_code=lot_code,
            error="Dữ liệu vừa thay đổi. Tải lại lô rồi thử lại.",
            submitted=submitted,
            status_code=409,
        )
    return RedirectResponse(f"/qc?{urlencode({'lot_code': lot_code, 'saved': 1})}", status_code=303)
