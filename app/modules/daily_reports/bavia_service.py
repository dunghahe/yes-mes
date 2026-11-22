from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.blank_requests.models import BlankRequest
from app.modules.daily_reports.bavia_schemas import BaviaQcInput, BaviaReportInput
from app.modules.daily_reports.models import BaviaReport, DailyReport
from app.modules.employees.models import Employee
from app.modules.orders.models import ProductionOrder
from app.modules.qc.models import BaviaQcInspection, QcInspection, QcPairResult
from app.modules.qc.service import qc_inspection_is_complete
from app.modules.repairs.models import RepairQcRecheck
from app.modules.schedules.models import ProductionSchedule
from app.modules.shifts.models import Shift


class BaviaReportError(ValueError):
    pass


def save_bavia_report(
    db: Session,
    data: BaviaReportInput,
    actor_id: int,
    *,
    report_id: int | None = None,
) -> BaviaReport:
    order = db.scalar(
        select(ProductionOrder)
        .where(ProductionOrder.id == data.order_id, ProductionOrder.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise BaviaReportError("Không tìm thấy PO đang hoạt động.")
    if order.process_type == "SX_ONLY":
        raise BaviaReportError("PO chỉ sản xuất không được nhập báo cáo Bavia.")
    shift = db.scalar(
        select(Shift).where(
            Shift.id == data.shift_id, Shift.is_active.is_(True), Shift.deleted_at.is_(None)
        )
    )
    if shift is None:
        raise BaviaReportError("Chỉ chọn ca/kíp đang hoạt động.")
    employee = db.scalar(
        select(Employee).where(
            Employee.id == data.employee_id,
            Employee.employee_type == "operator",
            Employee.is_active.is_(True),
            Employee.deleted_at.is_(None),
        )
    )
    if employee is None:
        raise BaviaReportError("Chỉ chọn người làm đang hoạt động.")
    if report_id is not None:
        existing = db.scalar(
            select(BaviaReport)
            .where(
                BaviaReport.id == report_id,
                BaviaReport.order_id == order.id,
                BaviaReport.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if existing is None:
            raise BaviaReportError("Không tìm thấy báo cáo Bavia cần sửa.")
    else:
        existing = db.scalar(
            select(BaviaReport).where(
                BaviaReport.order_id == order.id,
                BaviaReport.report_date == data.report_date,
                BaviaReport.shift_id == shift.id,
                BaviaReport.employee_id == employee.id,
                BaviaReport.deleted_at.is_(None),
            )
        )
    if existing is None and data.version != 0:
        raise BaviaReportError("Báo cáo Bavia đã thay đổi. Tải lại trang trước khi lưu.")
    if existing is not None and data.version != existing.version:
        raise BaviaReportError("Báo cáo Bavia đã được cập nhật. Tải lại trang trước khi lưu.")

    existing_total = (
        db.scalar(
            select(func.coalesce(func.sum(BaviaReport.quantity_produced), 0)).where(
                BaviaReport.order_id == order.id,
                BaviaReport.deleted_at.is_(None),
            )
        )
        or 0
    )
    other_total = int(existing_total) - (existing.quantity_produced if existing else 0)
    if order.process_type == "FULL":
        first_pass_and_recheck_ok = _production_qc_ok_total(db, order.id)
        if other_total + data.quantity_produced > first_pass_and_recheck_ok:
            raise BaviaReportError(
                "Tổng sản lượng Bavia không được vượt tổng OK đã qua QC sản xuất "
                f"({first_pass_and_recheck_ok})."
            )
    elif order.process_type == "BAVIA_ONLY":
        delivered_count, known_count, issued_total = db.execute(
            select(
                func.count(BlankRequest.id),
                func.count(BlankRequest.delivered_quantity),
                func.coalesce(func.sum(BlankRequest.delivered_quantity), 0),
            )
            .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
            .where(
                ProductionSchedule.order_id == order.id,
                BlankRequest.status == "delivered",
                BlankRequest.deleted_at.is_(None),
                ProductionSchedule.deleted_at.is_(None),
            )
        ).one()
        if not delivered_count:
            raise BaviaReportError("Chỉ nhập Bavia sau khi Kho NVL đã xác nhận giao phôi.")
        if delivered_count == known_count and other_total + data.quantity_produced > issued_total:
            raise BaviaReportError(
                "Tổng sản lượng Bavia không được vượt số phôi Kho NVL đã giao "
                f"({int(issued_total)})."
            )

    now = datetime.now(UTC)
    if existing is None:
        existing = BaviaReport(
            order_id=order.id,
            report_date=data.report_date,
            shift_id=shift.id,
            employee_id=employee.id,
            quantity_produced=data.quantity_produced,
            version=1,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        db.add(existing)
        db.flush()
        action, old_values = "insert", None
    else:
        old_values = _report_values(existing)
        qc = db.scalar(
            select(BaviaQcInspection).where(
                BaviaQcInspection.bavia_report_id == existing.id,
                BaviaQcInspection.deleted_at.is_(None),
            )
        )
        identity_changed = (
            existing.report_date != data.report_date
            or existing.shift_id != shift.id
            or existing.employee_id != employee.id
        )
        if qc is not None and (
            identity_changed or existing.quantity_produced != data.quantity_produced
        ):
            raise BaviaReportError("Không sửa báo cáo Bavia sau khi đã ghi nhận QC Bavia.")
        if report_id is not None and identity_changed:
            duplicate = db.scalar(
                select(BaviaReport.id).where(
                    BaviaReport.order_id == order.id,
                    BaviaReport.report_date == data.report_date,
                    BaviaReport.shift_id == shift.id,
                    BaviaReport.employee_id == employee.id,
                    BaviaReport.id != existing.id,
                    BaviaReport.deleted_at.is_(None),
                )
            )
            if duplicate is not None:
                raise BaviaReportError("Đã có báo cáo Bavia cho ngày, kíp và người làm này.")
        existing.report_date = data.report_date
        existing.shift_id = shift.id
        existing.employee_id = employee.id
        existing.quantity_produced = data.quantity_produced
        existing.version += 1
        existing.updated_at = now
        existing.updated_by = actor_id
        action = "update"
    db.add(
        AuditLog(
            table_name="bavia_reports",
            record_id=existing.id,
            action=action,
            old_values=old_values,
            new_values=_report_values(existing),
            reason="Nhập/sửa báo cáo sản lượng Bavia",
            actor_id=actor_id,
        )
    )
    from app.modules.orders.lifecycle import OrderLifecycleError, refresh_order_lifecycle

    try:
        refresh_order_lifecycle(db, order.id, actor_id)
    except OrderLifecycleError as exc:
        raise BaviaReportError(str(exc)) from exc
    return existing


def list_bavia_reports(
    db: Session,
    *,
    order_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    from app.modules.qc.models import BaviaQcInspection

    query = (
        select(BaviaReport, ProductionOrder, Shift, Employee)
        .join(ProductionOrder, ProductionOrder.id == BaviaReport.order_id)
        .join(Shift, Shift.id == BaviaReport.shift_id)
        .join(Employee, Employee.id == BaviaReport.employee_id)
        .where(
            BaviaReport.deleted_at.is_(None),
            ProductionOrder.deleted_at.is_(None),
        )
    )
    if order_id:
        query = query.where(BaviaReport.order_id == order_id)
    if date_from:
        query = query.where(BaviaReport.report_date >= date_from)
    if date_to:
        query = query.where(BaviaReport.report_date <= date_to)
    result = []
    for report, order, shift, employee in db.execute(
        query.order_by(BaviaReport.report_date.desc(), ProductionOrder.po_no)
    ):
        qc = db.scalar(
            select(BaviaQcInspection).where(
                BaviaQcInspection.bavia_report_id == report.id,
                BaviaQcInspection.deleted_at.is_(None),
            )
        )
        result.append(
            {
                "id": report.id,
                "version": report.version,
                "order_id": order.id,
                "po_no": order.po_no,
                "report_date": report.report_date.isoformat(),
                "shift_id": shift.id,
                "shift": shift.name,
                "employee_id": employee.id,
                "employee_name": employee.name,
                "quantity_produced": report.quantity_produced,
                "qc": {
                    "id": qc.id,
                    "version": qc.version,
                    "inspected_date": qc.inspected_date.isoformat(),
                    "quantity_in": qc.quantity_in,
                    "ng_scrap": qc.ng_scrap,
                    "ng_repair": qc.ng_repair,
                    "qc_employee_id": qc.qc_employee_id,
                }
                if qc
                else None,
            }
        )
    return result


def save_bavia_qc(
    db: Session, bavia_report_id: int, data: BaviaQcInput, actor_id: int
) -> BaviaQcInspection:
    order_id = db.scalar(
        select(BaviaReport.order_id).where(
            BaviaReport.id == bavia_report_id,
            BaviaReport.deleted_at.is_(None),
        )
    )
    order = (
        db.scalar(
            select(ProductionOrder)
            .where(ProductionOrder.id == order_id, ProductionOrder.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if order_id
        else None
    )
    if order is None:
        raise BaviaReportError("Không tìm thấy PO đang hoạt động cho báo cáo Bavia.")
    report = db.scalar(
        select(BaviaReport)
        .where(BaviaReport.id == bavia_report_id, BaviaReport.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if report is None:
        raise BaviaReportError("Không tìm thấy báo cáo sản lượng Bavia.")
    if data.ng_scrap + data.ng_repair > report.quantity_produced:
        raise BaviaReportError(
            f"Tổng NG hủy và NG sửa vượt sản lượng Bavia ({report.quantity_produced})."
        )
    if data.shift_id != report.shift_id:
        raise BaviaReportError("Ca/kíp QC phải khớp ca/kíp của báo cáo Bavia.")
    qc_employee = db.scalar(
        select(Employee).where(
            Employee.id == data.qc_employee_id,
            Employee.employee_type == "qc",
            Employee.is_active.is_(True),
            Employee.deleted_at.is_(None),
        )
    )
    if qc_employee is None:
        raise BaviaReportError("Chỉ chọn nhân viên QC đang hoạt động.")
    existing = db.scalar(
        select(BaviaQcInspection)
        .where(
            BaviaQcInspection.bavia_report_id == report.id,
            BaviaQcInspection.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if existing is None and data.version != 0:
        raise BaviaReportError("QC Bavia đã thay đổi. Tải lại trang trước khi lưu.")
    if existing is not None and data.version != existing.version:
        raise BaviaReportError("QC Bavia đã được cập nhật. Tải lại trang trước khi lưu.")
    _ensure_bavia_repair_queue_not_reduced(
        db,
        order.id,
        existing.id if existing else None,
        data.ng_repair,
    )
    now = datetime.now(UTC)
    if existing is None:
        existing = BaviaQcInspection(
            bavia_report_id=report.id,
            inspected_date=data.inspected_date,
            shift_id=data.shift_id,
            qc_employee_id=qc_employee.id,
            quantity_in=report.quantity_produced,
            ng_scrap=data.ng_scrap,
            ng_repair=data.ng_repair,
            version=1,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        db.add(existing)
        db.flush()
        action, old_values = "insert", None
    else:
        old_values = _bavia_qc_values(existing)
        existing.inspected_date = data.inspected_date
        existing.shift_id = data.shift_id
        existing.qc_employee_id = qc_employee.id
        existing.quantity_in = report.quantity_produced
        existing.ng_scrap = data.ng_scrap
        existing.ng_repair = data.ng_repair
        existing.version += 1
        existing.updated_at = now
        existing.updated_by = actor_id
        action = "update"
    db.add(
        AuditLog(
            table_name="bavia_qc_inspections",
            record_id=existing.id,
            action=action,
            old_values=old_values,
            new_values=_bavia_qc_values(existing),
            reason="Nhập/sửa kết quả QC Bavia",
            actor_id=actor_id,
        )
    )
    from app.modules.orders.lifecycle import OrderLifecycleError, refresh_order_lifecycle

    try:
        refresh_order_lifecycle(db, report.order_id, actor_id)
    except OrderLifecycleError as exc:
        raise BaviaReportError(str(exc)) from exc
    return existing


def _ensure_bavia_repair_queue_not_reduced(
    db: Session,
    order_id: int,
    qc_id: int | None,
    submitted_ng_repair: int,
) -> None:
    from app.modules.repairs.models import RepairJob, RepairQcRecheck

    other_ng = (
        db.scalar(
            select(func.coalesce(func.sum(BaviaQcInspection.ng_repair), 0))
            .join(BaviaReport, BaviaReport.id == BaviaQcInspection.bavia_report_id)
            .where(
                BaviaReport.order_id == order_id,
                BaviaQcInspection.id != qc_id if qc_id else True,
                BaviaReport.deleted_at.is_(None),
                BaviaQcInspection.deleted_at.is_(None),
            )
        )
        or 0
    )
    recheck_ng = (
        db.scalar(
            select(func.coalesce(func.sum(RepairQcRecheck.ng_repair), 0)).where(
                RepairQcRecheck.order_id == order_id,
                RepairQcRecheck.stage == "QC_BAVIA",
                RepairQcRecheck.deleted_at.is_(None),
            )
        )
        or 0
    )
    dispatched = (
        db.scalar(
            select(func.coalesce(func.sum(RepairJob.quantity_repaired), 0)).where(
                RepairJob.order_id == order_id,
                RepairJob.stage == "QC_BAVIA",
                RepairJob.deleted_at.is_(None),
            )
        )
        or 0
    )
    if int(other_ng) + submitted_ng_repair + int(recheck_ng) < int(dispatched):
        raise BaviaReportError(
            "Không giảm NG sửa Bavia vì đã có số lượng được ghi nhận mang đi sửa."
        )


def _production_qc_ok_total(db: Session, order_id: int) -> int:
    from app.modules.orders.models import ProductionLot
    from app.modules.qc.models import LotQcInspection

    lot_totals = db.execute(
        select(
            func.count(LotQcInspection.id), func.coalesce(func.sum(LotQcInspection.quantity_ok), 0)
        )
        .join(ProductionLot, ProductionLot.id == LotQcInspection.production_lot_id)
        .where(
            ProductionLot.order_id == order_id,
            ProductionLot.deleted_at.is_(None),
            LotQcInspection.deleted_at.is_(None),
        )
    ).one()
    if lot_totals[0]:
        recheck_ok = (
            db.scalar(
                select(func.coalesce(func.sum(RepairQcRecheck.quantity_ok), 0)).where(
                    RepairQcRecheck.order_id == order_id,
                    RepairQcRecheck.stage == "QC",
                    RepairQcRecheck.deleted_at.is_(None),
                )
            )
            or 0
        )
        return int(lot_totals[1]) + int(recheck_ok)
    candidate_ids = list(
        db.scalars(
            select(QcInspection.id)
            .join(DailyReport, DailyReport.id == QcInspection.daily_report_id)
            .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
            .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
            .where(
                ProductionSchedule.order_id == order_id,
                QcInspection.deleted_at.is_(None),
                DailyReport.deleted_at.is_(None),
                BlankRequest.deleted_at.is_(None),
                ProductionSchedule.deleted_at.is_(None),
            )
        )
    )
    complete_ids = [row_id for row_id in candidate_ids if qc_inspection_is_complete(db, row_id)]
    if not complete_ids:
        return 0
    first_pass = db.execute(
        select(
            func.coalesce(func.sum(QcPairResult.quantity_in), 0),
            func.coalesce(func.sum(QcPairResult.ng_scrap + QcPairResult.ng_repair), 0),
        )
        .join(QcInspection, QcInspection.id == QcPairResult.qc_inspection_id)
        .join(DailyReport, DailyReport.id == QcInspection.daily_report_id)
        .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
        .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
        .where(
            ProductionSchedule.order_id == order_id,
            QcInspection.id.in_(complete_ids),
            QcInspection.deleted_at.is_(None),
            QcPairResult.deleted_at.is_(None),
            DailyReport.deleted_at.is_(None),
            BlankRequest.deleted_at.is_(None),
            ProductionSchedule.deleted_at.is_(None),
        )
    ).one()
    qc_input, first_qc_ng = int(first_pass[0]), int(first_pass[1])
    recheck_ok = (
        db.scalar(
            select(func.coalesce(func.sum(RepairQcRecheck.quantity_ok), 0)).where(
                RepairQcRecheck.order_id == order_id,
                RepairQcRecheck.stage == "QC",
                RepairQcRecheck.deleted_at.is_(None),
            )
        )
        or 0
    )
    return qc_input - first_qc_ng + int(recheck_ok)


def _report_values(row: BaviaReport) -> dict[str, object]:
    return {
        "order_id": row.order_id,
        "report_date": row.report_date.isoformat(),
        "shift_id": row.shift_id,
        "employee_id": row.employee_id,
        "quantity_produced": row.quantity_produced,
        "version": row.version,
    }


def _bavia_qc_values(row: BaviaQcInspection) -> dict[str, object]:
    return {
        "bavia_report_id": row.bavia_report_id,
        "inspected_date": row.inspected_date.isoformat(),
        "shift_id": row.shift_id,
        "qc_employee_id": row.qc_employee_id,
        "quantity_in": row.quantity_in,
        "ng_scrap": row.ng_scrap,
        "ng_repair": row.ng_repair,
        "version": row.version,
    }
