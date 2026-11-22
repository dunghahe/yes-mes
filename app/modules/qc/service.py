from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.modules.assets.models import Machine, MachinePair
from app.modules.auth.models import AuditLog
from app.modules.blank_requests.models import BlankRequest
from app.modules.daily_reports.models import DailyReport, DailyReportLine, DailyReportPair
from app.modules.defects.models import DefectCode
from app.modules.employees.models import Employee
from app.modules.orders.models import ProductionLot, ProductionOrder
from app.modules.products.models import Product
from app.modules.qc.models import (
    LotQcDefectLine,
    LotQcInspection,
    QcCheckStep,
    QcInspection,
    QcPairResult,
)
from app.modules.qc.schemas import (
    LotQcInput,
    QcInspectionInput,
    QcPairSectionInput,
    QcPartialSaveInput,
    QcStepsSectionInput,
)
from app.modules.schedules.models import ProductionSchedule
from app.modules.shifts.models import Shift


class QcInspectionError(Exception):
    """QC business rule rejected a change."""


STEP_LABELS = {
    1: "Đo 100% kích thước theo tiêu chuẩn",
    2: "Soi ngoại quan 100%",
    3: "Kiểm tra đúng mã sản phẩm, chất liệu",
    4: "QC kiểm tra xác suất",
}


def lot_qc_context(db: Session, lot_code: str):
    return db.execute(
        select(ProductionLot, ProductionOrder, Product)
        .join(ProductionOrder, ProductionOrder.id == ProductionLot.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .where(
            ProductionLot.lot_code == lot_code,
            ProductionLot.deleted_at.is_(None),
            ProductionOrder.deleted_at.is_(None),
            ProductionOrder.process_type != "BAVIA_ONLY",
        )
    ).first()


def list_printed_lots_for_po(db: Session, po_query: str):
    query = (
        select(ProductionLot, ProductionOrder, Product, LotQcInspection)
        .join(ProductionOrder, ProductionOrder.id == ProductionLot.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .outerjoin(
            LotQcInspection,
            (LotQcInspection.production_lot_id == ProductionLot.id)
            & LotQcInspection.deleted_at.is_(None),
        )
        .where(
            ProductionLot.deleted_at.is_(None),
            ProductionOrder.deleted_at.is_(None),
            ProductionOrder.process_type != "BAVIA_ONLY",
            or_(ProductionLot.printed_at.is_not(None), LotQcInspection.id.is_not(None)),
        )
        .order_by(ProductionOrder.po_no, ProductionLot.lot_number)
    )
    if po_query.strip():
        query = query.where(ProductionOrder.po_no.ilike(f"%{po_query.strip()}%"))
    else:
        return []
    return [
        {"lot": lot, "order": order, "product": product, "inspection": inspection}
        for lot, order, product, inspection in db.execute(query)
    ]


def qc_search_suggestions(db: Session, field: str, query_text: str) -> list[str]:
    value = query_text.strip()
    if len(value) < 1:
        return []
    lot_query = (
        select(ProductionLot.lot_code)
        .join(ProductionOrder, ProductionOrder.id == ProductionLot.order_id)
        .outerjoin(
            LotQcInspection,
            (LotQcInspection.production_lot_id == ProductionLot.id)
            & LotQcInspection.deleted_at.is_(None),
        )
        .where(
            ProductionLot.deleted_at.is_(None),
            ProductionOrder.deleted_at.is_(None),
            ProductionOrder.process_type != "BAVIA_ONLY",
            or_(ProductionLot.printed_at.is_not(None), LotQcInspection.id.is_not(None)),
            ProductionLot.lot_code.ilike(f"%{value}%"),
        )
        .order_by(ProductionLot.lot_code)
        .limit(12)
    )
    if field == "lot":
        return list(db.scalars(lot_query))
    po_query = (
        select(ProductionOrder.po_no)
        .join(ProductionLot, ProductionLot.order_id == ProductionOrder.id)
        .outerjoin(
            LotQcInspection,
            (LotQcInspection.production_lot_id == ProductionLot.id)
            & LotQcInspection.deleted_at.is_(None),
        )
        .where(
            ProductionLot.deleted_at.is_(None),
            ProductionOrder.deleted_at.is_(None),
            ProductionOrder.process_type != "BAVIA_ONLY",
            or_(ProductionLot.printed_at.is_not(None), LotQcInspection.id.is_not(None)),
            ProductionOrder.po_no.ilike(f"%{value}%"),
        )
        .distinct()
        .order_by(ProductionOrder.po_no)
        .limit(12)
    )
    return list(db.scalars(po_query))


def lot_qc_details(db: Session, inspection_id: int) -> list[dict[str, object]]:
    rows = db.execute(
        select(LotQcDefectLine, DefectCode, Machine)
        .join(DefectCode, DefectCode.id == LotQcDefectLine.defect_code_id)
        .join(Machine, Machine.id == LotQcDefectLine.machine_id)
        .where(
            LotQcDefectLine.lot_qc_inspection_id == inspection_id,
            LotQcDefectLine.deleted_at.is_(None),
        )
        .order_by(DefectCode.code, Machine.code)
    )
    return [{"line": line, "defect": defect, "machine": machine} for line, defect, machine in rows]


def save_lot_qc(db: Session, lot_code: str, data: LotQcInput, actor_id: int) -> LotQcInspection:
    lot_identity = db.execute(
        select(ProductionLot.id, ProductionLot.order_id)
        .join(ProductionOrder, ProductionOrder.id == ProductionLot.order_id)
        .where(
            ProductionLot.lot_code == lot_code,
            ProductionLot.deleted_at.is_(None),
            ProductionOrder.deleted_at.is_(None),
        )
    ).first()
    if lot_identity is None:
        raise QcInspectionError("Không tìm thấy mã lô đang hoạt động.")
    order = db.scalar(
        select(ProductionOrder)
        .where(
            ProductionOrder.id == lot_identity.order_id,
            ProductionOrder.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    lot = db.scalar(
        select(ProductionLot)
        .where(ProductionLot.id == lot_identity.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if lot is None or order is None or order.status == "cancelled":
        raise QcInspectionError("Lô không còn thuộc PO đang hoạt động.")
    if order.process_type == "BAVIA_ONLY":
        raise QcInspectionError("PO chỉ Bavia không có QC sản xuất theo lô.")
    if data.quantity_ok + data.quantity_ng != lot.quantity:
        raise QcInspectionError(f"Tổng OK + NG phải bằng số lượng lô ({lot.quantity}).")

    shift = db.scalar(
        select(Shift).where(
            Shift.id == data.shift_id,
            Shift.is_active.is_(True),
            Shift.deleted_at.is_(None),
        )
    )
    employee = db.scalar(
        select(Employee).where(
            Employee.id == data.qc_employee_id,
            Employee.employee_type == "qc",
            Employee.is_active.is_(True),
            Employee.deleted_at.is_(None),
        )
    )
    if shift is None:
        raise QcInspectionError("Chọn ca/kíp QC đang hoạt động.")
    if employee is None:
        raise QcInspectionError("Chọn nhân viên QC đang hoạt động.")

    duplicate_keys = [(row.defect_code_id, row.machine_id, row.disposition) for row in data.defects]
    if len(duplicate_keys) != len(set(duplicate_keys)):
        raise QcInspectionError("Gộp số lượng cùng dạng lỗi, máy và kết quả vào một dòng.")
    defect_ids = {row.defect_code_id for row in data.defects}
    machine_ids = {row.machine_id for row in data.defects}
    if defect_ids:
        valid_defects = set(
            db.scalars(
                select(DefectCode.id).where(
                    DefectCode.id.in_(defect_ids),
                    DefectCode.detected_at == "SX",
                    DefectCode.is_active.is_(True),
                    DefectCode.deleted_at.is_(None),
                )
            )
        )
        if valid_defects != defect_ids:
            raise QcInspectionError("Có mã lỗi không còn hoạt động trong QC sản xuất.")
    if machine_ids:
        valid_machines = set(
            db.scalars(
                select(Machine.id).where(
                    Machine.id.in_(machine_ids),
                    Machine.is_active.is_(True),
                    Machine.deleted_at.is_(None),
                )
            )
        )
        if valid_machines != machine_ids:
            raise QcInspectionError("Có máy không còn hoạt động.")

    inspection = db.scalar(
        select(LotQcInspection)
        .where(
            LotQcInspection.production_lot_id == lot.id,
            LotQcInspection.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    produced_quantity = int(
        db.scalar(
            select(func.coalesce(func.sum(DailyReportLine.quantity_produced), 0))
            .join(
                DailyReportPair,
                DailyReportPair.id == DailyReportLine.daily_report_pair_id,
            )
            .join(DailyReport, DailyReport.id == DailyReportPair.daily_report_id)
            .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
            .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
            .where(
                ProductionSchedule.order_id == order.id,
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
    already_qc_quantity = int(
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
    qc_quantity_after_save = already_qc_quantity + (0 if inspection else lot.quantity)
    if qc_quantity_after_save > produced_quantity:
        raise QcInspectionError(
            "Chưa đủ sản lượng đã xác nhận cho lô này. "
            f"Sản lượng PO: {produced_quantity}; sau khi lưu QC sẽ là {qc_quantity_after_save}."
        )
    if inspection is None and data.version != 0:
        raise QcInspectionError("Lô chưa có kết quả QC. Tải lại trang rồi nhập lại.")
    if inspection and inspection.version != data.version:
        raise QcInspectionError("Kết quả QC vừa được cập nhật. Tải lại trang rồi thử lại.")
    if inspection is not None:
        from app.modules.repairs.service import repair_balances

        balance = repair_balances(db, order.id, "QC", production_lot_id=lot.id)
        generated_after = balance["repair_generated"] - inspection.ng_repair + data.ng_repair
        if generated_after < balance["repaired_total"]:
            raise QcInspectionError("Không giảm NG sửa vì lô đã có hàng mang đi sửa.")

    if order.process_type == "FULL":
        from app.modules.daily_reports.models import BaviaReport
        from app.modules.repairs.models import RepairQcRecheck

        bavia_produced = int(
            db.scalar(
                select(func.coalesce(func.sum(BaviaReport.quantity_produced), 0)).where(
                    BaviaReport.order_id == order.id,
                    BaviaReport.deleted_at.is_(None),
                )
            )
            or 0
        )
        available_ok = int(
            db.scalar(
                select(func.coalesce(func.sum(LotQcInspection.quantity_ok), 0))
                .join(ProductionLot, ProductionLot.id == LotQcInspection.production_lot_id)
                .where(
                    ProductionLot.order_id == order.id,
                    ProductionLot.deleted_at.is_(None),
                    LotQcInspection.deleted_at.is_(None),
                )
            )
            or 0
        )
        available_ok += int(
            db.scalar(
                select(func.coalesce(func.sum(RepairQcRecheck.quantity_ok), 0)).where(
                    RepairQcRecheck.order_id == order.id,
                    RepairQcRecheck.stage == "QC",
                    RepairQcRecheck.deleted_at.is_(None),
                )
            )
            or 0
        )
        if inspection is not None:
            available_ok -= inspection.quantity_ok
        available_ok += data.quantity_ok
        if bavia_produced > available_ok:
            raise QcInspectionError("Không giảm OK vì đã có sản lượng Bavia sử dụng số hàng này.")

    old_values = _lot_qc_snapshot(db, inspection) if inspection else None
    now = datetime.now(UTC)
    if inspection is None:
        inspection = LotQcInspection(
            production_lot_id=lot.id,
            inspected_date=data.inspected_date,
            shift_id=shift.id,
            qc_employee_id=employee.id,
            quantity_in=lot.quantity,
            quantity_ok=data.quantity_ok,
            ng_scrap=data.ng_scrap,
            ng_repair=data.ng_repair,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(inspection)
        db.flush()
        action = "insert"
    else:
        inspection.inspected_date = data.inspected_date
        inspection.shift_id = shift.id
        inspection.qc_employee_id = employee.id
        inspection.quantity_in = lot.quantity
        inspection.quantity_ok = data.quantity_ok
        inspection.ng_scrap = data.ng_scrap
        inspection.ng_repair = data.ng_repair
        inspection.version += 1
        inspection.updated_at = now
        inspection.updated_by = actor_id
        for old_line in db.scalars(
            select(LotQcDefectLine).where(
                LotQcDefectLine.lot_qc_inspection_id == inspection.id,
                LotQcDefectLine.deleted_at.is_(None),
            )
        ):
            old_line.deleted_at = now
            old_line.updated_at = now
            old_line.updated_by = actor_id
        db.flush()
        action = "update"

    for row in data.defects:
        db.add(
            LotQcDefectLine(
                lot_qc_inspection_id=inspection.id,
                defect_code_id=row.defect_code_id,
                machine_id=row.machine_id,
                disposition=row.disposition,
                quantity=row.quantity,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
    db.flush()
    db.add(
        AuditLog(
            table_name="lot_qc_inspections",
            record_id=inspection.id,
            action=action,
            old_values=old_values,
            new_values=_lot_qc_snapshot(db, inspection),
            reason="Lưu kết quả QC theo lô",
            actor_id=actor_id,
        )
    )
    from app.modules.orders.lifecycle import refresh_order_lifecycle

    refresh_order_lifecycle(db, order.id, actor_id)
    return inspection


def _lot_qc_snapshot(db: Session, inspection: LotQcInspection) -> dict[str, object]:
    return {
        "production_lot_id": inspection.production_lot_id,
        "inspected_date": inspection.inspected_date.isoformat(),
        "shift_id": inspection.shift_id,
        "qc_employee_id": inspection.qc_employee_id,
        "quantity_in": inspection.quantity_in,
        "quantity_ok": inspection.quantity_ok,
        "ng_scrap": inspection.ng_scrap,
        "ng_repair": inspection.ng_repair,
        "defects": [
            {
                "defect_code_id": row.defect_code_id,
                "machine_id": row.machine_id,
                "disposition": row.disposition,
                "quantity": row.quantity,
            }
            for row in db.scalars(
                select(LotQcDefectLine).where(
                    LotQcDefectLine.lot_qc_inspection_id == inspection.id,
                    LotQcDefectLine.deleted_at.is_(None),
                )
            )
        ],
    }


def active_qc_employees(db: Session) -> list[Employee]:
    return list(
        db.scalars(
            select(Employee)
            .where(
                Employee.employee_type == "qc",
                Employee.is_active.is_(True),
                Employee.deleted_at.is_(None),
            )
            .order_by(Employee.code)
        )
    )


def get_qc_edit_data(db: Session, daily_report_id: int):
    inspection = db.scalar(
        select(QcInspection).where(
            QcInspection.daily_report_id == daily_report_id,
            QcInspection.deleted_at.is_(None),
        )
    )
    first = aliased(Machine)
    second = aliased(Machine)
    rows = list(
        db.execute(
            select(DailyReportPair, MachinePair, first, second, Employee)
            .join(MachinePair, MachinePair.id == DailyReportPair.machine_pair_id)
            .join(first, first.id == MachinePair.machine_1_id)
            .join(second, second.id == MachinePair.machine_2_id)
            .join(Employee, Employee.id == DailyReportPair.employee_id)
            .where(
                DailyReportPair.daily_report_id == daily_report_id,
                DailyReportPair.deleted_at.is_(None),
            )
            .order_by(DailyReportPair.id)
        )
    )
    pair_results = {}
    if inspection:
        pair_results = {
            row.daily_report_pair_id: row
            for row in db.scalars(
                select(QcPairResult).where(
                    QcPairResult.qc_inspection_id == inspection.id,
                    QcPairResult.deleted_at.is_(None),
                )
            )
        }
    produced_by_pair = dict(
        db.execute(
            select(
                DailyReportLine.daily_report_pair_id,
                func.sum(DailyReportLine.quantity_produced),
            )
            .where(
                DailyReportLine.daily_report_pair_id.in_([row[0].id for row in rows]),
                DailyReportLine.deleted_at.is_(None),
            )
            .group_by(DailyReportLine.daily_report_pair_id)
        ).all()
    )
    pairs = []
    for report_pair, pair, machine_1, machine_2, operator in rows:
        produced = produced_by_pair.get(report_pair.id, 0)
        pairs.append(
            {
                "report_pair": report_pair,
                "pair": pair,
                "machine_1": machine_1,
                "machine_2": machine_2,
                "operator": operator,
                "produced": produced,
                "result": pair_results.get(report_pair.id),
            }
        )
    steps = {}
    if inspection:
        steps = {
            row.step_number: row
            for row in db.scalars(
                select(QcCheckStep).where(
                    QcCheckStep.qc_inspection_id == inspection.id,
                    QcCheckStep.deleted_at.is_(None),
                )
            )
        }
    return inspection, pairs, steps


def qc_inspection_is_complete(db: Session, inspection_id: int) -> bool:
    inspection = db.get(QcInspection, inspection_id)
    if (
        inspection is None
        or inspection.deleted_at is not None
        or not inspection.pair_section_saved
        or not inspection.steps_section_saved
    ):
        return False
    pair_totals = db.execute(
        select(
            func.count(QcPairResult.id),
            func.coalesce(func.sum(QcPairResult.ng_scrap), 0),
            func.coalesce(func.sum(QcPairResult.ng_repair), 0),
        ).where(
            QcPairResult.qc_inspection_id == inspection_id,
            QcPairResult.deleted_at.is_(None),
        )
    ).one()
    step_totals = db.execute(
        select(
            func.count(QcCheckStep.id),
            func.coalesce(func.sum(QcCheckStep.ng_scrap), 0),
            func.coalesce(func.sum(QcCheckStep.ng_repair), 0),
        ).where(
            QcCheckStep.qc_inspection_id == inspection_id,
            QcCheckStep.deleted_at.is_(None),
        )
    ).one()
    return (
        pair_totals[0] > 0
        and step_totals[0] == 4
        and int(pair_totals[1]) == int(step_totals[1])
        and int(pair_totals[2]) == int(step_totals[2])
    )


def save_production_qc(
    db: Session, daily_report_id: int, data: QcInspectionInput, actor_id: int
) -> QcInspection:
    report = db.scalar(
        select(DailyReport)
        .where(DailyReport.id == daily_report_id, DailyReport.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if report is None:
        raise QcInspectionError("Không tìm thấy báo cáo sản lượng để nhập QC.")
    if report.status != "confirmed":
        raise QcInspectionError("Chỉ nhập QC khi báo cáo sản lượng đã được xác nhận.")
    order_id = _lock_report_order(db, report.id)

    shift = db.scalar(
        select(Shift).where(
            Shift.id == data.shift_id,
            Shift.is_active.is_(True),
            Shift.deleted_at.is_(None),
        )
    )
    if shift is None:
        raise QcInspectionError("Chỉ chọn ca/kíp đang hoạt động.")

    inspection = db.scalar(
        select(QcInspection).where(
            QcInspection.daily_report_id == report.id,
            QcInspection.deleted_at.is_(None),
        )
    )
    if inspection is None and data.version != 0:
        raise QcInspectionError("Dữ liệu QC đã thay đổi. Tải lại trang trước khi lưu.")
    if inspection and data.version != inspection.version:
        raise QcInspectionError("Dữ liệu QC đã được người khác cập nhật. Tải lại trang.")

    report_pairs = list(
        db.scalars(
            select(DailyReportPair)
            .where(
                DailyReportPair.daily_report_id == report.id,
                DailyReportPair.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    current_ids = {row.id for row in report_pairs}
    submitted_ids = {row.daily_report_pair_id for row in data.pairs}
    if current_ids != submitted_ids:
        raise QcInspectionError("Phần QC phải có đủ các cặp máy của báo cáo sản lượng.")

    employee_ids = {row.qc_employee_id for row in data.steps}
    retained_employee_ids = set()
    if inspection:
        retained_employee_ids = set(
            db.scalars(
                select(QcCheckStep.qc_employee_id).where(
                    QcCheckStep.qc_inspection_id == inspection.id,
                    QcCheckStep.deleted_at.is_(None),
                    QcCheckStep.qc_employee_id.is_not(None),
                )
            )
        )
    if employee_ids:
        valid_employees = set(
            db.scalars(
                select(Employee.id).where(
                    Employee.id.in_(employee_ids),
                    Employee.employee_type == "qc",
                    Employee.deleted_at.is_(None),
                    (Employee.is_active.is_(True) | Employee.id.in_(retained_employee_ids)),
                )
            )
        )
        if valid_employees != employee_ids:
            raise QcInspectionError("Chỉ chọn nhân viên QC đang hoạt động.")

    quantities_by_pair = dict(
        db.execute(
            select(
                DailyReportLine.daily_report_pair_id,
                func.sum(DailyReportLine.quantity_produced),
            )
            .where(
                DailyReportLine.daily_report_pair_id.in_(current_ids),
                DailyReportLine.deleted_at.is_(None),
            )
            .group_by(DailyReportLine.daily_report_pair_id)
        ).all()
    )
    if sum(quantities_by_pair.values()) == 0:
        raise QcInspectionError("Chưa có sản lượng để ghi nhận kết quả QC.")
    _ensure_repair_queue_not_reduced(
        db,
        order_id,
        inspection.id if inspection else None,
        sum(row.ng_repair for row in data.pairs),
    )
    for pair_input in data.pairs:
        produced = quantities_by_pair.get(pair_input.daily_report_pair_id, 0)
        if pair_input.ng_scrap + pair_input.ng_repair > produced:
            raise QcInspectionError(
                f"Tổng NG hủy và NG sửa vượt sản lượng đã ghi ({produced}) của cặp máy này."
            )

    if inspection is None:
        inspection = QcInspection(
            daily_report_id=report.id,
            inspected_date=data.inspected_date,
            shift_id=data.shift_id,
            version=1,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(inspection)
        db.flush()
        action = "insert"
        old_values = None
    else:
        old_values = _snapshot(db, inspection)
        inspection.inspected_date = data.inspected_date
        inspection.shift_id = data.shift_id
        inspection.version += 1
        inspection.updated_by = actor_id
        action = "update"

    old_results = {
        row.daily_report_pair_id: row
        for row in db.scalars(
            select(QcPairResult).where(
                QcPairResult.qc_inspection_id == inspection.id,
                QcPairResult.deleted_at.is_(None),
            )
        )
    }
    now = datetime.now(UTC)
    for row in data.pairs:
        result = old_results.pop(row.daily_report_pair_id, None)
        if result is None:
            db.add(
                QcPairResult(
                    qc_inspection_id=inspection.id,
                    daily_report_pair_id=row.daily_report_pair_id,
                    quantity_in=quantities_by_pair.get(row.daily_report_pair_id, 0),
                    ng_scrap=row.ng_scrap,
                    ng_repair=row.ng_repair,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )
        else:
            result.quantity_in = quantities_by_pair.get(row.daily_report_pair_id, 0)
            result.ng_scrap = row.ng_scrap
            result.ng_repair = row.ng_repair
            result.updated_at = now
            result.updated_by = actor_id
    for removed in old_results.values():
        removed.deleted_at = now
        removed.updated_at = now
        removed.updated_by = actor_id

    old_steps = {
        row.step_number: row
        for row in db.scalars(
            select(QcCheckStep).where(
                QcCheckStep.qc_inspection_id == inspection.id,
                QcCheckStep.deleted_at.is_(None),
            )
        )
    }
    for row in data.steps:
        step = old_steps.get(row.step_number)
        if step is None:
            db.add(
                QcCheckStep(
                    qc_inspection_id=inspection.id,
                    step_number=row.step_number,
                    ng_scrap=row.ng_scrap,
                    ng_repair=row.ng_repair,
                    qc_employee_id=row.qc_employee_id,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )
        else:
            step.ng_scrap = row.ng_scrap
            step.ng_repair = row.ng_repair
            step.qc_employee_id = row.qc_employee_id
            step.updated_at = now
            step.updated_by = actor_id

    inspection.pair_section_saved = True
    inspection.steps_section_saved = True
    db.flush()
    new_values = _snapshot(db, inspection)
    db.add(
        AuditLog(
            table_name="qc_inspections",
            record_id=inspection.id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            reason="Nhập/sửa kết quả QC sản xuất",
            actor_id=actor_id,
        )
    )
    _refresh_report_order(db, report.id, actor_id)
    return inspection


def save_qc_pair_section(
    db: Session,
    daily_report_id: int,
    data: QcPairSectionInput,
    actor_id: int,
    *,
    refresh_lifecycle: bool = True,
) -> QcInspection:
    """Save the pair totals without requiring the four-checkpoint section yet."""
    report, inspection, action, old_values = _prepare_section_save(
        db, daily_report_id, data, actor_id
    )
    report_pairs = list(
        db.scalars(
            select(DailyReportPair)
            .where(
                DailyReportPair.daily_report_id == report.id,
                DailyReportPair.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    current_ids = {row.id for row in report_pairs}
    if current_ids != {row.daily_report_pair_id for row in data.pairs}:
        raise QcInspectionError("Phần QC phải có đủ các cặp máy của báo cáo sản lượng.")
    quantities = dict(
        db.execute(
            select(
                DailyReportLine.daily_report_pair_id,
                func.sum(DailyReportLine.quantity_produced),
            )
            .where(
                DailyReportLine.daily_report_pair_id.in_(current_ids),
                DailyReportLine.deleted_at.is_(None),
            )
            .group_by(DailyReportLine.daily_report_pair_id)
        ).all()
    )
    if sum(quantities.values()) == 0:
        raise QcInspectionError("Chưa có sản lượng để ghi nhận kết quả QC.")
    _ensure_repair_queue_not_reduced(
        db,
        _lock_report_order(db, report.id),
        inspection.id,
        sum(row.ng_repair for row in data.pairs),
    )

    old_results = {
        row.daily_report_pair_id: row
        for row in db.scalars(
            select(QcPairResult).where(
                QcPairResult.qc_inspection_id == inspection.id,
                QcPairResult.deleted_at.is_(None),
            )
        )
    }
    now = datetime.now(UTC)
    for row in data.pairs:
        produced = quantities.get(row.daily_report_pair_id, 0)
        if row.ng_scrap + row.ng_repair > produced:
            raise QcInspectionError(
                f"Tổng NG hủy và NG sửa vượt sản lượng đã ghi ({produced}) của cặp máy này."
            )
        result = old_results.pop(row.daily_report_pair_id, None)
        if result is None:
            db.add(
                QcPairResult(
                    qc_inspection_id=inspection.id,
                    daily_report_pair_id=row.daily_report_pair_id,
                    quantity_in=produced,
                    ng_scrap=row.ng_scrap,
                    ng_repair=row.ng_repair,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )
        else:
            result.quantity_in = produced
            result.ng_scrap = row.ng_scrap
            result.ng_repair = row.ng_repair
            result.updated_at = now
            result.updated_by = actor_id
    for removed in old_results.values():
        removed.deleted_at = now
        removed.updated_at = now
        removed.updated_by = actor_id

    inspection.pair_section_saved = True
    db.flush()
    _audit_section(db, inspection, action, old_values, actor_id, "Lưu riêng QC theo cặp máy")
    if refresh_lifecycle:
        _refresh_report_order(db, report.id, actor_id)
    return inspection


def save_qc_steps_section(
    db: Session,
    daily_report_id: int,
    data: QcStepsSectionInput,
    actor_id: int,
    *,
    refresh_lifecycle: bool = True,
) -> QcInspection:
    """Save all four QC checkpoints independently of the pair totals."""
    report, inspection, action, old_values = _prepare_section_save(
        db, daily_report_id, data, actor_id
    )
    employee_ids = {row.qc_employee_id for row in data.steps}
    valid_employees = set(
        db.scalars(
            select(Employee.id).where(
                Employee.id.in_(employee_ids),
                Employee.employee_type == "qc",
                Employee.deleted_at.is_(None),
                Employee.is_active.is_(True),
            )
        )
    )
    if valid_employees != employee_ids:
        raise QcInspectionError("Chỉ chọn nhân viên QC đang hoạt động.")
    old_steps = {
        row.step_number: row
        for row in db.scalars(
            select(QcCheckStep).where(
                QcCheckStep.qc_inspection_id == inspection.id,
                QcCheckStep.deleted_at.is_(None),
            )
        )
    }
    now = datetime.now(UTC)
    for row in data.steps:
        step = old_steps.get(row.step_number)
        if step is None:
            db.add(
                QcCheckStep(
                    qc_inspection_id=inspection.id,
                    step_number=row.step_number,
                    ng_scrap=row.ng_scrap,
                    ng_repair=row.ng_repair,
                    qc_employee_id=row.qc_employee_id,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )
        else:
            step.ng_scrap = row.ng_scrap
            step.ng_repair = row.ng_repair
            step.qc_employee_id = row.qc_employee_id
            step.updated_at = now
            step.updated_by = actor_id
    inspection.steps_section_saved = True
    db.flush()
    _audit_section(db, inspection, action, old_values, actor_id, "Lưu riêng bốn bước kiểm soát QC")
    if refresh_lifecycle:
        _refresh_report_order(db, report.id, actor_id)
    return inspection


def save_qc_partial(
    db: Session, daily_report_id: int, data: QcPartialSaveInput, actor_id: int
) -> QcInspection:
    """Save the complete pair section and any individually completed QC steps atomically."""
    inspection = None
    if data.pairs:
        pair_data = QcPairSectionInput(
            inspected_date=data.inspected_date,
            shift_id=data.shift_id,
            version=data.version,
            pairs=data.pairs,
        )
        inspection = save_qc_pair_section(
            db,
            daily_report_id,
            pair_data,
            actor_id,
            refresh_lifecycle=False,
        )
    if data.steps:
        steps_data = QcStepsSectionInput(
            inspected_date=data.inspected_date,
            shift_id=data.shift_id,
            version=inspection.version if inspection else data.version,
            steps=data.steps,
        )
        inspection = save_qc_steps_section(
            db,
            daily_report_id,
            steps_data,
            actor_id,
            refresh_lifecycle=False,
        )
    if inspection is None:
        raise QcInspectionError("Nhập ít nhất một phần QC đủ thông tin rồi lưu.")
    _refresh_report_order(db, daily_report_id, actor_id)
    return inspection


def _refresh_report_order(db: Session, report_id: int, actor_id: int) -> None:
    from app.modules.blank_requests.models import BlankRequest
    from app.modules.orders.lifecycle import OrderLifecycleError, refresh_order_lifecycle
    from app.modules.schedules.models import ProductionSchedule

    order_id = db.scalar(
        select(ProductionSchedule.order_id)
        .join(BlankRequest, BlankRequest.schedule_id == ProductionSchedule.id)
        .join(DailyReport, DailyReport.blank_request_id == BlankRequest.id)
        .where(DailyReport.id == report_id)
    )
    if order_id is not None:
        try:
            refresh_order_lifecycle(db, order_id, actor_id)
        except OrderLifecycleError as exc:
            raise QcInspectionError(str(exc)) from exc


def _prepare_section_save(db: Session, daily_report_id: int, data, actor_id: int):
    report = db.scalar(
        select(DailyReport)
        .where(DailyReport.id == daily_report_id, DailyReport.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if report is None or report.status != "confirmed":
        raise QcInspectionError("Chỉ nhập QC khi báo cáo sản lượng đã được xác nhận.")
    _lock_report_order(db, report.id)
    shift = db.scalar(
        select(Shift).where(
            Shift.id == data.shift_id,
            Shift.is_active.is_(True),
            Shift.deleted_at.is_(None),
        )
    )
    if shift is None:
        raise QcInspectionError("Chỉ chọn ca/kíp đang hoạt động.")
    inspection = db.scalar(
        select(QcInspection)
        .where(
            QcInspection.daily_report_id == report.id,
            QcInspection.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if inspection is None and data.version != 0:
        raise QcInspectionError("Dữ liệu QC đã thay đổi. Tải lại trang trước khi lưu.")
    if inspection and data.version != inspection.version:
        raise QcInspectionError("Dữ liệu QC đã được người khác cập nhật. Tải lại trang.")
    if inspection is None:
        inspection = QcInspection(
            daily_report_id=report.id,
            inspected_date=data.inspected_date,
            shift_id=data.shift_id,
            version=1,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(inspection)
        db.flush()
        return report, inspection, "insert", None
    old_values = _snapshot(db, inspection)
    inspection.inspected_date = data.inspected_date
    inspection.shift_id = data.shift_id
    inspection.version += 1
    inspection.updated_at = datetime.now(UTC)
    inspection.updated_by = actor_id
    return report, inspection, "update", old_values


def _lock_report_order(db: Session, report_id: int) -> int:
    from app.modules.orders.models import ProductionOrder

    order_id = db.scalar(
        select(ProductionSchedule.order_id)
        .join(BlankRequest, BlankRequest.schedule_id == ProductionSchedule.id)
        .join(DailyReport, DailyReport.blank_request_id == BlankRequest.id)
        .where(DailyReport.id == report_id)
    )
    if (
        order_id is None
        or db.scalar(
            select(ProductionOrder.id)
            .where(ProductionOrder.id == order_id, ProductionOrder.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        is None
    ):
        raise QcInspectionError("Không tìm thấy PO đang hoạt động cho báo cáo QC.")
    return order_id


def _ensure_repair_queue_not_reduced(
    db: Session, order_id: int, inspection_id: int | None, submitted_ng_repair: int
) -> None:
    from app.modules.repairs.models import RepairJob, RepairQcRecheck

    other_initial = (
        db.scalar(
            select(func.coalesce(func.sum(QcPairResult.ng_repair), 0))
            .join(QcInspection, QcInspection.id == QcPairResult.qc_inspection_id)
            .join(DailyReport, DailyReport.id == QcInspection.daily_report_id)
            .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
            .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
            .where(
                QcInspection.id != inspection_id if inspection_id else True,
                QcInspection.deleted_at.is_(None),
                QcPairResult.deleted_at.is_(None),
                DailyReport.deleted_at.is_(None),
                BlankRequest.deleted_at.is_(None),
                ProductionSchedule.order_id == order_id,
            )
        )
        or 0
    )
    recheck_repair = (
        db.scalar(
            select(func.coalesce(func.sum(RepairQcRecheck.ng_repair), 0)).where(
                RepairQcRecheck.order_id == order_id,
                RepairQcRecheck.stage == "QC",
                RepairQcRecheck.deleted_at.is_(None),
            )
        )
        or 0
    )
    dispatched = (
        db.scalar(
            select(func.coalesce(func.sum(RepairJob.quantity_repaired), 0)).where(
                RepairJob.order_id == order_id,
                RepairJob.stage == "QC",
                RepairJob.deleted_at.is_(None),
            )
        )
        or 0
    )
    if int(other_initial) + submitted_ng_repair + int(recheck_repair) < int(dispatched):
        raise QcInspectionError(
            "Không giảm NG sửa vì đã có số lượng được ghi nhận mang đi sửa; "
            "cần xử lý dữ liệu sửa trước."
        )


def _audit_section(
    db: Session,
    inspection: QcInspection,
    action: str,
    old_values: dict[str, object] | None,
    actor_id: int,
    reason: str,
) -> None:
    db.add(
        AuditLog(
            table_name="qc_inspections",
            record_id=inspection.id,
            action=action,
            old_values=old_values,
            new_values=_snapshot(db, inspection),
            reason=reason,
            actor_id=actor_id,
        )
    )


def _snapshot(db: Session, inspection: QcInspection) -> dict[str, object]:
    pairs = list(
        db.scalars(
            select(QcPairResult).where(
                QcPairResult.qc_inspection_id == inspection.id,
                QcPairResult.deleted_at.is_(None),
            )
        )
    )
    steps = list(
        db.scalars(
            select(QcCheckStep).where(
                QcCheckStep.qc_inspection_id == inspection.id,
                QcCheckStep.deleted_at.is_(None),
            )
        )
    )
    return {
        "daily_report_id": inspection.daily_report_id,
        "inspected_date": inspection.inspected_date.isoformat(),
        "shift_id": inspection.shift_id,
        "version": inspection.version,
        "pair_section_saved": inspection.pair_section_saved,
        "steps_section_saved": inspection.steps_section_saved,
        "pairs": [
            {
                "daily_report_pair_id": row.daily_report_pair_id,
                "quantity_in": row.quantity_in,
                "ng_scrap": row.ng_scrap,
                "ng_repair": row.ng_repair,
            }
            for row in pairs
        ],
        "steps": [
            {
                "step_number": row.step_number,
                "ng_scrap": row.ng_scrap,
                "ng_repair": row.ng_repair,
                "qc_employee_id": row.qc_employee_id,
            }
            for row in steps
        ],
    }
