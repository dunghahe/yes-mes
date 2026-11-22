from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, csrf_token_for_request, set_csrf_cookie
from app.core.db import get_db
from app.core.permissions import has_permission, require_permission
from app.core.validation import read_json, validation_details
from app.modules.auth.models import User
from app.modules.employees.models import Employee
from app.modules.orders.models import ProductionLot, ProductionOrder
from app.modules.repairs.schemas import RepairJobCreate, RepairRecheckCreate
from app.modules.repairs.service import (
    RepairWorkflowError,
    create_repair_job,
    create_repair_recheck,
    list_repair_queue,
    lot_repair_balances,
    repair_job_recheck_balances,
)
from app.modules.reporting.service import repair_history_rows
from app.modules.shifts.models import Shift
from app.modules.users.models import UserPermission

router = APIRouter(prefix="/repairs", tags=["repairs"])
templates = Jinja2Templates(directory="app/templates")


def _require_csrf(request: Request) -> None:
    if not csrf_is_valid(request, request.headers.get("x-csrf-token", "")):
        raise HTTPException(status_code=403, detail="Phiên biểu mẫu không hợp lệ.")


def _render_repair_page(
    request: Request,
    db: Session,
    actor: User,
    *,
    error: str | None = None,
    success: str | None = None,
    repair_code: str | None = None,
    form_values: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    token = csrf_token_for_request(request)
    permissions = list(
        db.scalars(
            select(UserPermission).where(
                UserPermission.user_id == actor.id,
                UserPermission.deleted_at.is_(None),
            )
        )
    )
    extras = frozenset(
        (permission.module, action)
        for permission in permissions
        for action, allowed in (
            ("view", permission.can_view),
            ("create", permission.can_create),
            ("edit", permission.can_edit),
            ("delete", permission.can_delete),
        )
        if allowed
    )
    orders = [
        order
        for order in db.scalars(
            select(ProductionOrder)
            .where(
                ProductionOrder.deleted_at.is_(None),
                ProductionOrder.process_type != "BAVIA_ONLY",
                ProductionOrder.status != "cancelled",
            )
            .order_by(ProductionOrder.po_no)
        )
    ]
    queue = [row for row in list_repair_queue(db) if row["stage"] == "QC"]
    queue_by_order = {row["order_id"]: row for row in queue}
    lot_balances = lot_repair_balances(db)
    lot_codes = {
        lot.id: lot.lot_code
        for lot in db.scalars(select(ProductionLot).where(ProductionLot.deleted_at.is_(None)))
    }
    repair_jobs_waiting_qc = [
        row for row in repair_job_recheck_balances(db, stage="QC") if row["quantity_waiting_qc"]
    ]
    history = [row for row in repair_history_rows(db) if row["stage"] == "QC"]
    employees = list(
        db.scalars(
            select(Employee)
            .where(
                Employee.is_active.is_(True),
                Employee.deleted_at.is_(None),
            )
            .order_by(Employee.code)
        )
    )
    qc_employees = list(
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
    shifts = list(
        db.scalars(
            select(Shift)
            .where(Shift.is_active.is_(True), Shift.deleted_at.is_(None))
            .order_by(Shift.start_time)
        )
    )
    response = templates.TemplateResponse(
        request=request,
        name="repairs/index.html",
        context={
            "title": "Theo dõi hàng mang đi sửa",
            "csrf_token": token,
            "error": error,
            "success": success,
            "repair_code": repair_code,
            "form_values": form_values or {},
            "can_create": has_permission(actor.role, "repairs", "create", extras),
            "orders": orders,
            "queue": queue,
            "queue_by_order": queue_by_order,
            "lot_balances": lot_balances,
            "lot_codes": lot_codes,
            "repair_jobs_waiting_qc": repair_jobs_waiting_qc,
            "history": history,
            "repair_employees": employees,
            "qc_employees": qc_employees,
            "shifts": shifts,
            "today": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat(),
        },
        status_code=status_code,
    )
    set_csrf_cookie(response, token)
    return response


@router.get("", response_class=HTMLResponse)
def repair_page(
    request: Request,
    actor: Annotated[User, Depends(require_permission("repairs", "view"))],
    db: Annotated[Session, Depends(get_db)],
    saved: str | None = None,
    repair_code: str | None = None,
) -> HTMLResponse:
    success = {
        "job": (
            f"Đã tạo phiếu sửa {repair_code}. "
            "Hãy ghi mã này lên phiếu giao hàng để QC tra khi nhận lại."
            if repair_code
            else "Đã ghi nhận lượt mang hàng đi sửa."
        ),
        "recheck": "Đã ghi nhận kết quả QC lại.",
    }.get(saved or "")
    return _render_repair_page(request, db, actor, success=success)


@router.post("/jobs/form", response_class=HTMLResponse)
async def repair_job_form_submit(
    request: Request,
    actor: Annotated[User, Depends(require_permission("repairs", "create"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    form = await request.form()
    if not csrf_is_valid(request, str(form.get("csrf_token", ""))):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        form_values = {
            key: str(form.get(key, ""))
            for key in (
                "production_lot_id",
                "repair_date",
                "repair_employee_id",
                "quantity_repaired",
                "note",
            )
        }
        lot_id_raw = str(form.get("production_lot_id", ""))
        if not lot_id_raw.isdigit():
            raise RepairWorkflowError("Chọn lô đang có hàng chờ sửa.")
        lot_id = int(lot_id_raw)
        lot = db.scalar(
            select(ProductionLot).where(
                ProductionLot.id == lot_id,
                ProductionLot.deleted_at.is_(None),
            )
        )
        if lot is None:
            raise RepairWorkflowError("Chọn lô đang có hàng chờ sửa.")
        data = RepairJobCreate.model_validate(
            {
                "order_id": lot.order_id,
                "production_lot_id": lot.id,
                "stage": "QC",
                "repair_employee_id": form.get("repair_employee_id"),
                "repair_date": form.get("repair_date"),
                "quantity_repaired": form.get("quantity_repaired"),
                "note": form.get("note") or None,
            }
        )
        repair_job = create_repair_job(db, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        message = "; ".join(item["msg"] for item in exc.errors())
        return _render_repair_page(
            request, db, actor, error=message, form_values=form_values, status_code=422
        )
    except RepairWorkflowError as exc:
        db.rollback()
        return _render_repair_page(
            request, db, actor, error=str(exc), form_values=form_values, status_code=409
        )
    except IntegrityError:
        db.rollback()
        return _render_repair_page(
            request,
            db,
            actor,
            error="Dữ liệu hàng chờ vừa thay đổi; hãy tải lại trang rồi thử lại.",
            form_values=form_values,
            status_code=409,
        )
    return RedirectResponse(
        f"/repairs?{urlencode({'saved': 'job', 'repair_code': repair_job.repair_code})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/rechecks/form", response_class=HTMLResponse)
async def repair_recheck_form_submit(
    request: Request,
    actor: Annotated[User, Depends(require_permission("repairs", "create"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    form = await request.form()
    if not csrf_is_valid(request, str(form.get("csrf_token", ""))):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    try:
        form_values = {
            key: str(form.get(key, ""))
            for key in (
                "repair_code",
                "inspected_date",
                "shift_id",
                "qc_employee_id",
                "quantity_in",
                "quantity_ok",
                "ng_scrap",
                "ng_repair",
            )
        }
        data = RepairRecheckCreate.model_validate(
            {
                "repair_code": form.get("repair_code"),
                "inspected_date": form.get("inspected_date"),
                "shift_id": form.get("shift_id"),
                "qc_employee_id": form.get("qc_employee_id"),
                "quantity_in": form.get("quantity_in"),
                "quantity_ok": form.get("quantity_ok"),
                "ng_scrap": form.get("ng_scrap"),
                "ng_repair": form.get("ng_repair"),
            }
        )
        create_repair_recheck(db, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        message = "; ".join(item["msg"] for item in exc.errors())
        return _render_repair_page(
            request, db, actor, error=message, form_values=form_values, status_code=422
        )
    except RepairWorkflowError as exc:
        db.rollback()
        return _render_repair_page(
            request, db, actor, error=str(exc), form_values=form_values, status_code=409
        )
    except IntegrityError:
        db.rollback()
        return _render_repair_page(
            request,
            db,
            actor,
            error="Dữ liệu hàng chờ vừa thay đổi; hãy tải lại trang rồi thử lại.",
            form_values=form_values,
            status_code=409,
        )
    return RedirectResponse(
        f"/repairs?{urlencode({'saved': 'recheck'})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/queue")
def repair_queue(
    _actor: Annotated[User, Depends(require_permission("repairs", "view"))],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, object]]:
    return list_repair_queue(db)


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
async def repair_job_submit(
    request: Request,
    actor: Annotated[User, Depends(require_permission("repairs", "create"))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _require_csrf(request)
    from pydantic import ValidationError

    try:
        data = RepairJobCreate.model_validate(await read_json(request))
        row = create_repair_job(db, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=validation_details(exc)) from exc
    except RepairWorkflowError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Dữ liệu vừa thay đổi; hãy tải lại hàng chờ sửa."
        ) from exc
    return {
        "id": row.id,
        "repair_code": row.repair_code,
        "order_id": row.order_id,
        "production_lot_id": row.production_lot_id,
        "stage": row.stage,
        "quantity_repaired": row.quantity_repaired,
    }


@router.post("/rechecks", status_code=status.HTTP_201_CREATED)
async def repair_recheck_submit(
    request: Request,
    actor: Annotated[User, Depends(require_permission("repairs", "create"))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _require_csrf(request)
    from pydantic import ValidationError

    try:
        data = RepairRecheckCreate.model_validate(await read_json(request))
        row = create_repair_recheck(db, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=validation_details(exc)) from exc
    except RepairWorkflowError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Dữ liệu vừa thay đổi; hãy tải lại hàng chờ sửa."
        ) from exc
    return {
        "id": row.id,
        "repair_code": data.repair_code,
        "order_id": row.order_id,
        "stage": row.stage,
        "quantity_in": row.quantity_in,
    }
