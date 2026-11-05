from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.employees.models import Employee
from app.modules.employees.schemas import EmployeeCreate, EmployeeUpdate


class EmployeeManagementError(Exception):
    """An employee master data rule rejected the request."""


class ConcurrentEmployeeChange(EmployeeManagementError):
    """The employee changed since the administrator loaded it."""


def create_employee(db: Session, data: EmployeeCreate, actor_id: int) -> Employee:
    if db.scalar(
        select(Employee.id).where(Employee.code == data.code, Employee.deleted_at.is_(None))
    ):
        raise EmployeeManagementError("Mã nhân viên này đã được sử dụng.")
    now = datetime.now(UTC)
    employee = Employee(
        code=data.code,
        name=data.name,
        employee_type=data.employee_type,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(employee)
    db.flush()
    _audit(db, actor_id, employee, "create", None, _values(employee), "Admin tạo nhân viên")
    return employee


def update_employee(db: Session, employee_id: int, data: EmployeeUpdate, actor_id: int) -> Employee:
    employee = db.scalar(
        select(Employee)
        .where(Employee.id == employee_id, Employee.deleted_at.is_(None))
        .with_for_update()
    )
    if employee is None:
        raise EmployeeManagementError("Không tìm thấy nhân viên.")
    if employee.version != data.version:
        raise ConcurrentEmployeeChange("Nhân viên đã thay đổi. Hãy tải lại trang rồi thử lại.")
    if data.code != employee.code and db.scalar(
        select(Employee.id).where(
            Employee.code == data.code,
            Employee.deleted_at.is_(None),
            Employee.id != employee.id,
        )
    ):
        raise EmployeeManagementError("Mã nhân viên này đã được sử dụng.")

    old_values = _values(employee)
    employee.code = data.code
    employee.name = data.name
    employee.employee_type = data.employee_type
    employee.is_active = data.is_active
    employee.version += 1
    employee.updated_at = datetime.now(UTC)
    employee.updated_by = actor_id
    _audit(
        db,
        actor_id,
        employee,
        "update",
        old_values,
        _values(employee),
        "Admin cập nhật nhân viên hoặc trạng thái",
    )
    return employee


def list_employees(db: Session) -> list[Employee]:
    return list(
        db.scalars(
            select(Employee)
            .where(Employee.deleted_at.is_(None))
            .order_by(Employee.is_active.desc(), Employee.code, Employee.id)
        )
    )


def list_active_employees(db: Session, employee_type: str | None = None) -> list[Employee]:
    query = select(Employee).where(Employee.deleted_at.is_(None), Employee.is_active.is_(True))
    if employee_type:
        query = query.where(Employee.employee_type == employee_type)
    return list(db.scalars(query.order_by(Employee.code, Employee.id)))


def _values(employee: Employee) -> dict[str, str | bool]:
    return {
        "code": employee.code,
        "name": employee.name,
        "employee_type": employee.employee_type,
        "is_active": employee.is_active,
    }


def _audit(
    db: Session,
    actor_id: int,
    employee: Employee,
    action: str,
    old_values: dict[str, str | bool] | None,
    new_values: dict[str, str | bool],
    reason: str,
) -> None:
    db.add(
        AuditLog(
            table_name="employees",
            record_id=employee.id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            actor_id=actor_id,
        )
    )
