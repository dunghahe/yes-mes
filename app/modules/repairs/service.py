from datetime import UTC, datetime

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.blank_requests.models import BlankRequest
from app.modules.daily_reports.models import BaviaReport, DailyReport, DailyReportPair
from app.modules.employees.models import Employee
from app.modules.orders.models import ProductionLot, ProductionOrder
from app.modules.qc.models import (
    BaviaQcInspection,
    LotQcInspection,
    QcInspection,
    QcPairResult,
)
from app.modules.repairs.models import RepairJob, RepairQcRecheck
from app.modules.repairs.schemas import RepairJobCreate, RepairRecheckCreate
from app.modules.schedules.models import ProductionSchedule
from app.modules.shifts.models import Shift


class RepairWorkflowError(ValueError):
    pass


def repair_balances(
    db: Session, order_id: int, stage: str, production_lot_id: int | None = None
) -> dict[str, int]:
    if stage == "QC":
        lot_qc_filters = [
            ProductionLot.order_id == order_id,
            LotQcInspection.deleted_at.is_(None),
            ProductionLot.deleted_at.is_(None),
        ]
        if production_lot_id is not None:
            lot_qc_filters.append(ProductionLot.id == production_lot_id)
        lot_qc_query = (
            select(func.coalesce(func.sum(LotQcInspection.ng_repair), 0))
            .join(ProductionLot, ProductionLot.id == LotQcInspection.production_lot_id)
            .where(*lot_qc_filters)
        )
        lot_qc_total = int(db.scalar(lot_qc_query) or 0)
        lot_qc_exists_filters = [
            ProductionLot.order_id == order_id,
            LotQcInspection.deleted_at.is_(None),
            ProductionLot.deleted_at.is_(None),
        ]
        if production_lot_id is not None:
            lot_qc_exists_filters.append(ProductionLot.id == production_lot_id)
        has_lot_qc = (
            db.scalar(
                select(LotQcInspection.id)
                .join(ProductionLot, ProductionLot.id == LotQcInspection.production_lot_id)
                .where(*lot_qc_exists_filters)
                .limit(1)
            )
            is not None
        )
        if has_lot_qc or production_lot_id is not None:
            initial_ng = lot_qc_total
        else:
            initial_ng = db.scalar(
                select(func.coalesce(func.sum(QcPairResult.ng_repair), 0))
                .join(QcInspection, QcInspection.id == QcPairResult.qc_inspection_id)
                .join(DailyReportPair, DailyReportPair.id == QcPairResult.daily_report_pair_id)
                .join(DailyReport, DailyReport.id == QcInspection.daily_report_id)
                .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
                .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
                .where(
                    ProductionSchedule.order_id == order_id,
                    QcInspection.pair_section_saved.is_(True),
                    QcInspection.deleted_at.is_(None),
                    QcPairResult.deleted_at.is_(None),
                    DailyReportPair.deleted_at.is_(None),
                    DailyReport.deleted_at.is_(None),
                    BlankRequest.deleted_at.is_(None),
                    ProductionSchedule.deleted_at.is_(None),
                )
            )
    elif stage == "QC_BAVIA":
        initial_ng = db.scalar(
            select(func.coalesce(func.sum(BaviaQcInspection.ng_repair), 0))
            .join(BaviaReport, BaviaReport.id == BaviaQcInspection.bavia_report_id)
            .where(
                BaviaReport.order_id == order_id,
                BaviaQcInspection.deleted_at.is_(None),
                BaviaReport.deleted_at.is_(None),
            )
        )
    else:
        raise RepairWorkflowError("Chọn đúng công đoạn QC hoặc QC Bavia.")

    recheck_query = select(func.coalesce(func.sum(RepairQcRecheck.ng_repair), 0)).where(
        RepairQcRecheck.order_id == order_id,
        RepairQcRecheck.stage == stage,
        RepairQcRecheck.deleted_at.is_(None),
    )
    dispatched_query = select(func.coalesce(func.sum(RepairJob.quantity_repaired), 0)).where(
        RepairJob.order_id == order_id,
        RepairJob.stage == stage,
        RepairJob.deleted_at.is_(None),
    )
    rechecked_query = select(func.coalesce(func.sum(RepairQcRecheck.quantity_in), 0)).where(
        RepairQcRecheck.order_id == order_id,
        RepairQcRecheck.stage == stage,
        RepairQcRecheck.deleted_at.is_(None),
    )
    if production_lot_id is not None:
        recheck_query = recheck_query.where(RepairQcRecheck.production_lot_id == production_lot_id)
        dispatched_query = dispatched_query.where(RepairJob.production_lot_id == production_lot_id)
        rechecked_query = rechecked_query.where(
            RepairQcRecheck.production_lot_id == production_lot_id
        )
    recheck_ng = db.scalar(recheck_query)
    dispatched = db.scalar(dispatched_query)
    rechecked = db.scalar(rechecked_query)
    generated = int(initial_ng or 0) + int(recheck_ng or 0)
    dispatched = int(dispatched or 0)
    rechecked = int(rechecked or 0)
    return {
        "repair_waiting": generated - dispatched,
        "repaired_waiting_qc": dispatched - rechecked,
        "repair_generated": generated,
        "repaired_total": dispatched,
        "rechecked_total": rechecked,
    }


def lot_repair_balances(db: Session) -> list[dict[str, object]]:
    lots = list(
        db.execute(
            select(ProductionLot, ProductionOrder)
            .join(ProductionOrder, ProductionOrder.id == ProductionLot.order_id)
            .where(
                ProductionLot.deleted_at.is_(None),
                ProductionOrder.deleted_at.is_(None),
                ProductionOrder.process_type != "BAVIA_ONLY",
                ProductionOrder.status != "cancelled",
            )
            .order_by(ProductionOrder.po_no, ProductionLot.lot_number)
        )
    )
    rows = []
    for lot, order in lots:
        balance = repair_balances(db, order.id, "QC", production_lot_id=lot.id)
        if balance["repair_waiting"] > 0:
            rows.append({"lot": lot, "order": order, **balance})
    return rows


def repair_job_recheck_balances(
    db: Session, *, stage: str = "QC", order_id: int | None = None
) -> list[dict[str, object]]:
    query = (
        select(RepairJob, ProductionOrder, Employee)
        .join(ProductionOrder, ProductionOrder.id == RepairJob.order_id)
        .join(Employee, Employee.id == RepairJob.repair_employee_id)
        .where(
            RepairJob.stage == stage,
            RepairJob.deleted_at.is_(None),
            ProductionOrder.deleted_at.is_(None),
        )
        .order_by(RepairJob.repair_date, RepairJob.id)
    )
    if order_id is not None:
        query = query.where(RepairJob.order_id == order_id)
    rows = list(db.execute(query))
    if not rows:
        return []

    job_ids = [row[0].id for row in rows]
    linked_rechecks = dict(
        db.execute(
            select(RepairQcRecheck.repair_job_id, func.sum(RepairQcRecheck.quantity_in))
            .where(
                RepairQcRecheck.repair_job_id.in_(job_ids),
                RepairQcRecheck.deleted_at.is_(None),
            )
            .group_by(RepairQcRecheck.repair_job_id)
        ).all()
    )
    # Preserve older PO-level QC returns that predate repair slip linking.
    legacy_by_order: dict[int, int] = {}
    order_ids = {row[0].order_id for row in rows}
    for legacy_order_id, quantity in db.execute(
        select(RepairQcRecheck.order_id, func.sum(RepairQcRecheck.quantity_in))
        .where(
            RepairQcRecheck.repair_job_id.is_(None),
            RepairQcRecheck.stage == stage,
            RepairQcRecheck.order_id.in_(order_ids),
            RepairQcRecheck.deleted_at.is_(None),
        )
        .group_by(RepairQcRecheck.order_id)
    ):
        legacy_by_order[legacy_order_id] = int(quantity or 0)

    remaining_legacy = dict(legacy_by_order)
    result = []
    for job, order, employee in rows:
        linked_quantity = int(linked_rechecks.get(job.id, 0) or 0)
        available_after_linked = max(job.quantity_repaired - linked_quantity, 0)
        legacy_quantity = min(remaining_legacy.get(job.order_id, 0), available_after_linked)
        remaining_legacy[job.order_id] = remaining_legacy.get(job.order_id, 0) - legacy_quantity
        result.append(
            {
                "repair_job": job,
                "order": order,
                "employee": employee,
                "quantity_rechecked": linked_quantity + legacy_quantity,
                "quantity_waiting_qc": available_after_linked - legacy_quantity,
            }
        )
    return result


def list_repair_queue(db: Session) -> list[dict[str, object]]:
    orders = list(
        db.scalars(
            select(ProductionOrder)
            .where(ProductionOrder.deleted_at.is_(None))
            .order_by(ProductionOrder.po_no)
        )
    )
    result = []
    for order in orders:
        for stage in ("QC", "QC_BAVIA"):
            balance = repair_balances(db, order.id, stage)
            if balance["repair_waiting"] or balance["repaired_waiting_qc"]:
                result.append(
                    {
                        "order_id": order.id,
                        "po_no": order.po_no,
                        "stage": stage,
                        **balance,
                    }
                )
    return result


def create_repair_job(db: Session, data: RepairJobCreate, actor_id: int) -> RepairJob:
    order = db.scalar(
        select(ProductionOrder)
        .where(ProductionOrder.id == data.order_id, ProductionOrder.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is None or order.status == "cancelled":
        raise RepairWorkflowError("Không tìm thấy PO đang hoạt động.")
    lot = None
    if data.production_lot_id is not None:
        lot = db.scalar(
            select(ProductionLot)
            .where(
                ProductionLot.id == data.production_lot_id,
                ProductionLot.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if lot is None:
            raise RepairWorkflowError("Không tìm thấy lô đang hoạt động.")
        if lot.order_id != data.order_id:
            raise RepairWorkflowError("Lô không thuộc PO đã chọn.")
    _validate_order_stage(order.process_type, data.stage)
    employee = db.scalar(
        select(Employee).where(
            Employee.id == data.repair_employee_id,
            Employee.is_active.is_(True),
            Employee.deleted_at.is_(None),
        )
    )
    if employee is None:
        raise RepairWorkflowError("Chỉ chọn nhân viên đang hoạt động.")
    balances = repair_balances(db, order.id, data.stage, production_lot_id=data.production_lot_id)
    if data.quantity_repaired > balances["repair_waiting"]:
        raise RepairWorkflowError(
            f"Số lượng mang đi sửa vượt hàng chờ sửa ({balances['repair_waiting']})."
        )
    now = datetime.now(UTC)
    job_id = int(
        db.execute(text("SELECT nextval(pg_get_serial_sequence('repair_jobs', 'id'))")).scalar_one()
    )
    row = RepairJob(
        id=job_id,
        repair_code=f"SR-{job_id}",
        production_lot_id=lot.id,
        order_id=order.id,
        stage=data.stage,
        repair_employee_id=employee.id,
        repair_date=data.repair_date,
        quantity_repaired=data.quantity_repaired,
        note=data.note or None,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    db.add(
        AuditLog(
            table_name="repair_jobs",
            record_id=row.id,
            action="insert",
            old_values=None,
            new_values=_repair_job_values(row),
            reason="Ghi nhận hàng mang đi sửa",
            actor_id=actor_id,
        )
    )
    from app.modules.orders.lifecycle import OrderLifecycleError, refresh_order_lifecycle

    try:
        refresh_order_lifecycle(db, order.id, actor_id)
    except OrderLifecycleError as exc:
        raise RepairWorkflowError(str(exc)) from exc
    return row


def create_repair_recheck(db: Session, data: RepairRecheckCreate, actor_id: int) -> RepairQcRecheck:
    job_identity = db.execute(
        select(
            RepairJob.id,
            RepairJob.order_id,
            RepairJob.stage,
            RepairJob.production_lot_id,
        ).where(
            or_(
                RepairJob.repair_code == data.repair_code,
                RepairJob.legacy_repair_code == data.repair_code,
            ),
            RepairJob.deleted_at.is_(None),
        )
    ).first()
    if job_identity is None:
        raise RepairWorkflowError("Không tìm thấy mã phiếu sửa đang hoạt động.")
    order = db.scalar(
        select(ProductionOrder)
        .where(ProductionOrder.id == job_identity.order_id, ProductionOrder.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise RepairWorkflowError("Không tìm thấy PO đang hoạt động.")
    job = db.scalar(
        select(RepairJob)
        .where(
            RepairJob.id == job_identity.id,
            RepairJob.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None or data.repair_code not in (job.repair_code, job.legacy_repair_code):
        raise RepairWorkflowError("Không tìm thấy mã phiếu sửa đang hoạt động.")
    _validate_order_stage(order.process_type, job.stage)
    shift = db.scalar(
        select(Shift).where(
            Shift.id == data.shift_id,
            Shift.is_active.is_(True),
            Shift.deleted_at.is_(None),
        )
    )
    if shift is None:
        raise RepairWorkflowError("Chỉ chọn ca/kíp đang hoạt động.")
    employee = db.scalar(
        select(Employee).where(
            Employee.id == data.qc_employee_id,
            Employee.employee_type == "qc",
            Employee.is_active.is_(True),
            Employee.deleted_at.is_(None),
        )
    )
    if employee is None:
        raise RepairWorkflowError("Chỉ chọn nhân viên QC đang hoạt động.")
    balances = repair_job_recheck_balances(db, stage=job.stage, order_id=job.order_id)
    job_balance = next(row for row in balances if row["repair_job"].id == job.id)
    if data.quantity_in > job_balance["quantity_waiting_qc"]:
        raise RepairWorkflowError(
            "Số lượng đưa vào QC lại vượt số còn chờ QC của phiếu "
            f"{job.repair_code} ({job_balance['quantity_waiting_qc']})."
        )
    now = datetime.now(UTC)
    row = RepairQcRecheck(
        repair_job_id=job.id,
        order_id=order.id,
        stage=job.stage,
        inspected_date=data.inspected_date,
        shift_id=shift.id,
        qc_employee_id=employee.id,
        quantity_in=data.quantity_in,
        quantity_ok=data.quantity_ok,
        ng_scrap=data.ng_scrap,
        ng_repair=data.ng_repair,
        production_lot_id=job.production_lot_id,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    db.add(
        AuditLog(
            table_name="repair_qc_rechecks",
            record_id=row.id,
            action="insert",
            old_values=None,
            new_values=_recheck_values(row, job.repair_code),
            reason="Ghi nhận kết quả QC lại sau sửa",
            actor_id=actor_id,
        )
    )
    from app.modules.orders.lifecycle import OrderLifecycleError, refresh_order_lifecycle

    try:
        refresh_order_lifecycle(db, order.id, actor_id)
    except OrderLifecycleError as exc:
        raise RepairWorkflowError(str(exc)) from exc
    return row


def _repair_job_values(row: RepairJob) -> dict[str, object]:
    return {
        "repair_code": row.repair_code,
        "order_id": row.order_id,
        "production_lot_id": row.production_lot_id,
        "stage": row.stage,
        "repair_employee_id": row.repair_employee_id,
        "repair_date": row.repair_date.isoformat(),
        "quantity_repaired": row.quantity_repaired,
        "note": row.note,
    }


def _validate_order_stage(process_type: str, stage: str) -> None:
    if process_type == "SX_ONLY" and stage != "QC":
        raise RepairWorkflowError("PO chỉ sản xuất chỉ có công đoạn sửa QC sản xuất.")
    if process_type == "BAVIA_ONLY" and stage != "QC_BAVIA":
        raise RepairWorkflowError("PO chỉ Bavia chỉ có công đoạn sửa QC Bavia.")


def _recheck_values(row: RepairQcRecheck, repair_code: str) -> dict[str, object]:
    return {
        "repair_job_id": row.repair_job_id,
        "repair_code": repair_code,
        "production_lot_id": row.production_lot_id,
        "order_id": row.order_id,
        "stage": row.stage,
        "inspected_date": row.inspected_date.isoformat(),
        "shift_id": row.shift_id,
        "qc_employee_id": row.qc_employee_id,
        "quantity_in": row.quantity_in,
        "quantity_ok": row.quantity_ok,
        "ng_scrap": row.ng_scrap,
        "ng_repair": row.ng_repair,
    }
