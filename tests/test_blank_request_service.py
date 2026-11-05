from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.assets.models import (
    Machine,
    MachineGroup,
    MachineGroupAssignment,
    MachinePair,
)
from app.modules.auth.models import AuditLog, User
from app.modules.blank_requests.models import (
    BlankRequestCounter,
    BlankRequestPrint,
)
from app.modules.blank_requests.schemas import (
    BlankRequestCancel,
    BlankRequestCreate,
    BlankRequestDelivery,
    BlankRequestUpdate,
)
from app.modules.blank_requests.service import (
    BlankRequestManagementError,
    ConcurrentBlankRequestChange,
    cancel_blank_request,
    confirm_delivery,
    create_blank_request,
    list_blank_requests,
    queue_print_stats,
    register_print,
    request_resources,
    update_blank_request,
)
from app.modules.employees.models import Employee
from app.modules.orders.schemas import OrderCreate
from app.modules.orders.service import create_order
from app.modules.products.models import Product
from app.modules.schedules.models import ProductionSchedule
from app.modules.shifts.models import Shift


def _fixtures(db: Session) -> dict[str, object]:
    now = datetime.now(UTC)
    actor = User(
        username=f"engineering-{uuid4().hex}",
        display_name="Kỹ thuật thử nghiệm",
        password_hash="not-used-by-this-test",
        role="engineering",
        must_change_password=False,
        password_changed_at=now,
    )
    product = Product(
        code=f"BR-{uuid4().hex}",
        name="Sản phẩm thử",
        cycle_time_seconds=3,
        default_process_type="FULL",
        is_active=True,
    )
    shift = Shift(
        name=f"Kíp-{uuid4().hex}",
        start_time=time(7),
        end_time=time(15),
        planned_break_minutes=30,
        crosses_midnight=False,
        is_active=True,
    )
    group = MachineGroup(code=f"G-{uuid4().hex}", name="Nhóm thử", is_active=True)
    machine_1 = Machine(code=f"M1-{uuid4().hex[:8]}", name="Máy 1", production_area="Khu A")
    machine_2 = Machine(code=f"M2-{uuid4().hex[:8]}", name="Máy 2", production_area="Khu A")
    operator = Employee(
        code=f"NV-{uuid4().hex}", name="Người vận hành", employee_type="operator", is_active=True
    )
    qc_employee = Employee(
        code=f"QC-{uuid4().hex}", name="QC thử", employee_type="qc", is_active=True
    )
    db.add_all([actor, product, shift, group, machine_1, machine_2, operator, qc_employee])
    db.flush()
    pair = MachinePair(
        machine_1_id=min(machine_1.id, machine_2.id),
        machine_2_id=max(machine_1.id, machine_2.id),
        is_active=True,
    )
    db.add(pair)
    db.flush()
    assignment = MachineGroupAssignment(
        machine_pair_id=pair.id,
        machine_group_id=group.id,
        valid_from=now - timedelta(days=5),
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(assignment)
    db.flush()
    order = create_order(
        db,
        OrderCreate(
            po_no=f"PO-{uuid4().hex}",
            product_id=product.id,
            ordered_quantity=100,
            process_type="FULL",
            raw_material_code="RM-01",
            drawing_number="DWG-01",
            revision="A",
            material="Thép",
            blank_size="10x20",
            order_received_date=date(2026, 11, 5),
        ),
        actor.id,
    )
    schedule = ProductionSchedule(
        production_date=date(2026, 11, 6),
        shift_id=shift.id,
        order_id=order.id,
        planned_quantity=100,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(schedule)
    db.flush()
    return {
        "actor": actor,
        "group": group,
        "pair": pair,
        "operator": operator,
        "qc_employee": qc_employee,
        "schedule": schedule,
    }


def _data(fixtures: dict[str, object], **updates: object) -> BlankRequestCreate:
    values = {
        "schedule_id": fixtures["schedule"].id,
        "blank_quantity": 50,
        "machine_group_id": fixtures["group"].id,
        "machine_pair_ids": [fixtures["pair"].id],
        "operator_ids": [fixtures["operator"].id],
    }
    return BlankRequestCreate.model_validate({**values, **updates})


def test_create_request_generates_daily_number_and_audits_selected_resources() -> None:
    db = SessionLocal()
    try:
        db.begin()
        fixtures = _fixtures(db)
        actor = fixtures["actor"]
        first = create_blank_request(db, _data(fixtures), actor.id, today=date(2026, 11, 5))
        second = create_blank_request(db, _data(fixtures), actor.id, today=date(2026, 11, 5))
        audit_rows = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.table_name.in_(
                        (
                            "blank_requests",
                            "blank_request_pairs",
                            "blank_request_operators",
                            "blank_request_counters",
                        )
                    )
                )
            )
        )

        assert first.req_no == "YC-261105-01"
        assert second.req_no == "YC-261105-02"
        assert first.status == "submitted"
        assert request_resources(db, [first.id]) == {
            first.id: ([fixtures["pair"].id], [fixtures["operator"].id])
        }
        assert db.scalar(select(BlankRequestCounter.last_number)) == 2
        assert len(audit_rows) == 8
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("blank_quantity", 0),
        ("blank_quantity", -2),
        ("machine_pair_ids", []),
        ("operator_ids", []),
        ("machine_pair_ids", [1, 1]),
        ("operator_ids", [1, 1]),
    ],
)
def test_request_rejects_missing_or_invalid_required_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        BlankRequestCreate.model_validate(
            {
                "schedule_id": 1,
                "blank_quantity": 10,
                "machine_group_id": 1,
                "machine_pair_ids": [1],
                "operator_ids": [1],
                field: value,
            }
        )


def test_request_rejects_inactive_schedule_wrong_group_or_nonoperator() -> None:
    db = SessionLocal()
    try:
        db.begin()
        fixtures = _fixtures(db)
        actor = fixtures["actor"]
        schedule = fixtures["schedule"]
        schedule.deleted_at = datetime.now(UTC)
        with pytest.raises(BlankRequestManagementError, match="lịch đang sử dụng"):
            create_blank_request(db, _data(fixtures), actor.id, today=date(2026, 11, 5))
        schedule.deleted_at = None

        other_group = MachineGroup(code=f"G-{uuid4().hex}", name="Nhóm khác", is_active=True)
        db.add(other_group)
        db.flush()
        with pytest.raises(BlankRequestManagementError, match="thuộc nhóm"):
            create_blank_request(
                db,
                _data(fixtures, machine_group_id=other_group.id),
                actor.id,
                today=date(2026, 11, 5),
            )

        with pytest.raises(BlankRequestManagementError, match="vận hành"):
            create_blank_request(
                db,
                _data(fixtures, operator_ids=[fixtures["qc_employee"].id]),
                actor.id,
                today=date(2026, 11, 5),
            )
    finally:
        db.rollback()
        db.close()


def test_update_request_uses_version_reason_and_audits_old_and_new_values() -> None:
    db = SessionLocal()
    try:
        db.begin()
        fixtures = _fixtures(db)
        actor = fixtures["actor"]
        request = create_blank_request(db, _data(fixtures), actor.id, today=date(2026, 11, 5))
        old_version = request.version
        updated = update_blank_request(
            db,
            request.id,
            BlankRequestUpdate(
                blank_quantity=75,
                machine_group_id=fixtures["group"].id,
                machine_pair_ids=[fixtures["pair"].id],
                operator_ids=[fixtures["operator"].id],
                reason="Sửa theo phiếu giấy đã hiệu chỉnh",
                version=old_version,
            ),
            actor.id,
            "data_entry",
        )
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.table_name == "blank_requests", AuditLog.record_id == request.id)
            .order_by(AuditLog.id.desc())
        )

        assert updated.blank_quantity == 75
        assert updated.version == old_version + 1
        assert audit.old_values["blank_quantity"] == 50
        assert audit.new_values["blank_quantity"] == 75
        assert audit.reason == "Sửa theo phiếu giấy đã hiệu chỉnh"
        with pytest.raises(ConcurrentBlankRequestChange, match="tải lại"):
            update_blank_request(
                db,
                request.id,
                BlankRequestUpdate(
                    blank_quantity=80,
                    machine_group_id=fixtures["group"].id,
                    machine_pair_ids=[fixtures["pair"].id],
                    operator_ids=[fixtures["operator"].id],
                    reason="Sửa lần hai",
                    version=old_version,
                ),
                actor.id,
                "data_entry",
            )
    finally:
        db.rollback()
        db.close()


def test_only_admin_can_edit_delivered_request_and_cannot_cancel_it() -> None:
    db = SessionLocal()
    try:
        db.begin()
        fixtures = _fixtures(db)
        actor = fixtures["actor"]
        request = create_blank_request(db, _data(fixtures), actor.id, today=date(2026, 11, 5))
        request.status = "delivered"
        request.delivered_quantity = request.blank_quantity
        request.delivered_at = datetime.now(UTC)
        request.delivered_by = actor.id
        update_blank_request(
            db,
            request.id,
            BlankRequestUpdate(
                blank_quantity=55,
                machine_group_id=fixtures["group"].id,
                machine_pair_ids=[fixtures["pair"].id],
                operator_ids=[fixtures["operator"].id],
                reason="Admin sửa sau khi giao",
                version=request.version,
            ),
            actor.id,
            "admin",
        )
        with pytest.raises(BlankRequestManagementError, match="chỉ Admin"):
            update_blank_request(
                db,
                request.id,
                BlankRequestUpdate(
                    blank_quantity=60,
                    machine_group_id=fixtures["group"].id,
                    machine_pair_ids=[fixtures["pair"].id],
                    operator_ids=[fixtures["operator"].id],
                    reason="Nhập liệu sửa",
                    version=request.version,
                ),
                actor.id,
                "data_entry",
            )
        with pytest.raises(BlankRequestManagementError, match="Chỉ hủy được"):
            cancel_blank_request(db, request.id, "Không còn nhu cầu", request.version, actor.id)
    finally:
        db.rollback()
        db.close()


def test_confirm_delivery_warns_on_quantity_mismatch_and_audits_delivery() -> None:
    db = SessionLocal()
    try:
        db.begin()
        fixtures = _fixtures(db)
        actor = fixtures["actor"]
        request = create_blank_request(db, _data(fixtures), actor.id, today=date(2026, 11, 5))

        delivered, mismatch = confirm_delivery(db, request.id, 48, request.version, actor.id)

        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.table_name == "blank_requests", AuditLog.record_id == request.id)
            .order_by(AuditLog.id.desc())
        )
        assert mismatch
        assert delivered.status == "delivered"
        assert delivered.delivered_quantity == 48
        assert delivered.delivered_by == actor.id
        assert delivered.version == 2
        assert audit.action == "deliver"
        assert audit.old_values["status"] == "submitted"
        assert audit.new_values["delivered_quantity"] == 48
        assert audit.reason == "Kho xác nhận đã giao phôi"

        with pytest.raises(ConcurrentBlankRequestChange, match="tải lại"):
            confirm_delivery(db, request.id, 50, version=1, actor_id=actor.id)
        with pytest.raises(BlankRequestManagementError, match="đang chờ kho"):
            confirm_delivery(db, request.id, 50, delivered.version, actor.id)
        with pytest.raises(ValidationError):
            BlankRequestDelivery(actual_quantity=0, version=1)
    finally:
        db.rollback()
        db.close()


def test_cancel_request_requires_reason_and_sets_terminal_status() -> None:
    db = SessionLocal()
    try:
        db.begin()
        fixtures = _fixtures(db)
        actor = fixtures["actor"]
        request = create_blank_request(db, _data(fixtures), actor.id, today=date(2026, 11, 5))
        cancelled = cancel_blank_request(
            db, request.id, "Kế hoạch hủy theo giấy", request.version, actor.id
        )
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.table_name == "blank_requests", AuditLog.record_id == request.id)
            .order_by(AuditLog.id.desc())
        )

        assert cancelled.status == "cancelled"
        assert cancelled.version == 2
        assert audit.action == "cancel"
        assert audit.old_values["status"] == "submitted"
        assert audit.new_values["status"] == "cancelled"
        assert audit.reason == "Kế hoạch hủy theo giấy"
        with pytest.raises(ValidationError):
            BlankRequestCancel(reason="  ", version=cancelled.version)
        with pytest.raises(BlankRequestManagementError, match="đang chờ"):
            cancel_blank_request(db, request.id, "Hủy tiếp", cancelled.version, actor.id)
        with pytest.raises(BlankRequestManagementError, match="đã hủy"):
            register_print(db, request.id, "qc", actor.id)
    finally:
        db.rollback()
        db.close()


def test_print_events_record_each_form_and_allow_reprints() -> None:
    db = SessionLocal()
    try:
        db.begin()
        fixtures = _fixtures(db)
        actor = fixtures["actor"]
        request = create_blank_request(db, _data(fixtures), actor.id, today=date(2026, 11, 5))
        first_print, production_row = register_print(db, request.id, "production", actor.id)
        second_print, qc_row = register_print(db, request.id, "qc", actor.id)
        reprint, _ = register_print(db, request.id, "production", actor.id)
        stats = queue_print_stats(db, [request.id])[request.id]
        pending = list_blank_requests(db, status="submitted")

        assert production_row[0].req_no == qc_row[0].req_no == request.req_no
        assert first_print.form_type == "production"
        assert second_print.form_type == "qc"
        assert reprint.form_type == "production"
        assert stats["production"][1] == 2
        assert stats["qc"][1] == 1
        assert len(pending) == 1
        assert (
            db.scalar(
                select(AuditLog.id).where(
                    AuditLog.table_name == "blank_request_prints",
                    AuditLog.record_id == first_print.id,
                    AuditLog.action == "print",
                )
            )
            is not None
        )
        assert db.scalar(select(BlankRequestPrint.id).where(BlankRequestPrint.id == reprint.id))
    finally:
        db.rollback()
        db.close()
