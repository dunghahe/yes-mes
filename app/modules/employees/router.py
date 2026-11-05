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
from app.modules.employees.models import EMPLOYEE_TYPES, Employee
from app.modules.employees.schemas import EmployeeCreate, EmployeeUpdate
from app.modules.employees.service import (
    EmployeeManagementError,
    create_employee,
    list_employees,
    update_employee,
)

router = APIRouter(prefix="/admin/employees", tags=["employees"])
templates = Jinja2Templates(directory="app/templates")
TYPE_LABELS = {
    "operator": "Vận hành",
    "qc": "QC",
    "repair": "Sửa chữa",
    "engineering": "Kỹ thuật",
}


def _render(
    request: Request,
    *,
    db: Session,
    employee: Employee | None = None,
    error: str | None = None,
    submitted: dict[str, object] | None = None,
    errors: dict[str, str] | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    csrf_token = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        request=request,
        name="employees/manage.html",
        context={
            "title": "Quản lý nhân viên",
            "employees": list_employees(db),
            "employee": employee,
            "employee_types": EMPLOYEE_TYPES,
            "type_labels": TYPE_LABELS,
            "error": error,
            "submitted": submitted or {},
            "errors": errors or {},
            "csrf_token": csrf_token,
        },
        status_code=status_code,
    )
    set_csrf_cookie(response, csrf_token)
    return response


@router.get("", response_class=HTMLResponse)
def employee_page(
    request: Request,
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    return _render(request, db=db)


@router.post("", response_class=HTMLResponse)
def create_employee_submit(
    request: Request,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    employee_type: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {"code": code, "name": name, "employee_type": employee_type}
    try:
        create_employee(db, EmployeeCreate.model_validate(submitted), actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render(
            request,
            db=db,
            submitted=submitted,
            errors={
                str(item["loc"][0]): "Giá trị không hợp lệ hoặc vượt giới hạn cho phép."
                for item in exc.errors()
                if item["loc"]
            },
            status_code=422,
        )
    except (EmployeeManagementError, IntegrityError) as exc:
        db.rollback()
        message = (
            str(exc)
            if isinstance(exc, EmployeeManagementError)
            else "Mã nhân viên này đã được sử dụng."
        )
        return _render(request, db=db, submitted=submitted, error=message, status_code=422)
    return RedirectResponse("/admin/employees", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{employee_id}", response_class=HTMLResponse)
def update_employee_submit(
    request: Request,
    employee_id: int,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    employee_type: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    is_active: Annotated[bool, Form()] = False,
    version: Annotated[int, Form()] = 1,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted: dict[str, object] = {
        "code": code,
        "name": name,
        "employee_type": employee_type,
        "is_active": is_active,
    }
    try:
        update_employee(
            db,
            employee_id,
            EmployeeUpdate(**submitted, version=version),
            actor.id,
        )
        db.commit()
    except ValidationError as exc:
        db.rollback()
        employee = db.get(Employee, employee_id)
        if employee is None or employee.deleted_at is not None:
            return Response("Không tìm thấy nhân viên.", status_code=404)
        return _render(
            request,
            db=db,
            employee=employee,
            submitted=submitted,
            errors={
                str(item["loc"][0]): "Giá trị không hợp lệ hoặc vượt giới hạn cho phép."
                for item in exc.errors()
                if item["loc"]
            },
            status_code=422,
        )
    except (EmployeeManagementError, IntegrityError) as exc:
        db.rollback()
        employee = db.get(Employee, employee_id)
        if employee is None or employee.deleted_at is not None:
            return Response("Không tìm thấy nhân viên.", status_code=404)
        message = (
            str(exc)
            if isinstance(exc, EmployeeManagementError)
            else "Mã nhân viên này đã được sử dụng."
        )
        return _render(request, db=db, employee=employee, error=message, status_code=422)
    return RedirectResponse("/admin/employees", status_code=status.HTTP_303_SEE_OTHER)
