from datetime import date, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, csrf_token_for_request, set_csrf_cookie
from app.core.db import get_db
from app.core.permissions import has_permission, require_active_user, require_permission
from app.modules.auth.models import User
from app.modules.blank_requests.service import active_operators
from app.modules.daily_reports.bavia_schemas import BaviaReportInput
from app.modules.daily_reports.bavia_service import (
    BaviaReportError,
    list_bavia_reports,
    save_bavia_report,
)
from app.modules.daily_reports.models import BaviaReport, DailyReport
from app.modules.daily_reports.schemas import DailyProductionReportCreate
from app.modules.daily_reports.service import (
    DailyReportError,
    DuplicateDailyReport,
    active_downtime_reasons,
    active_shifts,
    create_daily_production_report,
    daily_report_po_suggestions,
    get_daily_report_edit_data,
    get_request_context,
    list_daily_report_requests,
    list_daily_reports,
    report_pairs_for_request,
    report_shift_names,
    update_daily_production_report,
)
from app.modules.shifts.models import Shift
from app.modules.users.models import UserPermission

router = APIRouter(prefix="/daily-reports", tags=["daily-reports"])
templates = Jinja2Templates(directory="app/templates")


def _extra_permissions(db: Session, actor: User) -> frozenset[tuple[str, str]]:
    return frozenset(
        (permission.module, action)
        for permission in db.scalars(
            select(UserPermission).where(
                UserPermission.user_id == actor.id,
                UserPermission.deleted_at.is_(None),
            )
        )
        for action, allowed in (
            ("view", permission.can_view),
            ("create", permission.can_create),
            ("edit", permission.can_edit),
            ("delete", permission.can_delete),
        )
        if allowed
    )


def _render(
    request: Request,
    db: Session,
    actor: User,
    *,
    request_number: str = "",
    errors: list[str] | None = None,
    error: str | None = None,
    success: str | None = None,
    warnings: list[str] | None = None,
    editing_report_id: int | None = None,
    production_date_filter: date | None = None,
    shift_filter_id: int | None = None,
    po_query: str = "",
    mode: str = "production",
    bavia_report_id: int | None = None,
    bavia_form_values: dict[str, str] | None = None,
    production_form_payload: str = "",
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    token = csrf_token_for_request(request)
    extra_permissions = _extra_permissions(db, actor)
    can_create = has_permission(actor.role, "daily_reports", "create", extra_permissions)
    can_edit = has_permission(actor.role, "daily_reports", "edit", extra_permissions)
    can_view = has_permission(actor.role, "daily_reports", "view", extra_permissions)
    row = get_request_context(db, request_number) if request_number else None
    if row:
        if row[2].process_type == "BAVIA_ONLY":
            mode = "bavia"
        elif row[2].process_type == "SX_ONLY":
            mode = "production"
        elif mode not in {"production", "bavia"}:
            mode = "production"
    if row:
        production_date_filter = production_date_filter or row[1].production_date
        shift_filter_id = shift_filter_id or row[4].id
        po_query = po_query or row[2].po_no
    production_date_filter = (
        production_date_filter or datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    )
    report_requests = (
        list_daily_report_requests(
            db,
            production_date_filter,
            shift_id=shift_filter_id,
            po_query=po_query,
        )
        if can_view
        else []
    )
    existing_report_id = None
    if row:
        existing_report_id = db.scalar(
            select(DailyReport.id).where(
                DailyReport.blank_request_id == row[0].id,
                DailyReport.deleted_at.is_(None),
            )
        )
        if existing_report_id and can_edit and editing_report_id is None:
            editing_report_id = existing_report_id
    assignments = []
    workers = active_operators(db)
    editing_report = None
    edit_values = {}
    edit_shift_id = None
    if editing_report_id:
        edit_data = get_daily_report_edit_data(db, editing_report_id)
        if edit_data:
            editing_report, assignments, edit_values = edit_data
            edit_shift_id = next(
                (value["report_pair"].shift_id for value in edit_values.values()), None
            )
            existing_worker_ids = {worker.id for worker in workers}
            workers.extend(
                worker for _pair, worker in assignments if worker.id not in existing_worker_ids
            )
    elif existing_report_id and can_view:
        edit_data = get_daily_report_edit_data(db, existing_report_id)
        if edit_data:
            editing_report, assignments, edit_values = edit_data
            edit_shift_id = next(
                (value["report_pair"].shift_id for value in edit_values.values()), None
            )
            existing_worker_ids = {worker.id for worker in workers}
            workers.extend(
                worker for _pair, worker in assignments if worker.id not in existing_worker_ids
            )
    if row and not editing_report:
        assignments, workers = report_pairs_for_request(db, row[0].id)
    report_date = None
    if row:
        schedule = row[1]
        report_date = editing_report.report_date if editing_report else schedule.production_date
    shifts = active_shifts(db)
    if editing_report and edit_shift_id not in {shift.id for shift in shifts}:
        saved_shift = db.get(Shift, edit_shift_id)
        if saved_shift and saved_shift.deleted_at is None:
            shifts.append(saved_shift)
    shift_minutes = {
        shift_option.id: _shift_minutes(shift_option, report_date) for shift_option in shifts
    }
    bavia_reports = []
    bavia_form = bavia_form_values or {}
    if row and row[2].process_type in {"FULL", "BAVIA_ONLY"}:
        bavia_reports = [
            report
            for report in list_bavia_reports(
                db,
                order_id=row[2].id,
            )
        ]
        if bavia_report_id:
            selected_bavia = next(
                (item for item in bavia_reports if item["id"] == bavia_report_id), None
            )
            if selected_bavia:
                bavia_form = {
                    "report_id": str(selected_bavia["id"]),
                    "report_date": selected_bavia["report_date"],
                    "shift_id": str(selected_bavia["shift_id"]),
                    "employee_id": str(selected_bavia["employee_id"]),
                    "quantity_produced": str(selected_bavia["quantity_produced"]),
                    "version": str(selected_bavia["version"]),
                }
        if not bavia_form:
            bavia_form = {
                "report_id": "",
                "report_date": row[1].production_date.isoformat(),
                "shift_id": str(row[4].id),
                "employee_id": "",
                "quantity_produced": "",
                "version": "0",
            }
    bavia_status_keys = set(
        db.execute(
            select(BaviaReport.order_id, BaviaReport.report_date, BaviaReport.shift_id)
            .where(BaviaReport.deleted_at.is_(None))
            .distinct()
        ).all()
    )
    bavia_request_ids = (
        {
            item[0].id
            for item in report_requests
            if (item[2].id, item[1].production_date, item[4].id) in bavia_status_keys
        }
        if can_view
        else set()
    )

    response = templates.TemplateResponse(
        request=request,
        name="daily_reports/production.html",
        context={
            "title": "Nhập báo cáo sản lượng",
            "reports": list_daily_reports(db),
            "report_requests": report_requests,
            "request_row": row,
            "request_number": request_number,
            "mode": mode,
            "bavia_reports": bavia_reports,
            "bavia_form": bavia_form,
            "production_form_payload": production_form_payload,
            "bavia_report_id": bavia_report_id,
            "bavia_request_ids": bavia_request_ids,
            "assignments": assignments,
            "workers": workers,
            "downtime_reasons": active_downtime_reasons(db),
            "shift_options": shifts,
            "shift_minutes": shift_minutes,
            "report_shift_names": report_shift_names(db),
            "report_date": report_date,
            "errors": errors or [],
            "error": error,
            "success": success,
            "warnings": warnings or [],
            "csrf_token": token,
            "can_create": can_create,
            "can_edit": can_edit,
            "can_save_bavia": can_create or (bavia_report_id is not None and can_edit),
            "can_view": can_view,
            "report_read_only": bool(editing_report and not can_edit),
            "existing_report_id": existing_report_id,
            "editing_report": editing_report,
            "edit_values": edit_values,
            "edit_shift_id": edit_shift_id,
            "production_date_filter": production_date_filter,
            "shift_filter_id": shift_filter_id,
            "po_query": po_query,
        },
        status_code=status_code,
    )
    set_csrf_cookie(response, token)
    return response


def _shift_minutes(shift, report_date) -> int:
    if report_date is None:
        return 1
    start = datetime.combine(report_date, shift.start_time)
    end = datetime.combine(report_date, shift.end_time)
    if shift.crosses_midnight:
        end += timedelta(days=1)
    return max(int((end - start).total_seconds() // 60) - shift.planned_break_minutes, 1)


@router.get("", response_class=HTMLResponse)
def daily_reports_page(
    request: Request,
    actor: Annotated[User, Depends(require_permission("daily_reports", "view"))],
    db: Annotated[Session, Depends(get_db)],
    request_number: str = "",
    production_date: date | None = None,
    shift_id: str = "",
    po_query: str = "",
    mode: str = "production",
    bavia_id: int | None = None,
    updated: bool = False,
    created: bool = False,
    bavia_saved: bool = False,
) -> HTMLResponse:
    return _render(
        request,
        db,
        actor,
        request_number=request_number.strip(),
        production_date_filter=production_date,
        shift_filter_id=int(shift_id) if shift_id.isdigit() else None,
        po_query=po_query.strip(),
        mode=mode,
        bavia_report_id=bavia_id,
        success=(
            "Đã lưu sản lượng Bavia."
            if bavia_saved
            else "Đã lưu thay đổi báo cáo."
            if updated
            else "Đã lưu báo cáo sản lượng."
            if created
            else None
        ),
    )


@router.get("/suggestions", response_class=JSONResponse)
def daily_report_search_suggestions(
    actor: Annotated[User, Depends(require_permission("daily_reports", "view"))],
    db: Annotated[Session, Depends(get_db)],
    field: str = "po",
    q: str = "",
) -> JSONResponse:
    del actor
    if field != "po":
        return JSONResponse({"suggestions": []})
    return JSONResponse({"suggestions": daily_report_po_suggestions(db, q)})


@router.get("/new", response_class=HTMLResponse)
def new_daily_report_page(
    request: Request,
    actor: Annotated[User, Depends(require_permission("daily_reports", "create"))],
    db: Annotated[Session, Depends(get_db)],
    request_number: str = "",
    production_date: date | None = None,
    shift_id: str = "",
    po_query: str = "",
    mode: str = "production",
) -> HTMLResponse:
    return _render(
        request,
        db,
        actor,
        request_number=request_number.strip(),
        production_date_filter=production_date,
        shift_filter_id=int(shift_id) if shift_id.isdigit() else None,
        po_query=po_query.strip(),
        mode=mode,
    )


@router.post("", response_class=HTMLResponse)
async def create_daily_report_submit(
    request: Request,
    actor: Annotated[User, Depends(require_permission("daily_reports", "create"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    form = await request.form()
    csrf_token = str(form.get("csrf_token", ""))
    request_number = str(form.get("request_number", "")).strip()
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    payload = str(form.get("report_payload", ""))
    try:
        data = DailyProductionReportCreate.model_validate_json(payload)
    except ValidationError as exc:
        errors = [item["msg"] for item in exc.errors()]
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            errors=errors,
            production_form_payload=payload,
            status_code=422,
        )
    try:
        _report, warnings = create_daily_production_report(db, data, actor.id)
        db.commit()
    except DuplicateDailyReport as exc:
        db.rollback()
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            error=str(exc),
            production_form_payload=payload,
            status_code=409,
        )
    except DailyReportError as exc:
        db.rollback()
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            error=str(exc),
            production_form_payload=payload,
            status_code=422,
        )
    except IntegrityError:
        db.rollback()
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            error="Báo cáo vừa được người khác tạo. Tải lại trang để xem dữ liệu mới.",
            production_form_payload=payload,
            status_code=409,
        )
    if warnings:
        return _render(request, db, actor, request_number=request_number, warnings=warnings)
    return RedirectResponse(
        f"/daily-reports?{urlencode({'request_number': request_number, 'created': 1})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/bavia", response_class=HTMLResponse)
async def create_bavia_report_submit(
    request: Request,
    actor: Annotated[User, Depends(require_active_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    form = await request.form()
    csrf_token = str(form.get("csrf_token", ""))
    request_number = str(form.get("request_number", "")).strip()
    values = {
        key: str(form.get(key, "")).strip()
        for key in (
            "report_id",
            "report_date",
            "shift_id",
            "employee_id",
            "quantity_produced",
            "version",
        )
    }
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    if not any(
        has_permission(actor.role, "daily_reports", action, _extra_permissions(db, actor))
        for action in ("create", "edit")
    ):
        return Response("Bạn không có quyền lưu báo cáo Bavia.", status_code=403)
    if values["report_id"] and not values["report_id"].isdigit():
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            mode="bavia",
            bavia_form_values=values,
            error="Mã báo cáo Bavia không hợp lệ. Tải lại trang rồi thử lại.",
            status_code=422,
        )
    report_id = int(values["report_id"]) if values["report_id"] else None
    permission = "edit" if report_id is not None else "create"
    if not has_permission(actor.role, "daily_reports", permission, _extra_permissions(db, actor)):
        return Response("Bạn không có quyền lưu báo cáo Bavia.", status_code=403)
    row = get_request_context(db, request_number) if request_number else None
    if row is None:
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            mode="bavia",
            error="Không tìm thấy mã yêu cầu phôi đang sử dụng.",
            status_code=404,
        )
    if row[0].status != "delivered":
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            mode="bavia",
            bavia_form_values=values,
            error="Chờ Kho NVL xác nhận giao phôi rồi mới nhập sản lượng Bavia.",
            status_code=409,
        )
    if row[2].process_type not in {"FULL", "BAVIA_ONLY"}:
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            mode="bavia",
            bavia_form_values=values,
            error="PO chỉ sản xuất không có công đoạn Bavia.",
            status_code=422,
        )
    try:
        data = BaviaReportInput.model_validate(
            {
                "order_id": row[2].id,
                "report_date": values["report_date"],
                "shift_id": values["shift_id"],
                "employee_id": values["employee_id"],
                "quantity_produced": values["quantity_produced"],
                "version": values["version"] or "0",
            }
        )
        existing_id = report_id or db.scalar(
            select(BaviaReport.id).where(
                BaviaReport.order_id == data.order_id,
                BaviaReport.report_date == data.report_date,
                BaviaReport.shift_id == data.shift_id,
                BaviaReport.employee_id == data.employee_id,
                BaviaReport.deleted_at.is_(None),
            )
        )
        if existing_id and not has_permission(
            actor.role, "daily_reports", "edit", _extra_permissions(db, actor)
        ):
            return Response("Bạn không có quyền sửa báo cáo Bavia.", status_code=403)
        save_bavia_report(db, data, actor.id, report_id=report_id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            mode="bavia",
            bavia_form_values=values,
            errors=[item["msg"] for item in exc.errors()],
            status_code=422,
        )
    except BaviaReportError as exc:
        db.rollback()
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            mode="bavia",
            bavia_form_values=values,
            error=str(exc),
            status_code=409,
        )
    except IntegrityError:
        db.rollback()
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            mode="bavia",
            bavia_form_values=values,
            error="Báo cáo Bavia vừa được cập nhật. Tải lại trang rồi thử lại.",
            status_code=409,
        )
    saved_query = urlencode({"request_number": request_number, "mode": "bavia", "bavia_saved": 1})
    return RedirectResponse(
        f"/daily-reports?{saved_query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{report_id}", response_class=HTMLResponse)
async def update_daily_report_submit(
    report_id: int,
    request: Request,
    actor: Annotated[User, Depends(require_permission("daily_reports", "edit"))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    form = await request.form()
    csrf_token = str(form.get("csrf_token", ""))
    request_number = str(form.get("request_number", "")).strip()
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    payload = str(form.get("report_payload", ""))
    try:
        data = DailyProductionReportCreate.model_validate_json(payload)
        expected_version = int(str(form.get("version", "")))
    except (ValidationError, ValueError) as exc:
        errors = (
            [item["msg"] for item in exc.errors()]
            if isinstance(exc, ValidationError)
            else ["Phiên bản báo cáo không hợp lệ. Tải lại trang trước khi sửa."]
        )
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            editing_report_id=report_id,
            errors=errors,
            production_form_payload=payload,
            status_code=422,
        )
    try:
        _report, warnings = update_daily_production_report(
            db, report_id, data, expected_version, actor.id
        )
        db.commit()
    except DailyReportError as exc:
        db.rollback()
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            editing_report_id=report_id,
            error=str(exc),
            production_form_payload=payload,
            status_code=409,
        )
    except IntegrityError:
        db.rollback()
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            editing_report_id=report_id,
            error="Không lưu được thay đổi do dữ liệu vừa được cập nhật. Tải lại rồi thử lại.",
            production_form_payload=payload,
            status_code=409,
        )
    if warnings:
        return _render(
            request,
            db,
            actor,
            request_number=request_number,
            editing_report_id=report_id,
            warnings=warnings,
        )
    return RedirectResponse(
        f"/daily-reports?{urlencode({'request_number': request_number, 'updated': 1})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
