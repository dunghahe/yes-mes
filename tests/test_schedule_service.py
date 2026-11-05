from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.assets.models import MachineGroup
from app.modules.auth.models import AuditLog, User
from app.modules.blank_requests.models import BlankRequest
from app.modules.orders.schemas import OrderCreate
from app.modules.orders.service import create_order
from app.modules.products.models import Product
from app.modules.schedules.models import ProductionSchedule
from app.modules.schedules.router import _calendar_window
from app.modules.schedules.schemas import ScheduleBatchCreate, ScheduleUpdate
from app.modules.schedules.service import (
    ConcurrentScheduleChange,
    ScheduleManagementError,
    create_schedule_batch,
    soft_delete_schedule,
    update_schedule,
)
from app.modules.shifts.models import Shift


def _fixtures(db: Session) -> tuple[User, Product, Shift, int]:
    actor = User(
        username=f"schedule-admin-{uuid4().hex}",
        display_name="Admin thử nghiệm",
        password_hash="not-used-by-this-test",
        role="admin",
        must_change_password=False,
        password_changed_at=datetime.now(UTC),
    )
    product = Product(
        code=f"SCH-{uuid4().hex}",
        name="Sản phẩm thử nghiệm",
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
    db.add_all([actor, product, shift])
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
    return actor, product, shift, order.id


def _batch(
    shift_id: int, order_id: int, *, dates: list[date], quantity: int
) -> ScheduleBatchCreate:
    return ScheduleBatchCreate(
        production_dates=dates,
        shift_id=shift_id,
        order_id=order_id,
        planned_quantity=quantity,
    )


@pytest.mark.parametrize(
    ("view", "anchor", "start", "end"),
    [
        ("day", date(2026, 11, 5), date(2026, 11, 5), date(2026, 11, 5)),
        ("week", date(2026, 11, 5), date(2026, 11, 2), date(2026, 11, 8)),
        ("month", date(2028, 2, 10), date(2028, 2, 1), date(2028, 2, 29)),
    ],
)
def test_calendar_views_calculate_day_week_and_leap_month_ranges(
    view: str, anchor: date, start: date, end: date
) -> None:
    actual_start, actual_end, days, _, _, _ = _calendar_window(view, anchor)
    assert actual_start == start
    assert actual_end == end
    assert end in days
    if view == "week":
        assert days[0].weekday() == 0
    elif view == "day":
        assert days == [start]
    else:
        assert start in days
        assert len(days) % 7 == 0


def test_batch_schedule_creates_audited_rows_and_warns_when_order_is_exceeded() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor, _, shift, order_id = _fixtures(db)
        start = date(2026, 11, 10)
        rows, warning = create_schedule_batch(
            db,
            _batch(shift.id, order_id, dates=[start, start + timedelta(days=1)], quantity=60),
            actor.id,
        )
        audits = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.table_name == "schedules",
                    AuditLog.record_id.in_([row.id for row in rows]),
                )
            )
        )

        assert len(rows) == 2
        assert len(audits) == 2
        assert all(audit.actor_id == actor.id and audit.old_values is None for audit in audits)
        assert warning
        assert all(row.planned_quantity == 60 for row in rows)
    finally:
        db.rollback()
        db.close()


def test_schedule_batch_rejects_duplicate_days_and_nonpositive_quantity() -> None:
    with pytest.raises(ValidationError, match="trùng ngày"):
        _batch(1, 1, dates=[date(2026, 11, 10)] * 2, quantity=5)
    with pytest.raises(ValidationError):
        _batch(1, 1, dates=[date(2026, 11, 10)], quantity=0)
    with pytest.raises(ValidationError):
        _batch(1, 1, dates=[], quantity=5)


def test_schedule_requires_existing_order_and_active_shift() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor, _, shift, order_id = _fixtures(db)
        with pytest.raises(ScheduleManagementError, match="kíp đang"):
            create_schedule_batch(
                db,
                _batch(shift.id + 100000, order_id, dates=[date(2026, 11, 10)], quantity=5),
                actor.id,
            )
        with pytest.raises(ScheduleManagementError, match="PO đang"):
            create_schedule_batch(
                db,
                _batch(shift.id, order_id + 100000, dates=[date(2026, 11, 10)], quantity=5),
                actor.id,
            )
    finally:
        db.rollback()
        db.close()


def test_update_schedule_checks_version_warns_and_audits() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor, _, shift, order_id = _fixtures(db)
        rows, _ = create_schedule_batch(
            db,
            _batch(shift.id, order_id, dates=[date(2026, 11, 10)], quantity=40),
            actor.id,
        )
        row = rows[0]
        updated, warning = update_schedule(
            db,
            row.id,
            ScheduleUpdate(
                production_date=date(2026, 11, 11),
                shift_id=shift.id,
                order_id=order_id,
                planned_quantity=110,
                version=row.version,
            ),
            actor.id,
        )
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.table_name == "schedules", AuditLog.record_id == row.id)
            .order_by(AuditLog.id.desc())
        )

        assert updated.version == 2
        assert warning
        assert audit.old_values["planned_quantity"] == 40
        assert audit.new_values["production_date"] == "2026-11-11"
        with pytest.raises(ConcurrentScheduleChange, match="tải lại"):
            update_schedule(
                db,
                row.id,
                ScheduleUpdate(
                    production_date=date(2026, 11, 12),
                    shift_id=shift.id,
                    order_id=order_id,
                    planned_quantity=20,
                    version=1,
                ),
                actor.id,
            )
    finally:
        db.rollback()
        db.close()


def test_soft_delete_schedule_records_old_values_and_excludes_it_from_totals() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor, _, shift, order_id = _fixtures(db)
        rows, _ = create_schedule_batch(
            db,
            _batch(shift.id, order_id, dates=[date(2026, 11, 10)], quantity=25),
            actor.id,
        )
        deleted = soft_delete_schedule(db, rows[0].id, actor.id)
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.table_name == "schedules", AuditLog.record_id == deleted.id)
            .order_by(AuditLog.id.desc())
        )

        assert deleted.deleted_at is not None
        assert audit.action == "delete"
        assert audit.old_values["planned_quantity"] == 25
        assert (
            db.scalar(select(ProductionSchedule.id).where(ProductionSchedule.deleted_at.is_(None)))
            is None
        )
    finally:
        db.rollback()
        db.close()


def test_soft_delete_schedule_keeps_linked_undelivered_request() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor, _, shift, order_id = _fixtures(db)
        rows, _ = create_schedule_batch(
            db,
            _batch(shift.id, order_id, dates=[date(2026, 11, 10)], quantity=25),
            actor.id,
        )
        group = MachineGroup(code=f"SG-{uuid4().hex}", name="Nhóm lịch", is_active=True)
        db.add(group)
        db.flush()
        request = BlankRequest(
            req_no=f"YC-{uuid4().hex[:20]}",
            schedule_id=rows[0].id,
            blank_quantity=25,
            machine_group_id=group.id,
            status="submitted",
            created_by=actor.id,
            updated_by=actor.id,
        )
        db.add(request)
        db.flush()

        deleted = soft_delete_schedule(db, rows[0].id, actor.id)

        assert deleted.deleted_at is not None
        assert request.schedule_id == deleted.id
        assert request.deleted_at is None
    finally:
        db.rollback()
        db.close()


def test_soft_delete_schedule_is_blocked_after_blank_request_delivery() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor, _, shift, order_id = _fixtures(db)
        rows, _ = create_schedule_batch(
            db,
            _batch(shift.id, order_id, dates=[date(2026, 11, 10)], quantity=25),
            actor.id,
        )
        group = MachineGroup(code=f"SG-{uuid4().hex}", name="Nhóm lịch", is_active=True)
        db.add(group)
        db.flush()
        request = BlankRequest(
            req_no=f"YC-{uuid4().hex[:20]}",
            schedule_id=rows[0].id,
            blank_quantity=25,
            machine_group_id=group.id,
            status="delivered",
            delivered_quantity=24,
            delivered_at=datetime.now(UTC),
            delivered_by=actor.id,
            created_by=actor.id,
            updated_by=actor.id,
        )
        db.add(request)
        db.flush()

        with pytest.raises(ScheduleManagementError, match="đã có yêu cầu phôi"):
            soft_delete_schedule(db, rows[0].id, actor.id)

        assert rows[0].deleted_at is None
    finally:
        db.rollback()
        db.close()
