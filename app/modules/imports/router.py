from __future__ import annotations

from io import BytesIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
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
from app.core.permissions import require_admin
from app.modules.assets.models import Machine, MachinePair
from app.modules.assets.schemas import MachineInput, PairInput
from app.modules.assets.service import AssetManagementError, create_machine, create_pair
from app.modules.auth.models import User
from app.modules.defects.models import DefectCode
from app.modules.defects.schemas import DefectCodeCreate
from app.modules.defects.service import DefectCodeError, create_defect_code
from app.modules.downtime.models import DowntimeReason
from app.modules.downtime.schemas import DowntimeReasonCreate
from app.modules.downtime.service import DowntimeReasonError, create_reason
from app.modules.employees.models import Employee
from app.modules.employees.schemas import EmployeeCreate
from app.modules.employees.service import EmployeeManagementError, create_employee
from app.modules.shifts.models import Shift
from app.modules.shifts.schemas import ShiftCreate
from app.modules.shifts.service import ShiftManagementError, create_shift

router = APIRouter(prefix="/admin/imports", tags=["master-data-imports"])
templates = Jinja2Templates(directory="app/templates")

SPECS: dict[str, tuple[str, str, list[str]]] = {
    "machines": ("Máy", "Machines", ["Mã máy", "Tên máy", "Khu sản xuất"]),
    "machine-pairs": ("Cặp máy", "MachinePairs", ["Mã máy 1", "Mã máy 2"]),
    "employees": ("Nhân viên", "Employees", ["Mã nhân viên", "Họ tên", "Loại nhân viên"]),
    "defects": ("Mã lỗi", "Defects", ["Mã lỗi", "Tên lỗi", "Phát hiện tại (SX/BAVIA)"]),
    "downtime": ("Lý do dừng máy", "Downtime", ["Mã lý do", "Tên lý do"]),
    "shifts": (
        "Ca/kíp",
        "Shifts",
        ["Tên ca/kíp", "Giờ bắt đầu", "Giờ kết thúc", "Nghỉ (phút)", "Qua nửa đêm (true/false)"],
    ),
}
RETURN_URLS = {
    "machines": "/admin/machines",
    "machine-pairs": "/admin/machines",
    "employees": "/admin/employees",
    "defects": "/admin/defect-codes",
    "downtime": "/admin/downtime-reasons",
    "shifts": "/admin/shifts",
}


def _render_preview(
    request: Request, context: dict[str, object], status_code: int = 200
) -> HTMLResponse:
    token = csrf_token_for_request(request)
    response = templates.TemplateResponse(
        request=request,
        name="imports/preview.html",
        context={**context, "csrf_token": token},
        status_code=status_code,
    )
    set_csrf_cookie(response, token)
    return response


def _validate_row(
    resource: str, row: dict[str, str], machine_ids: dict[str, int] | None = None
) -> Any:
    if resource == "machines":
        return MachineInput(
            code=row["Mã máy"], name=row["Tên máy"], production_area=row["Khu sản xuất"]
        )
    if resource == "machine-pairs":
        machine_ids = machine_ids or {}
        first = machine_ids.get(row["Mã máy 1"].casefold())
        second = machine_ids.get(row["Mã máy 2"].casefold())
        if first is None or second is None:
            raise ValueError("Cả hai máy phải được khai báo và đang hoạt động.")
        return PairInput(machine_1_id=first, machine_2_id=second)
    if resource == "employees":
        return EmployeeCreate(
            code=row["Mã nhân viên"], name=row["Họ tên"], employee_type=row["Loại nhân viên"]
        )
    if resource == "defects":
        return DefectCodeCreate(
            code=row["Mã lỗi"], name=row["Tên lỗi"], detected_at=row["Phát hiện tại (SX/BAVIA)"]
        )
    if resource == "downtime":
        return DowntimeReasonCreate(code=row["Mã lý do"], name=row["Tên lý do"])
    if resource == "shifts":
        raw_midnight = row["Qua nửa đêm (true/false)"].strip().casefold()
        if raw_midnight not in {"true", "false", "1", "0", "có", "không"}:
            raise ValueError("Qua nửa đêm nhập true/false hoặc có/không.")
        return ShiftCreate(
            name=row["Tên ca/kíp"],
            start_time=row["Giờ bắt đầu"],
            end_time=row["Giờ kết thúc"],
            planned_break_minutes=row["Nghỉ (phút)"],
            crosses_midnight=raw_midnight in {"true", "1", "có"},
        )
    raise ValueError("Loại dữ liệu nhập không hợp lệ.")


def _existing_codes(db: Session, resource: str) -> set[str]:
    if resource == "machines":
        return set(db.scalars(select(Machine.code).where(Machine.deleted_at.is_(None))))
    if resource == "employees":
        return set(db.scalars(select(Employee.code).where(Employee.deleted_at.is_(None))))
    if resource == "defects":
        return set(db.scalars(select(DefectCode.code).where(DefectCode.deleted_at.is_(None))))
    if resource == "downtime":
        return set(
            db.scalars(select(DowntimeReason.code).where(DowntimeReason.deleted_at.is_(None)))
        )
    if resource == "shifts":
        return set(db.scalars(select(Shift.name).where(Shift.deleted_at.is_(None))))
    return set()


def _preview_errors(
    db: Session, resource: str, rows: list[dict[str, str]]
) -> list[dict[str, int | str]]:
    errors: list[dict[str, int | str]] = []
    machine_ids = {
        machine.code.casefold(): machine.id
        for machine in db.scalars(
            select(Machine).where(Machine.is_active.is_(True), Machine.deleted_at.is_(None))
        )
    }
    if resource == "machine-pairs":
        existing_pairs = {
            tuple(sorted((pair.machine_1_id, pair.machine_2_id)))
            for pair in db.scalars(select(MachinePair).where(MachinePair.deleted_at.is_(None)))
        }
        seen_pairs: set[tuple[int, int]] = set()
        for row in rows:
            try:
                data = _validate_row(resource, row, machine_ids)
                pair = tuple(sorted((data.machine_1_id, data.machine_2_id)))
                if pair[0] == pair[1]:
                    raise ValueError("Hai mã máy phải khác nhau.")
                if pair in existing_pairs or pair in seen_pairs:
                    raise ValueError("Cặp máy đã tồn tại hoặc bị lặp trong file.")
                seen_pairs.add(pair)
            except (ValidationError, ValueError) as exc:
                message = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "Thiếu dữ liệu hoặc mã máy không hợp lệ."
                )
                errors.append({"row": int(row["__row__"]), "message": message})
        return errors

    existing = _existing_codes(db, resource)
    seen: set[str] = set()
    code_column = {
        "machines": "Mã máy",
        "employees": "Mã nhân viên",
        "defects": "Mã lỗi",
        "downtime": "Mã lý do",
        "shifts": "Tên ca/kíp",
    }[resource]
    for row in rows:
        code = row[code_column].strip()
        try:
            _validate_row(resource, row)
            if code in existing or code in seen:
                raise ValueError(f"'{code}' đã tồn tại hoặc bị lặp.")
            seen.add(code)
        except (ValidationError, ValueError) as exc:
            message = (
                str(exc)
                if isinstance(exc, ValueError)
                else "Thiếu dữ liệu hoặc giá trị không đúng định dạng."
            )
            errors.append({"row": int(row["__row__"]), "message": message})
    return errors


def _create_rows(db: Session, resource: str, rows: list[dict[str, str]], actor_id: int) -> None:
    machine_ids = {
        machine.code.casefold(): machine.id
        for machine in db.scalars(
            select(Machine).where(Machine.is_active.is_(True), Machine.deleted_at.is_(None))
        )
    }
    for row in rows:
        data = _validate_row(resource, row, machine_ids)
        if resource == "machines":
            create_machine(db, data, actor_id)
        elif resource == "machine-pairs":
            create_pair(db, data.machine_1_id, data.machine_2_id, actor_id)
        elif resource == "employees":
            create_employee(db, data, actor_id)
        elif resource == "defects":
            create_defect_code(db, data, actor_id)
        elif resource == "downtime":
            create_reason(db, data, actor_id)
        elif resource == "shifts":
            create_shift(db, data, actor_id)


@router.get("/{resource}/template")
def import_template(resource: str, _actor: Annotated[User, Depends(require_admin)]) -> Response:
    spec = SPECS.get(resource)
    if spec is None:
        return Response("Không tìm thấy loại file mẫu.", status_code=404)
    title, sheet_name, headers = spec
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="20499B")
    for index in range(1, len(headers) + 1):
        sheet.column_dimensions[chr(64 + index)].width = max(18, len(headers[index - 1]) + 5)
    sheet.freeze_panes = "A2"
    dropdowns = {
        "employees": ("C", '"operator,qc,repair,engineering"'),
        "defects": ("C", '"SX,BAVIA"'),
        "shifts": ("E", '"true,false"'),
    }
    if resource in dropdowns:
        column, values = dropdowns[resource]
        validation = DataValidation(type="list", formula1=values, allow_blank=False)
        sheet.add_data_validation(validation)
        validation.add(f"{column}2:{column}5001")
    guide = workbook.create_sheet("HuongDan")
    guide.append([f"HƯỚNG DẪN NHẬP {title.upper()}"])
    guide.append([f"Mỗi dòng trên sheet {sheet_name} là một bản ghi."])
    guide.append(["Không đổi tên sheet hoặc hàng tiêu đề."])
    notes = {
        "machines": ["Khu sản xuất được gắn với từng máy."],
        "machine-pairs": ["Hai máy phải khác nhau và đã có trong danh mục Máy."],
        "employees": [
            "Loại nhân viên: operator (vận hành), qc, repair (sửa chữa), engineering (kỹ thuật)."
        ],
        "defects": ["Phát hiện tại: SX hoặc BAVIA."],
        "downtime": ["Mã lý do phải duy nhất."],
        "shifts": ["Giờ theo HH:MM; qua nửa đêm chọn true hoặc false."],
    }
    for note in notes[resource]:
        guide.append([note])
    guide.append(["Tải file lên phần mềm để kiểm tra; chỉ file không lỗi mới được nhập."])
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="mau-{resource}.xlsx"'},
    )


@router.post("/{resource}/preview", response_class=HTMLResponse)
async def import_preview(
    request: Request,
    resource: str,
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    csrf_token: Annotated[str, Form()],
    upload: Annotated[UploadFile, File()],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    spec = SPECS.get(resource)
    if spec is None:
        return Response("Không tìm thấy danh mục.", status_code=404)
    if not upload.filename or not upload.filename.lower().endswith(".xlsx"):
        return _render_preview(
            request,
            {
                "title": "Không đọc được file Excel",
                "resource": resource,
                "rows": [],
                "errors": [{"row": "—", "message": "Chỉ nhận file .xlsx."}],
                "confirm_url": "",
                "return_url": RETURN_URLS[resource],
            },
            422,
        )
    title, sheet_name, headers = spec
    try:
        rows = parse_xlsx(await upload.read(10 * 1024 * 1024 + 1), sheet_name, headers)
    except ValueError as exc:
        return _render_preview(
            request,
            {
                "title": "Không đọc được file Excel",
                "resource": resource,
                "rows": [],
                "errors": [{"row": "—", "message": str(exc)}],
                "confirm_url": "",
                "return_url": RETURN_URLS[resource],
            },
            422,
        )
    errors = _preview_errors(db, resource, rows)
    token = store_preview(db, actor.id, resource, rows, errors) if not errors else ""
    if token:
        db.commit()
    response = _render_preview(
        request,
        {
            "title": f"Kiểm tra file {title}",
            "resource": resource,
            "rows": rows,
            "errors": errors,
            "confirm_url": f"/admin/imports/{resource}/{token}/confirm" if token else "",
            "return_url": RETURN_URLS[resource],
        },
    )
    return response


@router.post("/{resource}/{token}/confirm", response_class=HTMLResponse)
def import_confirm(
    request: Request,
    resource: str,
    token: str,
    csrf_token: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    preview = get_preview(db, token, actor.id, resource)
    if preview is None or resource not in SPECS:
        return Response("Bản xem trước đã hết hạn. Hãy tải file lên lại.", status_code=410)
    if preview.errors:
        return Response("File còn lỗi, chưa thể nhập.", status_code=422)
    try:
        _create_rows(db, resource, preview.rows, actor.id)
        discard_preview(db, preview)
        db.commit()
    except (
        ValidationError,
        IntegrityError,
        AssetManagementError,
        EmployeeManagementError,
        DefectCodeError,
        DowntimeReasonError,
        ShiftManagementError,
    ) as exc:
        db.rollback()
        return Response(f"Không nhập được file; không dòng nào được lưu. {exc}", status_code=422)
    return Response(status_code=303, headers={"Location": RETURN_URLS[resource]})
