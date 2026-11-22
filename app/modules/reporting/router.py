from datetime import date, datetime
from io import BytesIO
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.csrf import csrf_token_for_request, set_csrf_cookie
from app.core.db import get_db
from app.core.permissions import require_permission
from app.modules.assets.models import Machine, MachinePair
from app.modules.auth.models import AuditLog, User
from app.modules.employees.models import Employee
from app.modules.orders.models import ProductionOrder
from app.modules.reporting.service import (
    aggregate_oee,
    list_audit_log,
    oee_rows,
    po_summaries,
    production_rows,
    quality_ng_rows,
    repair_history_rows,
)

router = APIRouter(prefix="/reports", tags=["reports"])
audit_router = APIRouter(prefix="/audit-log", tags=["audit"])
templates = Jinja2Templates(directory="app/templates")

PROCESS_LABELS = {
    "FULL": "Sản xuất + Bavia",
    "SX_ONLY": "Sản xuất",
    "BAVIA_ONLY": "Bavia",
}
LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
REPORT_TABS = ("po-summary", "production", "ng", "repairs", "oee")


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def report_dashboard(
    request: Request,
    _actor: Annotated[User, Depends(require_permission("reports", "view"))],
    db: Annotated[Session, Depends(get_db)],
    tab: str = Query(default="po-summary", pattern="^(po-summary|production|ng|repairs|oee)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    order_id: int | None = Query(default=None, gt=0),
    machine_pair_id: int | None = Query(default=None, gt=0),
    employee_id: int | None = Query(default=None, gt=0),
    kind: str | None = Query(default=None, pattern="^(scrap|repair)$"),
    group_by: str = Query(default="day", pattern="^(day|month|order|product|pair|shift)$"),
    preset: str | None = Query(default=None, pattern="^(today|month|year)$"),
) -> HTMLResponse:
    today = datetime.now(LOCAL_TZ).date()
    if preset == "today":
        date_from = date_to = today
    elif preset == "month":
        date_from, date_to = today.replace(day=1), today
    elif preset == "year":
        date_from, date_to = today.replace(month=1, day=1), today

    report_rows: list[dict[str, object]]
    if tab == "po-summary":
        report_rows = po_summaries(db)
    elif tab == "production":
        report_rows = production_rows(
            db,
            date_from=date_from,
            date_to=date_to,
            order_id=order_id,
            machine_pair_id=machine_pair_id,
            employee_id=employee_id,
        )
    elif tab == "ng":
        report_rows = quality_ng_rows(
            db,
            date_from=date_from,
            date_to=date_to,
            order_id=order_id,
            machine_pair_id=machine_pair_id,
            employee_id=employee_id,
            ng_kind=kind,
        )
    elif tab == "repairs":
        report_rows = repair_history_rows(
            db,
            order_id=order_id,
            date_from=date_from,
            date_to=date_to,
        )
    else:
        raw_oee_rows = oee_rows(
            db,
            date_from=date_from,
            date_to=date_to,
            order_id=order_id,
            machine_pair_id=machine_pair_id,
            employee_id=employee_id,
        )
        report_rows = aggregate_oee(raw_oee_rows, group_by)

    orders = list(
        db.scalars(
            select(ProductionOrder)
            .where(ProductionOrder.deleted_at.is_(None))
            .order_by(ProductionOrder.po_no)
        )
    )
    machine_1 = Machine.__table__.alias("report_machine_1")
    machine_2 = Machine.__table__.alias("report_machine_2")
    machine_pairs = list(
        db.execute(
            select(MachinePair.id, machine_1.c.code, machine_2.c.code)
            .join(machine_1, machine_1.c.id == MachinePair.machine_1_id)
            .join(machine_2, machine_2.c.id == MachinePair.machine_2_id)
            .where(MachinePair.deleted_at.is_(None), MachinePair.is_active.is_(True))
            .order_by(machine_1.c.code, machine_2.c.code)
        )
    )
    employees = list(
        db.scalars(
            select(Employee)
            .where(Employee.deleted_at.is_(None), Employee.is_active.is_(True))
            .order_by(Employee.code)
        )
    )
    export_filters = {
        key: value
        for key, value in (
            ("date_from", date_from.isoformat() if date_from else None),
            ("date_to", date_to.isoformat() if date_to else None),
            ("order_id", order_id),
            ("machine_pair_id", machine_pair_id),
            ("employee_id", employee_id),
            ("kind", kind),
            ("group_by", group_by if tab == "oee" else None),
        )
        if value is not None
    }
    tab_urls = {
        item: f"/reports?{urlencode({**export_filters, 'tab': item})}" for item in REPORT_TABS
    }
    preset_urls = {
        "today": f"/reports?{urlencode({**export_filters, 'tab': tab, 'preset': 'today'})}",
        "month": f"/reports?{urlencode({**export_filters, 'tab': tab, 'preset': 'month'})}",
        "year": f"/reports?{urlencode({**export_filters, 'tab': tab, 'preset': 'year'})}",
    }
    summary_metrics = (
        {
            "order_count": len(report_rows),
            "ordered_quantity": sum(int(row["ordered_quantity"]) for row in report_rows),
            "finished_quantity": sum(int(row["finished_quantity"]) for row in report_rows),
            "ng_waiting_repair": sum(int(row["ng_waiting_repair"]) for row in report_rows),
        }
        if tab == "po-summary"
        else None
    )
    csrf_token = csrf_token_for_request(request)
    response = templates.TemplateResponse(
        request=request,
        name="reporting/dashboard.html",
        context={
            "title": "Báo cáo",
            "csrf_token": csrf_token,
            "tab": tab,
            "rows": report_rows,
            "orders": orders,
            "machine_pairs": machine_pairs,
            "employees": employees,
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
            "order_id": order_id,
            "machine_pair_id": machine_pair_id,
            "employee_id": employee_id,
            "kind": kind or "",
            "group_by": group_by,
            "process_labels": PROCESS_LABELS,
            "tab_urls": tab_urls,
            "preset_urls": preset_urls,
            "active_preset": preset or "",
            "summary_metrics": summary_metrics,
            "export_url": (
                f"/reports/export/{tab}?{urlencode(export_filters)}"
                if tab != "po-summary"
                else f"/reports/export/{tab}"
            ),
        },
    )
    set_csrf_cookie(response, csrf_token)
    return response


@router.get("/po-summary")
def po_summary(
    _actor: Annotated[User, Depends(require_permission("reports", "view"))],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, object]]:
    return po_summaries(db)


@router.get("/production")
def production_report(
    _actor: Annotated[User, Depends(require_permission("reports", "view"))],
    db: Annotated[Session, Depends(get_db)],
    date_from: date | None = None,
    date_to: date | None = None,
    order_id: int | None = Query(default=None, gt=0),
    machine_pair_id: int | None = Query(default=None, gt=0),
    employee_id: int | None = Query(default=None, gt=0),
) -> list[dict[str, object]]:
    return production_rows(
        db,
        date_from=date_from,
        date_to=date_to,
        order_id=order_id,
        machine_pair_id=machine_pair_id,
        employee_id=employee_id,
    )


@router.get("/ng")
def ng_report(
    _actor: Annotated[User, Depends(require_permission("reports", "view"))],
    db: Annotated[Session, Depends(get_db)],
    date_from: date | None = None,
    date_to: date | None = None,
    order_id: int | None = Query(default=None, gt=0),
    machine_pair_id: int | None = Query(default=None, gt=0),
    employee_id: int | None = Query(default=None, gt=0),
    kind: str | None = Query(default=None, pattern="^(scrap|repair)$"),
) -> list[dict[str, object]]:
    return quality_ng_rows(
        db,
        date_from=date_from,
        date_to=date_to,
        order_id=order_id,
        machine_pair_id=machine_pair_id,
        employee_id=employee_id,
        ng_kind=kind,
    )


@router.get("/repairs")
def repair_report(
    _actor: Annotated[User, Depends(require_permission("reports", "view"))],
    db: Annotated[Session, Depends(get_db)],
    order_id: int | None = Query(default=None, gt=0),
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, object]]:
    return repair_history_rows(db, order_id=order_id, date_from=date_from, date_to=date_to)


@router.get("/oee")
def oee_report(
    _actor: Annotated[User, Depends(require_permission("reports", "view"))],
    db: Annotated[Session, Depends(get_db)],
    date_from: date | None = None,
    date_to: date | None = None,
    order_id: int | None = Query(default=None, gt=0),
    machine_pair_id: int | None = Query(default=None, gt=0),
    employee_id: int | None = Query(default=None, gt=0),
    group_by: str | None = Query(default=None, pattern="^(day|month|order|product|pair|shift)$"),
) -> list[dict[str, object]]:
    rows = oee_rows(
        db,
        date_from=date_from,
        date_to=date_to,
        order_id=order_id,
        machine_pair_id=machine_pair_id,
        employee_id=employee_id,
    )
    return aggregate_oee(rows, group_by) if group_by else rows


@router.get("/export/{report_type}")
def export_report(
    report_type: str,
    _actor: Annotated[User, Depends(require_permission("reports", "view"))],
    db: Annotated[Session, Depends(get_db)],
    date_from: date | None = None,
    date_to: date | None = None,
    order_id: int | None = Query(default=None, gt=0),
    machine_pair_id: int | None = Query(default=None, gt=0),
    employee_id: int | None = Query(default=None, gt=0),
    kind: str | None = Query(default=None, pattern="^(scrap|repair)$"),
    group_by: str | None = Query(default=None, pattern="^(day|month|order|product|pair|shift)$"),
) -> StreamingResponse:
    if report_type == "production":
        rows = production_rows(
            db,
            date_from=date_from,
            date_to=date_to,
            order_id=order_id,
            machine_pair_id=machine_pair_id,
            employee_id=employee_id,
        )
    elif report_type == "ng":
        rows = quality_ng_rows(
            db,
            date_from=date_from,
            date_to=date_to,
            order_id=order_id,
            machine_pair_id=machine_pair_id,
            employee_id=employee_id,
            ng_kind=kind,
        )
    elif report_type == "repairs":
        rows = repair_history_rows(db, order_id=order_id, date_from=date_from, date_to=date_to)
    elif report_type == "oee":
        rows = oee_rows(
            db,
            date_from=date_from,
            date_to=date_to,
            order_id=order_id,
            machine_pair_id=machine_pair_id,
            employee_id=employee_id,
        )
    elif report_type == "po-summary":
        rows = po_summaries(db)
    else:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Không có loại báo cáo này.")
    if report_type == "oee" and group_by:
        rows = aggregate_oee(rows, group_by)
    content = _to_xlsx(rows, report_type)
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{report_type}.xlsx"'},
    )


@audit_router.get("")
def audit_log_report(
    _actor: Annotated[User, Depends(require_permission("audit", "view"))],
    db: Annotated[Session, Depends(get_db)],
    table_name: str | None = None,
    actor_id: int | None = Query(default=None, gt=0),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, object]]:
    return [
        {
            "id": row.id,
            "table_name": row.table_name,
            "record_id": row.record_id,
            "action": row.action,
            "old_values": row.old_values,
            "new_values": row.new_values,
            "reason": row.reason,
            "actor_id": row.actor_id,
            "created_at": row.created_at.isoformat(),
        }
        for row in list_audit_log(
            db,
            table_name=table_name,
            actor_id=actor_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    ]


@audit_router.get("/view", response_class=HTMLResponse, include_in_schema=False)
def audit_dashboard(
    request: Request,
    _actor: Annotated[User, Depends(require_permission("audit", "view"))],
    db: Annotated[Session, Depends(get_db)],
    table_name: str | None = None,
    actor_id: int | None = Query(default=None, gt=0),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> HTMLResponse:
    if table_name == "":
        table_name = None
    records = list_audit_log(
        db,
        table_name=table_name,
        actor_id=actor_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    table_names = list(
        db.scalars(select(AuditLog.table_name).distinct().order_by(AuditLog.table_name))
    )
    actors = list(db.scalars(select(User).where(User.deleted_at.is_(None)).order_by(User.username)))
    csrf_token = csrf_token_for_request(request)
    response = templates.TemplateResponse(
        request=request,
        name="reporting/audit.html",
        context={
            "title": "Nhật ký hệ thống",
            "csrf_token": csrf_token,
            "records": records,
            "table_names": table_names,
            "actors": actors,
            "actor_names": {item.id: item.display_name for item in actors},
            "table_name": table_name or "",
            "actor_id": actor_id,
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
            "limit": limit,
        },
    )
    set_csrf_cookie(response, csrf_token)
    return response


def _to_xlsx(rows: list[dict[str, object]], sheet_name: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name[:31]
    if rows:
        columns = list(rows[0])
        sheet.append(columns)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="145A67")
        for row in rows:
            sheet.append([row.get(key) for key in columns])
            for cell in sheet[sheet.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            max_length = min(max(len(str(cell.value or "")) for cell in column) + 2, 36)
            sheet.column_dimensions[column[0].column_letter].width = max(max_length, 12)
    else:
        sheet.append(["Không có dữ liệu theo bộ lọc đã chọn."])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()
