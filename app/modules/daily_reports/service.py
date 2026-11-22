from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.modules.assets.models import Machine, MachinePair
from app.modules.auth.models import AuditLog
from app.modules.blank_requests.models import (
    BlankRequest,
    BlankRequestOperator,
    BlankRequestPair,
)
from app.modules.daily_reports.models import (
    DailyReport,
    DailyReportLine,
    DailyReportPair,
    DowntimeEntry,
)
from app.modules.daily_reports.schemas import DailyProductionReportCreate
from app.modules.downtime.models import DowntimeReason
from app.modules.employees.models import Employee
from app.modules.orders.models import ProductionLot, ProductionOrder
from app.modules.products.models import Product
from app.modules.qc.models import LotQcInspection, QcInspection, QcPairResult
from app.modules.schedules.models import ProductionSchedule
from app.modules.shifts.models import Shift


class DailyReportError(Exception):
    """A daily report business rule rejected the change."""


class DuplicateDailyReport(DailyReportError):
    """The blank request already has a production report."""


def get_request_context(db: Session, request_number: str):
    return db.execute(
        select(BlankRequest, ProductionSchedule, ProductionOrder, Product, Shift)
        .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
        .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(Shift, Shift.id == ProductionSchedule.shift_id)
        .where(
            BlankRequest.req_no == request_number.strip(),
            BlankRequest.deleted_at.is_(None),
        )
    ).first()


def report_pairs_for_request(db: Session, request_id: int):
    links = list(
        db.execute(
            select(BlankRequestPair.machine_pair_id, BlankRequestPair.employee_id)
            .where(
                BlankRequestPair.blank_request_id == request_id,
                BlankRequestPair.deleted_at.is_(None),
            )
            .order_by(BlankRequestPair.id)
        )
    )
    legacy_workers = list(
        db.scalars(
            select(BlankRequestOperator.employee_id).where(
                BlankRequestOperator.blank_request_id == request_id,
                BlankRequestOperator.deleted_at.is_(None),
            )
        )
    )
    if len(links) == 1 and links[0][1] is None and len(legacy_workers) == 1:
        links = [(links[0][0], legacy_workers[0])]

    pair_ids = [pair_id for pair_id, _employee_id in links]
    machine_1 = aliased(Machine)
    machine_2 = aliased(Machine)
    pair_rows = list(
        db.execute(
            select(MachinePair, machine_1, machine_2)
            .join(machine_1, machine_1.id == MachinePair.machine_1_id)
            .join(machine_2, machine_2.id == MachinePair.machine_2_id)
            .where(MachinePair.id.in_(pair_ids))
        )
    )
    pair_by_id = {row[0].id: row for row in pair_rows}
    worker_ids = [employee_id for _pair_id, employee_id in links if employee_id]
    workers = list(
        db.scalars(
            select(Employee)
            .where(
                Employee.employee_type == "operator",
                (Employee.is_active.is_(True) & Employee.deleted_at.is_(None))
                | Employee.id.in_(worker_ids),
            )
            .order_by(Employee.code)
        )
    )
    worker_by_id = {worker.id: worker for worker in workers}
    assignments = [
        (pair_row, worker_by_id.get(employee_id))
        for pair_id, employee_id in links
        if (pair_row := pair_by_id.get(pair_id)) is not None
    ]
    return assignments, workers


def active_downtime_reasons(db: Session) -> list[DowntimeReason]:
    return list(
        db.scalars(
            select(DowntimeReason)
            .where(DowntimeReason.is_active.is_(True), DowntimeReason.deleted_at.is_(None))
            .order_by(DowntimeReason.code)
        )
    )


def active_shifts(db: Session) -> list[Shift]:
    return list(
        db.scalars(
            select(Shift)
            .where(Shift.is_active.is_(True), Shift.deleted_at.is_(None))
            .order_by(Shift.start_time)
        )
    )


def list_daily_reports(db: Session):
    return list(
        db.execute(
            select(DailyReport, BlankRequest, ProductionSchedule, ProductionOrder)
            .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
            .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
            .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
            .where(DailyReport.deleted_at.is_(None))
            .order_by(DailyReport.report_date.desc(), DailyReport.created_at.desc())
        )
    )


def list_daily_report_requests(
    db: Session,
    production_date: date,
    *,
    shift_id: int | None = None,
    po_query: str = "",
):
    query = (
        select(BlankRequest, ProductionSchedule, ProductionOrder, Product, Shift, DailyReport)
        .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
        .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(Shift, Shift.id == ProductionSchedule.shift_id)
        .outerjoin(
            DailyReport,
            (DailyReport.blank_request_id == BlankRequest.id) & DailyReport.deleted_at.is_(None),
        )
        .where(
            BlankRequest.status != "cancelled",
            BlankRequest.deleted_at.is_(None),
            ProductionSchedule.production_date == production_date,
            ProductionSchedule.deleted_at.is_(None),
            ProductionOrder.deleted_at.is_(None),
        )
        .order_by(
            ProductionSchedule.production_date.desc(), Shift.start_time, ProductionOrder.po_no
        )
        .limit(150)
    )
    if shift_id is not None:
        query = query.where(ProductionSchedule.shift_id == shift_id)
    if po_query.strip():
        query = query.where(ProductionOrder.po_no.ilike(f"%{po_query.strip()}%"))
    return list(db.execute(query))


def daily_report_po_suggestions(db: Session, query_text: str) -> list[str]:
    value = query_text.strip()
    if not value:
        return []
    query = (
        select(ProductionOrder.po_no)
        .join(ProductionSchedule, ProductionSchedule.order_id == ProductionOrder.id)
        .join(BlankRequest, BlankRequest.schedule_id == ProductionSchedule.id)
        .where(
            ProductionOrder.deleted_at.is_(None),
            ProductionSchedule.deleted_at.is_(None),
            BlankRequest.deleted_at.is_(None),
            BlankRequest.status != "cancelled",
            ProductionOrder.po_no.ilike(f"%{value}%"),
        )
        .distinct()
        .order_by(ProductionOrder.po_no)
        .limit(12)
    )
    return list(db.scalars(query))


def report_shift_names(db: Session) -> dict[int, str]:
    rows = db.execute(
        select(DailyReportPair.daily_report_id, Shift.name)
        .join(Shift, Shift.id == DailyReportPair.shift_id)
        .where(DailyReportPair.deleted_at.is_(None))
        .distinct()
        .order_by(DailyReportPair.daily_report_id, Shift.name)
    )
    names: dict[int, list[str]] = {}
    for report_id, shift_name in rows:
        names.setdefault(report_id, []).append(shift_name)
    return {report_id: ", ".join(values) for report_id, values in names.items()}


def get_daily_report_edit_data(db: Session, report_id: int):
    report = db.scalar(
        select(DailyReport).where(
            DailyReport.id == report_id,
            DailyReport.deleted_at.is_(None),
        )
    )
    if report is None:
        return None
    machine_1 = aliased(Machine)
    machine_2 = aliased(Machine)
    rows = db.execute(
        select(DailyReportPair, MachinePair, machine_1, machine_2, Employee)
        .join(MachinePair, MachinePair.id == DailyReportPair.machine_pair_id)
        .join(machine_1, machine_1.id == MachinePair.machine_1_id)
        .join(machine_2, machine_2.id == MachinePair.machine_2_id)
        .join(Employee, Employee.id == DailyReportPair.employee_id)
        .where(
            DailyReportPair.daily_report_id == report.id,
            DailyReportPair.deleted_at.is_(None),
        )
        .order_by(DailyReportPair.id)
    )
    assignments = []
    values = {}
    for report_pair, machine_pair, first_machine, second_machine, employee in rows:
        line = db.scalar(
            select(DailyReportLine).where(
                DailyReportLine.daily_report_pair_id == report_pair.id,
                DailyReportLine.deleted_at.is_(None),
            )
        )
        downtime = list(
            db.scalars(
                select(DowntimeEntry).where(
                    DowntimeEntry.daily_report_pair_id == report_pair.id,
                    DowntimeEntry.deleted_at.is_(None),
                )
            )
        )
        assignments.append(((machine_pair, first_machine, second_machine), employee))
        values[machine_pair.id] = {
            "report_pair": report_pair,
            "quantity": line.quantity_produced if line else 0,
            "downtime_recorded": report_pair.downtime_recorded,
            "downtime": downtime,
        }
    return report, assignments, values


def create_daily_production_report(
    db: Session, data: DailyProductionReportCreate, actor_id: int
) -> tuple[DailyReport, list[str]]:
    _lock_request_order(db, data.blank_request_id)
    request_row = db.scalar(
        select(BlankRequest)
        .where(
            BlankRequest.id == data.blank_request_id,
            BlankRequest.deleted_at.is_(None),
            BlankRequest.status != "cancelled",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if request_row is None:
        raise DailyReportError("Không tìm thấy yêu cầu phôi đang sử dụng.")
    if db.scalar(
        select(DailyReport.id).where(
            DailyReport.blank_request_id == request_row.id,
            DailyReport.deleted_at.is_(None),
        )
    ):
        raise DuplicateDailyReport("Yêu cầu này đã có báo cáo sản lượng.")

    schedule = db.get(ProductionSchedule, request_row.schedule_id)
    if schedule is None:
        raise DailyReportError("Yêu cầu phôi không còn dòng lịch liên kết.")
    order = db.get(ProductionOrder, schedule.order_id)
    if order is None:
        raise DailyReportError("Không tìm thấy PO của yêu cầu phôi.")
    if order.process_type == "BAVIA_ONLY":
        raise DailyReportError("PO chỉ Bavia không được nhập báo cáo sản xuất CNC.")

    original_pair_assignments = list(
        db.execute(
            select(BlankRequestPair.machine_pair_id, BlankRequestPair.employee_id)
            .where(
                BlankRequestPair.blank_request_id == request_row.id,
                BlankRequestPair.deleted_at.is_(None),
            )
            .order_by(BlankRequestPair.id)
        )
    )
    current_pair_count = db.scalar(
        select(func.count(BlankRequestPair.id)).where(
            BlankRequestPair.blank_request_id == request_row.id,
            BlankRequestPair.deleted_at.is_(None),
        )
    )
    if current_pair_count != len(original_pair_assignments):
        raise DailyReportError(
            "Cấu hình cặp máy của yêu cầu phôi không nhất quán; cần kiểm tra lại."
        )
    submitted_pairs = [pair for shift in data.shifts for pair in shift.pairs]
    existing_pair_ids = {pair_id for pair_id, _employee_id in original_pair_assignments}
    source_pair_ids = {pair.source_machine_pair_id for pair in submitted_pairs}
    if source_pair_ids != existing_pair_ids:
        raise DailyReportError(
            "Không được thêm hoặc bỏ các dòng máy đã khai báo trong yêu cầu phôi."
        )
    if any(pair.machine_pair_id != pair.source_machine_pair_id for pair in submitted_pairs):
        raise DailyReportError("Báo cáo hiện chỉ nhận cặp máy đã khai báo trên yêu cầu phôi.")

    operator_ids = {pair.employee_id for pair in submitted_pairs}
    active_operator_ids = set(
        db.scalars(
            select(Employee.id).where(
                Employee.id.in_(operator_ids),
                Employee.employee_type == "operator",
                Employee.is_active.is_(True),
                Employee.deleted_at.is_(None),
            )
        )
    )
    if operator_ids != active_operator_ids:
        raise DailyReportError("Chọn người làm đang hoạt động cho từng cặp máy.")

    reason_ids = {entry.reason_id for pair in submitted_pairs for entry in pair.downtime}
    if reason_ids:
        valid_reason_ids = set(
            db.scalars(
                select(DowntimeReason.id).where(
                    DowntimeReason.id.in_(reason_ids),
                    DowntimeReason.is_active.is_(True),
                    DowntimeReason.deleted_at.is_(None),
                )
            )
        )
        if reason_ids != valid_reason_ids:
            raise DailyReportError("Chỉ chọn lý do dừng máy đang sử dụng.")

    shift_ids = {shift_input.shift_id for shift_input in data.shifts}
    shifts = {
        shift.id: shift
        for shift in db.scalars(
            select(Shift).where(
                Shift.id.in_(shift_ids), Shift.is_active.is_(True), Shift.deleted_at.is_(None)
            )
        )
    }
    if shift_ids != set(shifts):
        raise DailyReportError("Chỉ chọn kíp đang hoạt động.")

    original_assignment_by_pair = {
        pair_id: employee_id for pair_id, employee_id in original_pair_assignments
    }
    shift_minutes_by_id: dict[int, int] = {}
    for shift_input in data.shifts:
        shift = shifts[shift_input.shift_id]
        shift_start = datetime.combine(data.report_date, shift.start_time)
        shift_end = datetime.combine(data.report_date, shift.end_time)
        if shift.crosses_midnight:
            shift_end += timedelta(days=1)
        shift_minutes = max(
            int((shift_end - shift_start).total_seconds() // 60) - shift.planned_break_minutes,
            1,
        )
        shift_minutes_by_id[shift.id] = shift_minutes
        for pair_input in shift_input.pairs:
            downtime_minutes = sum(entry.minutes for entry in pair_input.downtime)
            if downtime_minutes > shift_minutes:
                raise DailyReportError(f"Tổng phút dừng vượt thời lượng ca/kíp {shift.name}.")

    now = datetime.now(UTC)
    report = DailyReport(
        blank_request_id=request_row.id,
        report_date=data.report_date,
        status="confirmed",
        created_at=now,
        updated_at=now,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(report)
    db.flush()
    warnings: list[str] = []
    if data.report_date != schedule.production_date:
        warnings.append("Ngày báo cáo lệch ngày trên lịch; hãy kiểm tra lại biểu giấy.")
    if schedule.shift_id not in shift_ids:
        warnings.append("Ca/kíp báo cáo lệch ca/kíp lịch; hãy kiểm tra lại biểu giấy.")
    product = db.get(Product, order.product_id)
    cycle_time = product.cycle_time_seconds
    for shift_input in data.shifts:
        for pair_data in shift_input.pairs:
            original_pair_id = pair_data.source_machine_pair_id
            original_employee_id = original_assignment_by_pair[original_pair_id]
            assignment_changed = pair_data.employee_id != original_employee_id
            pair = DailyReportPair(
                daily_report_id=report.id,
                shift_id=shift_input.shift_id,
                machine_pair_id=pair_data.machine_pair_id,
                employee_id=pair_data.employee_id,
                planned_minutes=shift_minutes_by_id[shift_input.shift_id],
                downtime_recorded=pair_data.downtime_recorded,
                created_at=now,
                updated_at=now,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(pair)
            db.flush()
            line = DailyReportLine(
                daily_report_pair_id=pair.id,
                order_id=order.id,
                quantity_produced=pair_data.quantity_produced,
                cycle_time_snapshot_seconds=cycle_time,
                created_at=now,
                updated_at=now,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(line)
            db.flush()
            _audit(
                db,
                actor_id,
                "daily_report_lines",
                line.id,
                None,
                {
                    "daily_report_pair_id": pair.id,
                    "order_id": order.id,
                    "quantity_produced": pair_data.quantity_produced,
                },
                "Ghi tổng sản lượng của cặp máy trong kíp",
            )
            for downtime_data in pair_data.downtime:
                entry = DowntimeEntry(
                    daily_report_pair_id=pair.id,
                    downtime_reason_id=downtime_data.reason_id,
                    minutes=downtime_data.minutes,
                    created_at=now,
                    updated_at=now,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                db.add(entry)
                db.flush()
                _audit(
                    db,
                    actor_id,
                    "downtime_entries",
                    entry.id,
                    None,
                    {
                        "daily_report_pair_id": pair.id,
                        "downtime_reason_id": downtime_data.reason_id,
                        "minutes": downtime_data.minutes,
                    },
                    "Ghi phút dừng máy từ biểu giấy",
                )
            _audit(
                db,
                actor_id,
                "daily_report_pairs",
                pair.id,
                None,
                {
                    "daily_report_id": report.id,
                    "shift_id": pair.shift_id,
                    "machine_pair_id": pair.machine_pair_id,
                    "employee_id": pair.employee_id,
                    "planned_minutes_from_shift": pair.planned_minutes,
                    "downtime_recorded": pair.downtime_recorded,
                    "request_assignment": {
                        "machine_pair_id": original_pair_id,
                        "employee_id": original_employee_id,
                    },
                },
                "Điều chỉnh theo biểu giấy"
                if assignment_changed
                else "Ghi nhận cặp máy trong báo cáo sản lượng",
            )
            produced = pair_data.quantity_produced
            down_minutes = sum(entry.minutes for entry in pair_data.downtime)
            available_minutes = shift_minutes_by_id[shift_input.shift_id]
            run_seconds = (available_minutes - down_minutes) * 60
            ideal_seconds = float(cycle_time) * produced
            if run_seconds > 0 and ideal_seconds > run_seconds:
                warnings.append(
                    f"Hiệu suất thời gian của cặp máy {pair.machine_pair_id} vượt 100%; "
                    "hãy rà soát số liệu."
                )

    _audit(
        db,
        actor_id,
        "daily_reports",
        report.id,
        None,
        {
            "blank_request_id": report.blank_request_id,
            "report_date": report.report_date.isoformat(),
            "shifts": [shift.shift_id for shift in data.shifts],
            "status": report.status,
        },
        "Xác nhận báo cáo ngày sản xuất",
    )
    from app.modules.orders.lifecycle import OrderLifecycleError, refresh_order_lifecycle

    try:
        refresh_order_lifecycle(db, order.id, actor_id)
    except OrderLifecycleError as exc:
        raise DailyReportError(str(exc)) from exc
    return report, warnings


def update_daily_production_report(
    db: Session,
    report_id: int,
    data: DailyProductionReportCreate,
    expected_version: int,
    actor_id: int,
) -> tuple[DailyReport, list[str]]:
    request_id = db.scalar(
        select(DailyReport.blank_request_id).where(
            DailyReport.id == report_id, DailyReport.deleted_at.is_(None)
        )
    )
    if request_id is None:
        raise DailyReportError("Không tìm thấy báo cáo cần sửa.")
    _lock_request_order(db, request_id)
    report = db.scalar(
        select(DailyReport)
        .where(DailyReport.id == report_id, DailyReport.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if report is None:
        raise DailyReportError("Không tìm thấy báo cáo cần sửa.")
    if report.version != expected_version:
        raise DailyReportError("Báo cáo đã được sửa ở nơi khác. Tải lại trước khi sửa tiếp.")
    if report.blank_request_id != data.blank_request_id:
        raise DailyReportError("Không thể chuyển báo cáo sang yêu cầu phôi khác.")

    request_row = db.scalar(
        select(BlankRequest)
        .where(
            BlankRequest.id == report.blank_request_id,
            BlankRequest.deleted_at.is_(None),
            BlankRequest.status != "cancelled",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if request_row is None:
        raise DailyReportError("Yêu cầu phôi không còn được sử dụng.")
    schedule = db.get(ProductionSchedule, request_row.schedule_id)
    order = (
        db.scalar(
            select(ProductionOrder)
            .where(
                ProductionOrder.id == schedule.order_id,
                ProductionOrder.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if schedule
        else None
    )
    if schedule is None or order is None:
        raise DailyReportError("Không tìm thấy lịch hoặc PO liên kết với báo cáo.")

    request_pairs = list(
        db.execute(
            select(BlankRequestPair.machine_pair_id, BlankRequestPair.employee_id).where(
                BlankRequestPair.blank_request_id == request_row.id,
                BlankRequestPair.deleted_at.is_(None),
            )
        )
    )
    submitted_pairs = [pair for shift in data.shifts for pair in shift.pairs]
    request_pair_ids = {pair_id for pair_id, _employee_id in request_pairs}
    if {pair.source_machine_pair_id for pair in submitted_pairs} != request_pair_ids:
        raise DailyReportError("Không được thêm hoặc bỏ cặp máy đã khai báo trong yêu cầu phôi.")
    if any(pair.machine_pair_id != pair.source_machine_pair_id for pair in submitted_pairs):
        raise DailyReportError("Báo cáo hiện chỉ nhận cặp máy đã khai báo trên yêu cầu phôi.")

    lot_qc_quantity = int(
        db.scalar(
            select(func.coalesce(func.sum(LotQcInspection.quantity_in), 0))
            .join(ProductionLot, ProductionLot.id == LotQcInspection.production_lot_id)
            .where(
                ProductionLot.order_id == order.id,
                ProductionLot.deleted_at.is_(None),
                LotQcInspection.deleted_at.is_(None),
            )
        )
        or 0
    )
    other_production_quantity = int(
        db.scalar(
            select(func.coalesce(func.sum(DailyReportLine.quantity_produced), 0))
            .join(DailyReportPair, DailyReportPair.id == DailyReportLine.daily_report_pair_id)
            .join(DailyReport, DailyReport.id == DailyReportPair.daily_report_id)
            .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
            .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
            .where(
                ProductionSchedule.order_id == order.id,
                DailyReport.id != report.id,
                DailyReport.status == "confirmed",
                DailyReport.deleted_at.is_(None),
                DailyReportPair.deleted_at.is_(None),
                DailyReportLine.deleted_at.is_(None),
                BlankRequest.deleted_at.is_(None),
                ProductionSchedule.deleted_at.is_(None),
            )
        )
        or 0
    )
    new_report_quantity = sum(pair.quantity_produced for pair in submitted_pairs)
    if lot_qc_quantity > other_production_quantity + new_report_quantity:
        raise DailyReportError(
            "Không thể giảm sản lượng xuống thấp hơn số lượng đã QC theo lô "
            f"({lot_qc_quantity} con)."
        )

    old_pairs = list(
        db.scalars(
            select(DailyReportPair).where(
                DailyReportPair.daily_report_id == report.id,
                DailyReportPair.deleted_at.is_(None),
            )
        )
    )
    old_pair_by_machine = {pair.machine_pair_id: pair for pair in old_pairs}
    if set(old_pair_by_machine) != request_pair_ids:
        raise DailyReportError(
            "Dòng máy của báo cáo không khớp yêu cầu phôi; không thể sửa an toàn."
        )
    qc_results_by_pair = {
        result.daily_report_pair_id: result
        for result in db.scalars(
            select(QcPairResult)
            .join(QcInspection, QcInspection.id == QcPairResult.qc_inspection_id)
            .where(
                QcInspection.daily_report_id == report.id,
                QcInspection.deleted_at.is_(None),
                QcPairResult.daily_report_pair_id.in_([pair.id for pair in old_pairs]),
                QcPairResult.deleted_at.is_(None),
            )
        )
    }
    qc_inspection = db.scalar(
        select(QcInspection).where(
            QcInspection.daily_report_id == report.id,
            QcInspection.deleted_at.is_(None),
        )
    )
    qc_quantity_changed = False
    submitted_quantity_by_machine = {
        item.machine_pair_id: item.quantity_produced for item in submitted_pairs
    }
    for pair in old_pairs:
        qc_result = qc_results_by_pair.get(pair.id)
        if qc_result and qc_result.ng_scrap + qc_result.ng_repair > (
            submitted_quantity_by_machine.get(pair.machine_pair_id, 0)
        ):
            raise DailyReportError(
                "Sản lượng mới thấp hơn tổng NG đã nhập QC; hãy sửa số NG trước."
            )
    allowed_existing_employee_ids = {pair.employee_id for pair in old_pairs}
    employee_ids = {pair.employee_id for pair in submitted_pairs}
    valid_employee_ids = set(
        db.scalars(
            select(Employee.id).where(
                Employee.id.in_(employee_ids),
                Employee.employee_type == "operator",
                Employee.deleted_at.is_(None),
                (Employee.is_active.is_(True) | Employee.id.in_(allowed_existing_employee_ids)),
            )
        )
    )
    if employee_ids != valid_employee_ids:
        raise DailyReportError("Chọn người làm hợp lệ cho từng cặp máy.")

    old_downtime = {
        pair.id: list(
            db.scalars(
                select(DowntimeEntry).where(
                    DowntimeEntry.daily_report_pair_id == pair.id,
                    DowntimeEntry.deleted_at.is_(None),
                )
            )
        )
        for pair in old_pairs
    }
    old_reason_ids = {
        entry.downtime_reason_id for entries in old_downtime.values() for entry in entries
    }
    reason_ids = {entry.reason_id for pair in submitted_pairs for entry in pair.downtime}
    valid_reason_ids = (
        set(
            db.scalars(
                select(DowntimeReason.id).where(
                    DowntimeReason.id.in_(reason_ids),
                    DowntimeReason.deleted_at.is_(None),
                    (DowntimeReason.is_active.is_(True) | DowntimeReason.id.in_(old_reason_ids)),
                )
            )
        )
        if reason_ids
        else set()
    )
    if reason_ids != valid_reason_ids:
        raise DailyReportError("Chỉ chọn lý do dừng máy đang hoạt động.")

    shift_ids = {shift.shift_id for shift in data.shifts}
    shifts = {
        shift.id: shift
        for shift in db.scalars(
            select(Shift).where(
                Shift.id.in_(shift_ids),
                Shift.deleted_at.is_(None),
                (Shift.is_active.is_(True) | Shift.id.in_({pair.shift_id for pair in old_pairs})),
            )
        )
    }
    if shift_ids != set(shifts):
        raise DailyReportError("Chọn ca/kíp hợp lệ.")
    shift_minutes_by_id = {}
    for shift_id, shift in shifts.items():
        start = datetime.combine(data.report_date, shift.start_time)
        end = datetime.combine(data.report_date, shift.end_time)
        if shift.crosses_midnight:
            end += timedelta(days=1)
        available_minutes = max(
            int((end - start).total_seconds() // 60) - shift.planned_break_minutes, 1
        )
        shift_minutes_by_id[shift_id] = available_minutes
        if any(
            sum(item.minutes for item in pair.downtime) > available_minutes
            for pair in data.shifts[0].pairs
        ):
            raise DailyReportError(f"Tổng phút dừng vượt thời lượng ca/kíp {shift.name}.")

    now = datetime.now(UTC)
    old_snapshot = _daily_report_snapshot(db, report)
    report.report_date = data.report_date
    report.updated_at = now
    report.updated_by = actor_id
    report.version += 1
    warnings: list[str] = []
    if data.report_date != schedule.production_date:
        warnings.append("Ngày báo cáo lệch ngày trên lịch; hãy kiểm tra lại biểu giấy.")
    if schedule.shift_id not in shift_ids:
        warnings.append("Ca/kíp báo cáo lệch ca/kíp lịch; hãy kiểm tra lại biểu giấy.")

    product = db.get(Product, order.product_id)
    cycle_time = product.cycle_time_seconds
    for shift_input in data.shifts:
        for pair_data in shift_input.pairs:
            pair = old_pair_by_machine[pair_data.machine_pair_id]
            old_pair_values = {
                "shift_id": pair.shift_id,
                "employee_id": pair.employee_id,
                "planned_minutes": pair.planned_minutes,
                "downtime_recorded": pair.downtime_recorded,
            }
            pair.shift_id = shift_input.shift_id
            pair.employee_id = pair_data.employee_id
            pair.planned_minutes = shift_minutes_by_id[shift_input.shift_id]
            pair.downtime_recorded = pair_data.downtime_recorded
            pair.updated_at = now
            pair.updated_by = actor_id
            line = db.scalar(
                select(DailyReportLine).where(
                    DailyReportLine.daily_report_pair_id == pair.id,
                    DailyReportLine.deleted_at.is_(None),
                )
            )
            old_quantity = line.quantity_produced if line else None
            if line is None:
                line = DailyReportLine(
                    daily_report_pair_id=pair.id,
                    order_id=order.id,
                    quantity_produced=pair_data.quantity_produced,
                    cycle_time_snapshot_seconds=cycle_time,
                    created_at=now,
                    updated_at=now,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                db.add(line)
                db.flush()
            else:
                line.quantity_produced = pair_data.quantity_produced
                line.updated_at = now
                line.updated_by = actor_id
            qc_result = qc_results_by_pair.get(pair.id)
            if qc_result and qc_result.quantity_in != pair_data.quantity_produced:
                qc_quantity_changed = True
                old_qc_quantity = qc_result.quantity_in
                qc_result.quantity_in = pair_data.quantity_produced
                qc_result.updated_at = now
                qc_result.updated_by = actor_id
                _audit(
                    db,
                    actor_id,
                    "qc_pair_results",
                    qc_result.id,
                    {"quantity_in": old_qc_quantity},
                    {"quantity_in": pair_data.quantity_produced},
                    "Đồng bộ số lượng QC theo sản lượng đã sửa",
                    action="update",
                )
            _audit(
                db,
                actor_id,
                "daily_report_pairs",
                pair.id,
                old_pair_values,
                {
                    "shift_id": pair.shift_id,
                    "employee_id": pair.employee_id,
                    "planned_minutes": pair.planned_minutes,
                    "downtime_recorded": pair.downtime_recorded,
                },
                "Sửa báo cáo sản lượng",
                action="update",
            )
            _audit(
                db,
                actor_id,
                "daily_report_lines",
                line.id,
                {"quantity_produced": old_quantity},
                {"quantity_produced": pair_data.quantity_produced},
                "Sửa tổng sản lượng trong ca",
                action="update",
            )
            for old_entry in old_downtime[pair.id]:
                old_values = {
                    "downtime_reason_id": old_entry.downtime_reason_id,
                    "minutes": old_entry.minutes,
                }
                old_entry.deleted_at = now
                old_entry.updated_at = now
                old_entry.updated_by = actor_id
                _audit(
                    db,
                    actor_id,
                    "downtime_entries",
                    old_entry.id,
                    old_values,
                    {"deleted_at": now.isoformat()},
                    "Thay dữ liệu dừng máy khi sửa báo cáo",
                    action="update",
                )
            for downtime_data in pair_data.downtime:
                entry = DowntimeEntry(
                    daily_report_pair_id=pair.id,
                    downtime_reason_id=downtime_data.reason_id,
                    minutes=downtime_data.minutes,
                    created_at=now,
                    updated_at=now,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                db.add(entry)
                db.flush()
                _audit(
                    db,
                    actor_id,
                    "downtime_entries",
                    entry.id,
                    None,
                    {"downtime_reason_id": entry.downtime_reason_id, "minutes": entry.minutes},
                    "Ghi lý do dừng khi sửa báo cáo",
                )
    if qc_quantity_changed and qc_inspection:
        old_qc_version = qc_inspection.version
        qc_inspection.version += 1
        qc_inspection.updated_at = now
        qc_inspection.updated_by = actor_id
        _audit(
            db,
            actor_id,
            "qc_inspections",
            qc_inspection.id,
            {"version": old_qc_version},
            {"version": qc_inspection.version},
            "Cập nhật phiên bản QC do sản lượng thay đổi",
            action="update",
        )
    db.flush()
    new_snapshot = _daily_report_snapshot(db, report)
    _audit(
        db,
        actor_id,
        "daily_reports",
        report.id,
        old_snapshot,
        new_snapshot,
        "Sửa báo cáo sản lượng đã xác nhận",
        action="update",
    )
    from app.modules.orders.lifecycle import OrderLifecycleError, refresh_order_lifecycle

    try:
        refresh_order_lifecycle(db, order.id, actor_id)
    except OrderLifecycleError as exc:
        raise DailyReportError(str(exc)) from exc
    return report, warnings


def _lock_request_order(db: Session, request_id: int) -> None:
    order_id = db.scalar(
        select(ProductionSchedule.order_id)
        .join(BlankRequest, BlankRequest.schedule_id == ProductionSchedule.id)
        .where(BlankRequest.id == request_id, BlankRequest.deleted_at.is_(None))
    )
    if order_id is None:
        raise DailyReportError("Không tìm thấy PO của yêu cầu phôi.")
    db.scalar(select(ProductionOrder).where(ProductionOrder.id == order_id).with_for_update())


def _daily_report_snapshot(db: Session, report: DailyReport) -> dict[str, object]:
    pairs = list(
        db.scalars(
            select(DailyReportPair).where(
                DailyReportPair.daily_report_id == report.id,
                DailyReportPair.deleted_at.is_(None),
            )
        )
    )
    details = []
    for pair in pairs:
        line = db.scalar(
            select(DailyReportLine).where(
                DailyReportLine.daily_report_pair_id == pair.id,
                DailyReportLine.deleted_at.is_(None),
            )
        )
        downtime = list(
            db.scalars(
                select(DowntimeEntry).where(
                    DowntimeEntry.daily_report_pair_id == pair.id,
                    DowntimeEntry.deleted_at.is_(None),
                )
            )
        )
        details.append(
            {
                "shift_id": pair.shift_id,
                "machine_pair_id": pair.machine_pair_id,
                "employee_id": pair.employee_id,
                "quantity_produced": line.quantity_produced if line else 0,
                "downtime_recorded": pair.downtime_recorded,
                "downtime": [
                    {"reason_id": entry.downtime_reason_id, "minutes": entry.minutes}
                    for entry in downtime
                ],
            }
        )
    return {
        "report_date": report.report_date.isoformat(),
        "status": report.status,
        "version": report.version,
        "pairs": details,
    }


def _audit(
    db: Session,
    actor_id: int,
    table_name: str,
    record_id: int,
    old_values: dict[str, object] | None,
    new_values: dict[str, object],
    reason: str,
    *,
    action: str = "create",
) -> None:
    db.add(
        AuditLog(
            table_name=table_name,
            record_id=record_id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            actor_id=actor_id,
        )
    )
