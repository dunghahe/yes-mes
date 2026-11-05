from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.auth.models import AuditLog, User
from app.modules.employees.schemas import EmployeeCreate, EmployeeUpdate
from app.modules.employees.service import (
    ConcurrentEmployeeChange,
    EmployeeManagementError,
    create_employee,
    list_active_employees,
    update_employee,
)


def _admin(db: Session) -> User:
    actor = User(
        username=f"employee-admin-{uuid4().hex}",
        display_name="Admin thử nghiệm",
        password_hash="not-used-by-test",
        role="admin",
        must_change_password=False,
        password_changed_at=datetime.now(UTC),
    )
    db.add(actor)
    db.flush()
    return actor


def _employee_data(code: str) -> EmployeeCreate:
    return EmployeeCreate(code=code, name="Nhân viên thử", employee_type="operator")


def test_create_employee_audits_values() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        employee = create_employee(db, _employee_data(f"NV-{uuid4().hex}"), actor.id)
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.table_name == "employees", AuditLog.record_id == employee.id
            )
        )
        assert employee.is_active
        assert audit.actor_id == actor.id
        assert audit.new_values["employee_type"] == "operator"
    finally:
        db.rollback()
        db.close()


def test_employee_code_must_be_unique() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        code = f"NV-{uuid4().hex}"
        create_employee(db, _employee_data(code), actor.id)
        with pytest.raises(EmployeeManagementError, match="đã được sử dụng"):
            create_employee(db, _employee_data(code), actor.id)
    finally:
        db.rollback()
        db.close()


def test_employee_type_is_limited_to_supported_values() -> None:
    with pytest.raises(ValidationError):
        EmployeeCreate(code="NV-1", name="Người thử", employee_type="other")


def test_inactive_employee_is_hidden_from_new_selectors_and_update_is_versioned() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        employee = create_employee(db, _employee_data(f"NV-{uuid4().hex}"), actor.id)
        original_version = employee.version
        updated = update_employee(
            db,
            employee.id,
            EmployeeUpdate(
                code=employee.code,
                name="Đã ngừng làm",
                employee_type="operator",
                is_active=False,
                version=original_version,
            ),
            actor.id,
        )

        assert not updated.is_active
        assert employee not in list_active_employees(db)
        with pytest.raises(ConcurrentEmployeeChange, match="tải lại"):
            update_employee(
                db,
                employee.id,
                EmployeeUpdate(
                    code=employee.code,
                    name=employee.name,
                    employee_type=employee.employee_type,
                    is_active=True,
                    version=original_version,
                ),
                actor.id,
            )
    finally:
        db.rollback()
        db.close()
