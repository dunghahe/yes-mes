from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.assets.models import Machine, MachinePair
from app.modules.auth.models import AuditLog
from app.modules.blank_requests.models import BlankRequest
from app.modules.daily_reports.models import (
    BaviaReport,
    DailyReport,
    DailyReportLine,
    DailyReportPair,
    DowntimeEntry,
)
from app.modules.defects.models import DefectCode
from app.modules.employees.models import Employee
from app.modules.orders.models import ProductionLot, ProductionOrder
from app.modules.products.models import Product
from app.modules.qc.models import (
    BaviaQcInspection,
    LotQcDefectLine,
    LotQcInspection,
    QcInspection,
    QcPairResult,
)
from app.modules.qc.service import qc_inspection_is_complete
from app.modules.repairs.models import RepairJob, RepairQcRecheck
from app.modules.schedules.models import ProductionSchedule
from app.modules.shifts.models import Shift


def production_rows(
    db: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    order_id: int | None = None,
    machine_pair_id: int | None = None,
    employee_id: int | None = None,
) -> list[dict[str, object]]:
    machine_1 = Machine.__table__.alias("production_machine_1")
    machine_2 = Machine.__table__.alias("production_machine_2")
    query = (
        select(
            DailyReport.report_date,
            Shift.name,
            ProductionOrder.id,
            ProductionOrder.po_no,
            Product.code,
            func.concat(machine_1.c.code, " – ", machine_2.c.code),
            Employee.code,
            Employee.name,
            DailyReportLine.quantity_produced,
            DailyReportLine.cycle_time_snapshot_seconds,
            DailyReportPair.downtime_recorded,
        )
        .join(DailyReportPair, DailyReportPair.daily_report_id == DailyReport.id)
        .join(DailyReportLine, DailyReportLine.daily_report_pair_id == DailyReportPair.id)
        .join(Shift, Shift.id == DailyReportPair.shift_id)
        .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
        .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
        .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(MachinePair, MachinePair.id == DailyReportPair.machine_pair_id)
        .join(machine_1, machine_1.c.id == MachinePair.machine_1_id)
        .join(machine_2, machine_2.c.id == MachinePair.machine_2_id)
        .join(Employee, Employee.id == DailyReportPair.employee_id)
        .where(
            DailyReport.deleted_at.is_(None),
            DailyReportPair.deleted_at.is_(None),
            DailyReportLine.deleted_at.is_(None),
            BlankRequest.deleted_at.is_(None),
            ProductionSchedule.deleted_at.is_(None),
            ProductionOrder.deleted_at.is_(None),
        )
    )
    if date_from:
        query = query.where(DailyReport.report_date >= date_from)
    if date_to:
        query = query.where(DailyReport.report_date <= date_to)
    if order_id:
        query = query.where(ProductionOrder.id == order_id)
    if machine_pair_id:
        query = query.where(DailyReportPair.machine_pair_id == machine_pair_id)
    if employee_id:
        query = query.where(DailyReportPair.employee_id == employee_id)
    result = []
    for row in db.execute(query.order_by(DailyReport.report_date, ProductionOrder.po_no)):
        result.append(
            {
                "date": row[0].isoformat(),
                "shift": row[1],
                "order_id": row[2],
                "po_no": row[3],
                "product_code": row[4],
                "machine_pair": row[5],
                "employee_code": row[6],
                "employee_name": row[7],
                "quantity_produced": row[8],
                "cycle_time_seconds": float(row[9]),
                "downtime_recorded": row[10],
                "stage": "SX",
            }
        )
    bavia_query = (
        select(
            BaviaReport.report_date,
            Shift.name,
            ProductionOrder.id,
            ProductionOrder.po_no,
            Product.code,
            Employee.code,
            Employee.name,
            BaviaReport.quantity_produced,
        )
        .join(ProductionOrder, ProductionOrder.id == BaviaReport.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(Shift, Shift.id == BaviaReport.shift_id)
        .join(Employee, Employee.id == BaviaReport.employee_id)
        .where(BaviaReport.deleted_at.is_(None), ProductionOrder.deleted_at.is_(None))
    )
    if date_from:
        bavia_query = bavia_query.where(BaviaReport.report_date >= date_from)
    if date_to:
        bavia_query = bavia_query.where(BaviaReport.report_date <= date_to)
    if order_id:
        bavia_query = bavia_query.where(ProductionOrder.id == order_id)
    if employee_id:
        bavia_query = bavia_query.where(BaviaReport.employee_id == employee_id)
    if not machine_pair_id:
        for row in db.execute(bavia_query):
            result.append(
                {
                    "date": row[0].isoformat(),
                    "shift": row[1],
                    "order_id": row[2],
                    "po_no": row[3],
                    "product_code": row[4],
                    "machine_pair": None,
                    "employee_code": row[5],
                    "employee_name": row[6],
                    "quantity_produced": row[7],
                    "cycle_time_seconds": None,
                    "downtime_recorded": None,
                    "stage": "BAVIA",
                }
            )
    return result


def po_summaries(db: Session) -> list[dict[str, object]]:
    orders = list(
        db.execute(
            select(ProductionOrder, Product)
            .join(Product, Product.id == ProductionOrder.product_id)
            .where(ProductionOrder.deleted_at.is_(None))
            .order_by(ProductionOrder.po_no)
        )
    )
    result = []
    for order, product in orders:
        production = (
            db.scalar(
                select(func.coalesce(func.sum(DailyReportLine.quantity_produced), 0))
                .join(DailyReportPair, DailyReportPair.id == DailyReportLine.daily_report_pair_id)
                .join(DailyReport, DailyReport.id == DailyReportPair.daily_report_id)
                .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
                .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
                .where(
                    ProductionSchedule.order_id == order.id,
                    DailyReportLine.deleted_at.is_(None),
                    DailyReportPair.deleted_at.is_(None),
                    DailyReport.deleted_at.is_(None),
                    BlankRequest.deleted_at.is_(None),
                    ProductionSchedule.deleted_at.is_(None),
                )
            )
            or 0
        )
        candidate_qc_ids = list(
            db.scalars(
                select(QcInspection.id)
                .join(DailyReport, DailyReport.id == QcInspection.daily_report_id)
                .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
                .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
                .where(
                    ProductionSchedule.order_id == order.id,
                    QcInspection.deleted_at.is_(None),
                    DailyReport.deleted_at.is_(None),
                    BlankRequest.deleted_at.is_(None),
                    ProductionSchedule.deleted_at.is_(None),
                )
            )
        )
        complete_qc_ids = [
            inspection_id
            for inspection_id in candidate_qc_ids
            if qc_inspection_is_complete(db, inspection_id)
        ]
        production_qc = db.execute(
            select(
                func.coalesce(func.sum(QcPairResult.quantity_in), 0),
                func.coalesce(func.sum(QcPairResult.ng_scrap), 0),
                func.coalesce(func.sum(QcPairResult.ng_repair), 0),
            )
            .join(QcInspection, QcInspection.id == QcPairResult.qc_inspection_id)
            .join(DailyReport, DailyReport.id == QcInspection.daily_report_id)
            .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
            .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
            .where(
                ProductionSchedule.order_id == order.id,
                QcInspection.id.in_(complete_qc_ids) if complete_qc_ids else False,
                QcInspection.deleted_at.is_(None),
                QcPairResult.deleted_at.is_(None),
                DailyReport.deleted_at.is_(None),
                BlankRequest.deleted_at.is_(None),
                ProductionSchedule.deleted_at.is_(None),
            )
        ).one()
        lot_qc = db.execute(
            select(
                func.coalesce(func.sum(LotQcInspection.quantity_in), 0),
                func.coalesce(func.sum(LotQcInspection.ng_scrap), 0),
                func.coalesce(func.sum(LotQcInspection.ng_repair), 0),
            )
            .join(ProductionLot, ProductionLot.id == LotQcInspection.production_lot_id)
            .where(
                ProductionLot.order_id == order.id,
                ProductionLot.deleted_at.is_(None),
                LotQcInspection.deleted_at.is_(None),
            )
        ).one()
        if int(lot_qc[0]):
            production_qc = lot_qc
        bavia_produced = (
            db.scalar(
                select(func.coalesce(func.sum(BaviaReport.quantity_produced), 0)).where(
                    BaviaReport.order_id == order.id,
                    BaviaReport.deleted_at.is_(None),
                )
            )
            or 0
        )
        bavia_qc = db.execute(
            select(
                func.coalesce(func.sum(BaviaQcInspection.quantity_in), 0),
                func.coalesce(func.sum(BaviaQcInspection.ng_scrap), 0),
                func.coalesce(func.sum(BaviaQcInspection.ng_repair), 0),
            )
            .join(BaviaReport, BaviaReport.id == BaviaQcInspection.bavia_report_id)
            .where(
                BaviaReport.order_id == order.id,
                BaviaReport.deleted_at.is_(None),
                BaviaQcInspection.deleted_at.is_(None),
            )
        ).one()
        repair_metrics = {}
        for stage, source in (("QC", production_qc), ("QC_BAVIA", bavia_qc)):
            rechecks = db.execute(
                select(
                    func.coalesce(func.sum(RepairQcRecheck.quantity_in), 0),
                    func.coalesce(func.sum(RepairQcRecheck.quantity_ok), 0),
                    func.coalesce(func.sum(RepairQcRecheck.ng_scrap), 0),
                    func.coalesce(func.sum(RepairQcRecheck.ng_repair), 0),
                ).where(
                    RepairQcRecheck.order_id == order.id,
                    RepairQcRecheck.stage == stage,
                    RepairQcRecheck.deleted_at.is_(None),
                )
            ).one()
            repaired = (
                db.scalar(
                    select(func.coalesce(func.sum(RepairJob.quantity_repaired), 0)).where(
                        RepairJob.order_id == order.id,
                        RepairJob.stage == stage,
                        RepairJob.deleted_at.is_(None),
                    )
                )
                or 0
            )
            repair_metrics[stage] = {
                "ng_scrap": int(source[1]) + int(rechecks[2]),
                "ng_waiting_repair": max(int(source[2]) + int(rechecks[3]) - int(repaired), 0),
                "repaired": int(repaired),
                "repaired_waiting_qc": max(int(repaired) - int(rechecks[0]), 0),
                "recheck_ok": int(rechecks[1]),
            }
        production_ok = max(
            int(production_qc[0]) - int(production_qc[1]) - int(production_qc[2]), 0
        )
        final_stage = "QC" if order.process_type == "SX_ONLY" else "QC_BAVIA"
        final_metrics = repair_metrics[final_stage]
        final_qc = bavia_qc if final_stage == "QC_BAVIA" else production_qc
        finished = (
            max(int(final_qc[0]) - int(final_qc[1]) - int(final_qc[2]), 0)
            + final_metrics["recheck_ok"]
        )
        metrics = repair_metrics["QC"]
        result.append(
            {
                "order_id": order.id,
                "po_no": order.po_no,
                "product_code": product.code,
                "process_type": order.process_type,
                "ordered_quantity": order.ordered_quantity,
                "produced": int(production),
                "production_ok": production_ok + metrics["recheck_ok"],
                "bavia_produced": int(bavia_produced),
                "finished_quantity": finished,
                "ng_scrap": metrics["ng_scrap"] + repair_metrics["QC_BAVIA"]["ng_scrap"],
                "ng_waiting_repair": metrics["ng_waiting_repair"]
                + repair_metrics["QC_BAVIA"]["ng_waiting_repair"],
                "repaired": metrics["repaired"] + repair_metrics["QC_BAVIA"]["repaired"],
                "repaired_waiting_qc": metrics["repaired_waiting_qc"]
                + repair_metrics["QC_BAVIA"]["repaired_waiting_qc"],
                "progress_percent": min(finished / order.ordered_quantity * 100, 999.99),
            }
        )
    return result


def repair_history_rows(
    db: Session,
    *,
    order_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, object]]:
    jobs = select(RepairJob).where(RepairJob.deleted_at.is_(None))
    rechecks = select(RepairQcRecheck).where(RepairQcRecheck.deleted_at.is_(None))
    if order_id:
        jobs = jobs.where(RepairJob.order_id == order_id)
        rechecks = rechecks.where(RepairQcRecheck.order_id == order_id)
    if date_from:
        jobs = jobs.where(RepairJob.repair_date >= date_from)
        rechecks = rechecks.where(RepairQcRecheck.inspected_date >= date_from)
    if date_to:
        jobs = jobs.where(RepairJob.repair_date <= date_to)
        rechecks = rechecks.where(RepairQcRecheck.inspected_date <= date_to)
    result = []
    for row in db.scalars(jobs.order_by(RepairJob.repair_date)):
        order = db.get(ProductionOrder, row.order_id)
        employee = db.get(Employee, row.repair_employee_id)
        lot = db.get(ProductionLot, row.production_lot_id) if row.production_lot_id else None
        result.append(
            {
                "kind": "repair",
                "repair_code": row.repair_code,
                "date": row.repair_date.isoformat(),
                "order_id": row.order_id,
                "po_no": order.po_no if order else "",
                "lot_code": lot.lot_code if lot else None,
                "stage": row.stage,
                "employee": employee.name if employee else "",
                "quantity": row.quantity_repaired,
                "note": row.note,
            }
        )
    for row in db.scalars(rechecks.order_by(RepairQcRecheck.inspected_date)):
        order = db.get(ProductionOrder, row.order_id)
        employee = db.get(Employee, row.qc_employee_id)
        lot = db.get(ProductionLot, row.production_lot_id) if row.production_lot_id else None
        result.append(
            {
                "kind": "recheck",
                "repair_code": (
                    db.get(RepairJob, row.repair_job_id).repair_code
                    if row.repair_job_id and db.get(RepairJob, row.repair_job_id)
                    else None
                ),
                "date": row.inspected_date.isoformat(),
                "order_id": row.order_id,
                "po_no": order.po_no if order else "",
                "lot_code": lot.lot_code if lot else None,
                "stage": row.stage,
                "employee": employee.name if employee else "",
                "quantity_in": row.quantity_in,
                "quantity_ok": row.quantity_ok,
                "ng_scrap": row.ng_scrap,
                "ng_repair": row.ng_repair,
            }
        )
    return sorted(result, key=lambda row: row["date"])


def quality_ng_rows(
    db: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    order_id: int | None = None,
    machine_pair_id: int | None = None,
    employee_id: int | None = None,
    ng_kind: str | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    lot_qc_filters = [
        LotQcInspection.deleted_at.is_(None),
        ProductionLot.deleted_at.is_(None),
    ]
    if date_from:
        lot_qc_filters.append(LotQcInspection.inspected_date >= date_from)
    if date_to:
        lot_qc_filters.append(LotQcInspection.inspected_date <= date_to)
    if order_id:
        lot_qc_filters.append(ProductionLot.order_id == order_id)
    if employee_id:
        lot_qc_filters.append(LotQcInspection.qc_employee_id == employee_id)
    lot_qc_order_ids = set(
        db.scalars(
            select(ProductionLot.order_id)
            .join(LotQcInspection, LotQcInspection.production_lot_id == ProductionLot.id)
            .join(Employee, Employee.id == LotQcInspection.qc_employee_id)
            .where(*lot_qc_filters)
            .distinct()
        )
    )
    machine_1 = Machine.__table__.alias("ng_machine_1")
    machine_2 = Machine.__table__.alias("ng_machine_2")
    production_query = (
        select(
            QcInspection.inspected_date,
            Shift.name,
            ProductionOrder.id,
            ProductionOrder.po_no,
            Product.code,
            func.concat(machine_1.c.code, " – ", machine_2.c.code),
            Employee.code,
            QcPairResult.ng_scrap,
            QcPairResult.ng_repair,
            QcInspection.id,
        )
        .join(QcPairResult, QcPairResult.qc_inspection_id == QcInspection.id)
        .join(DailyReport, DailyReport.id == QcInspection.daily_report_id)
        .join(DailyReportPair, DailyReportPair.id == QcPairResult.daily_report_pair_id)
        .join(Shift, Shift.id == QcInspection.shift_id)
        .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
        .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
        .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(MachinePair, MachinePair.id == DailyReportPair.machine_pair_id)
        .join(machine_1, machine_1.c.id == MachinePair.machine_1_id)
        .join(machine_2, machine_2.c.id == MachinePair.machine_2_id)
        .join(Employee, Employee.id == DailyReportPair.employee_id)
        .where(
            QcInspection.deleted_at.is_(None),
            QcInspection.pair_section_saved.is_(True),
            QcPairResult.deleted_at.is_(None),
            DailyReport.deleted_at.is_(None),
            DailyReportPair.deleted_at.is_(None),
        )
    )
    if date_from:
        production_query = production_query.where(QcInspection.inspected_date >= date_from)
    if date_to:
        production_query = production_query.where(QcInspection.inspected_date <= date_to)
    if order_id:
        production_query = production_query.where(ProductionOrder.id == order_id)
    if machine_pair_id:
        production_query = production_query.where(
            DailyReportPair.machine_pair_id == machine_pair_id
        )
    if employee_id:
        production_query = production_query.where(DailyReportPair.employee_id == employee_id)
    for row in db.execute(production_query):
        if row[2] in lot_qc_order_ids:
            continue
        complete = qc_inspection_is_complete(db, row[9])
        if ng_kind in (None, "scrap") and row[7]:
            rows.append(_ng_row(row, "QC", "scrap", row[7], complete))
        if ng_kind in (None, "repair") and row[8]:
            rows.append(_ng_row(row, "QC", "repair", row[8], complete))

    bavia_query = (
        select(
            BaviaQcInspection.inspected_date,
            Shift.name,
            ProductionOrder.id,
            ProductionOrder.po_no,
            Product.code,
            BaviaQcInspection.ng_scrap,
            BaviaQcInspection.ng_repair,
            Employee.code,
        )
        .join(BaviaReport, BaviaReport.id == BaviaQcInspection.bavia_report_id)
        .join(ProductionOrder, ProductionOrder.id == BaviaReport.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(Shift, Shift.id == BaviaQcInspection.shift_id)
        .join(Employee, Employee.id == BaviaQcInspection.qc_employee_id)
        .where(
            BaviaQcInspection.deleted_at.is_(None),
            BaviaReport.deleted_at.is_(None),
        )
    )
    if date_from:
        bavia_query = bavia_query.where(BaviaQcInspection.inspected_date >= date_from)
    if date_to:
        bavia_query = bavia_query.where(BaviaQcInspection.inspected_date <= date_to)
    if order_id:
        bavia_query = bavia_query.where(ProductionOrder.id == order_id)
    if machine_pair_id:
        bavia_query = None
    if employee_id and bavia_query is not None:
        bavia_query = bavia_query.where(BaviaQcInspection.qc_employee_id == employee_id)
    if bavia_query is not None:
        for row in db.execute(bavia_query):
            if ng_kind in (None, "scrap") and row[5]:
                rows.append(_ng_row(row, "QC_BAVIA", "scrap", row[5], True))
            if ng_kind in (None, "repair") and row[6]:
                rows.append(_ng_row(row, "QC_BAVIA", "repair", row[6], True))

    lot_query = (
        select(
            LotQcInspection.inspected_date,
            Shift.name,
            ProductionOrder.id,
            ProductionOrder.po_no,
            Product.code,
            ProductionLot.lot_code,
            Machine.code,
            DefectCode.code,
            LotQcDefectLine.disposition,
            LotQcDefectLine.quantity,
            LotQcInspection.qc_employee_id,
        )
        .join(ProductionLot, ProductionLot.id == LotQcInspection.production_lot_id)
        .join(ProductionOrder, ProductionOrder.id == ProductionLot.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(Shift, Shift.id == LotQcInspection.shift_id)
        .join(LotQcDefectLine, LotQcDefectLine.lot_qc_inspection_id == LotQcInspection.id)
        .join(Machine, Machine.id == LotQcDefectLine.machine_id)
        .join(DefectCode, DefectCode.id == LotQcDefectLine.defect_code_id)
        .where(
            LotQcInspection.deleted_at.is_(None),
            LotQcDefectLine.deleted_at.is_(None),
            ProductionLot.deleted_at.is_(None),
            ProductionOrder.deleted_at.is_(None),
        )
    )
    if date_from:
        lot_query = lot_query.where(LotQcInspection.inspected_date >= date_from)
    if date_to:
        lot_query = lot_query.where(LotQcInspection.inspected_date <= date_to)
    if order_id:
        lot_query = lot_query.where(ProductionOrder.id == order_id)
    if employee_id:
        lot_query = lot_query.where(LotQcInspection.qc_employee_id == employee_id)
    if not machine_pair_id:
        for row in db.execute(lot_query):
            kind = row[8]
            if ng_kind not in (None, kind):
                continue
            rows.append(
                {
                    "date": row[0].isoformat(),
                    "shift": row[1],
                    "order_id": row[2],
                    "po_no": row[3],
                    "product_code": row[4],
                    "machine_pair": row[6],
                    "lot_code": row[5],
                    "defect_code": row[7],
                    "employee_code": str(row[10]),
                    "stage": "QC",
                    "ng_kind": kind,
                    "quantity": int(row[9]),
                    "qc_complete": True,
                    "is_recheck": False,
                }
            )

    recheck_query = (
        select(
            RepairQcRecheck.inspected_date,
            Shift.name,
            ProductionOrder.id,
            ProductionOrder.po_no,
            Product.code,
            RepairQcRecheck.stage,
            RepairQcRecheck.ng_scrap,
            RepairQcRecheck.ng_repair,
            Employee.code,
        )
        .join(ProductionOrder, ProductionOrder.id == RepairQcRecheck.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(Shift, Shift.id == RepairQcRecheck.shift_id)
        .join(Employee, Employee.id == RepairQcRecheck.qc_employee_id)
        .where(RepairQcRecheck.deleted_at.is_(None), ProductionOrder.deleted_at.is_(None))
    )
    if date_from:
        recheck_query = recheck_query.where(RepairQcRecheck.inspected_date >= date_from)
    if date_to:
        recheck_query = recheck_query.where(RepairQcRecheck.inspected_date <= date_to)
    if order_id:
        recheck_query = recheck_query.where(ProductionOrder.id == order_id)
    if employee_id:
        recheck_query = recheck_query.where(RepairQcRecheck.qc_employee_id == employee_id)
    if not machine_pair_id:
        for row in db.execute(recheck_query):
            for kind, quantity in (("scrap", row[6]), ("repair", row[7])):
                if quantity and ng_kind in (None, kind):
                    rows.append(
                        {
                            "date": row[0].isoformat(),
                            "shift": row[1],
                            "order_id": row[2],
                            "po_no": row[3],
                            "product_code": row[4],
                            "machine_pair": None,
                            "employee_code": row[8],
                            "stage": row[5],
                            "ng_kind": kind,
                            "quantity": int(quantity),
                            "qc_complete": True,
                            "is_recheck": True,
                        }
                    )
    return sorted(rows, key=lambda value: (value["date"], value["po_no"]))


def oee_rows(
    db: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    order_id: int | None = None,
    machine_pair_id: int | None = None,
    employee_id: int | None = None,
) -> list[dict[str, object]]:
    machine_1 = Machine.__table__.alias("oee_machine_1")
    machine_2 = Machine.__table__.alias("oee_machine_2")
    query = (
        select(
            DailyReportPair.id,
            DailyReport.report_date,
            Shift.name,
            ProductionOrder.id,
            ProductionOrder.po_no,
            Product.code,
            MachinePair.id,
            func.concat(machine_1.c.code, " – ", machine_2.c.code),
            Employee.id,
            Employee.name,
            DailyReportPair.planned_minutes,
            DailyReportPair.downtime_recorded,
        )
        .join(DailyReport, DailyReport.id == DailyReportPair.daily_report_id)
        .join(Shift, Shift.id == DailyReportPair.shift_id)
        .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
        .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
        .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(MachinePair, MachinePair.id == DailyReportPair.machine_pair_id)
        .join(machine_1, machine_1.c.id == MachinePair.machine_1_id)
        .join(machine_2, machine_2.c.id == MachinePair.machine_2_id)
        .join(Employee, Employee.id == DailyReportPair.employee_id)
        .where(
            DailyReport.deleted_at.is_(None),
            DailyReportPair.deleted_at.is_(None),
            DailyReport.status == "confirmed",
        )
    )
    if date_from:
        query = query.where(DailyReport.report_date >= date_from)
    if date_to:
        query = query.where(DailyReport.report_date <= date_to)
    if order_id:
        query = query.where(ProductionOrder.id == order_id)
    if machine_pair_id:
        query = query.where(DailyReportPair.machine_pair_id == machine_pair_id)
    if employee_id:
        query = query.where(DailyReportPair.employee_id == employee_id)

    output = []
    report_rows = list(
        db.execute(query.order_by(DailyReport.report_date, machine_1.c.code, machine_2.c.code))
    )
    qc_by_order: dict[int, tuple[int | None, int, bool]] = {}
    for current_order_id in {row[3] for row in report_rows}:
        lot_date_filters = []
        if date_from:
            lot_date_filters.append(LotQcInspection.inspected_date >= date_from)
        if date_to:
            lot_date_filters.append(LotQcInspection.inspected_date <= date_to)
        ng_total, qc_total = db.execute(
            select(
                func.coalesce(func.sum(LotQcInspection.ng_scrap + LotQcInspection.ng_repair), 0),
                func.coalesce(func.sum(LotQcInspection.quantity_in), 0),
            )
            .join(ProductionLot, ProductionLot.id == LotQcInspection.production_lot_id)
            .where(
                ProductionLot.order_id == current_order_id,
                ProductionLot.deleted_at.is_(None),
                LotQcInspection.deleted_at.is_(None),
                *lot_date_filters,
            )
        ).one()
        if int(qc_total):
            active_lots = int(
                db.scalar(
                    select(func.count(ProductionLot.id)).where(
                        ProductionLot.order_id == current_order_id,
                        ProductionLot.deleted_at.is_(None),
                    )
                )
                or 0
            )
            checked_lots = int(
                db.scalar(
                    select(func.count(LotQcInspection.id))
                    .join(ProductionLot, ProductionLot.id == LotQcInspection.production_lot_id)
                    .where(
                        ProductionLot.order_id == current_order_id,
                        ProductionLot.deleted_at.is_(None),
                        LotQcInspection.deleted_at.is_(None),
                        *lot_date_filters,
                    )
                )
                or 0
            )
            qc_by_order[current_order_id] = (
                int(qc_total) - int(ng_total),
                int(qc_total),
                active_lots > 0 and checked_lots >= active_lots,
            )
        else:
            inspection_date_filters = []
            if date_from:
                inspection_date_filters.append(QcInspection.inspected_date >= date_from)
            if date_to:
                inspection_date_filters.append(QcInspection.inspected_date <= date_to)
            candidate_ids = list(
                db.scalars(
                    select(QcInspection.id)
                    .join(DailyReport, DailyReport.id == QcInspection.daily_report_id)
                    .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
                    .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
                    .where(
                        ProductionSchedule.order_id == current_order_id,
                        QcInspection.deleted_at.is_(None),
                        DailyReport.deleted_at.is_(None),
                        BlankRequest.deleted_at.is_(None),
                        ProductionSchedule.deleted_at.is_(None),
                        *inspection_date_filters,
                    )
                )
            )
            complete_ids = [
                inspection_id
                for inspection_id in candidate_ids
                if qc_inspection_is_complete(db, inspection_id)
            ]
            if complete_ids:
                ng_total, qc_total = db.execute(
                    select(
                        func.coalesce(func.sum(QcPairResult.ng_scrap + QcPairResult.ng_repair), 0),
                        func.coalesce(func.sum(QcPairResult.quantity_in), 0),
                    )
                    .join(QcInspection, QcInspection.id == QcPairResult.qc_inspection_id)
                    .where(
                        QcInspection.id.in_(complete_ids),
                        QcInspection.deleted_at.is_(None),
                        QcPairResult.deleted_at.is_(None),
                    )
                ).one()
                qc_by_order[current_order_id] = (
                    int(qc_total) - int(ng_total),
                    int(qc_total),
                    len(complete_ids) == len(candidate_ids),
                )
            else:
                qc_by_order[current_order_id] = (None, 0, False)

    for row in report_rows:
        pair_id = row[0]
        quantity, ideal_seconds = db.execute(
            select(
                func.coalesce(func.sum(DailyReportLine.quantity_produced), 0),
                func.coalesce(
                    func.sum(
                        DailyReportLine.quantity_produced
                        * DailyReportLine.cycle_time_snapshot_seconds
                    ),
                    0,
                ),
            ).where(
                DailyReportLine.daily_report_pair_id == pair_id,
                DailyReportLine.deleted_at.is_(None),
            )
        ).one()
        downtime = (
            db.scalar(
                select(func.coalesce(func.sum(DowntimeEntry.minutes), 0)).where(
                    DowntimeEntry.daily_report_pair_id == pair_id,
                    DowntimeEntry.deleted_at.is_(None),
                )
            )
            or 0
        )
        qc_ok, qc_input, qc_complete = qc_by_order[row[3]]
        produced = int(quantity)
        planned = int(row[10])
        run = max(planned - int(downtime), 0)
        a = run / planned if planned else None
        p = float(ideal_seconds) / (run * 60) if run else None
        q = None
        oee = None
        output.append(
            {
                "date": row[1].isoformat(),
                "shift": row[2],
                "order_id": row[3],
                "po_no": row[4],
                "product_code": row[5],
                "machine_pair_id": row[6],
                "machine_pair": row[7],
                "employee_id": row[8],
                "employee_name": row[9],
                "planned_minutes": planned,
                "downtime_minutes": int(downtime),
                "run_minutes": run,
                "downtime_recorded": bool(row[11]),
                "produced": produced,
                "ideal_seconds": float(ideal_seconds),
                "qc_first_pass_ok": None,
                "qc_input": qc_input,
                "qc_order_first_pass_ok": qc_ok,
                "qc_order_input": qc_input,
                "qc_order_complete": qc_complete,
                "quality_scope_allowed": not machine_pair_id and not employee_id,
                "availability": a,
                "performance": p,
                "quality": q,
                "oee": oee,
                "performance_over_100": p is not None and p > 1,
            }
        )
    return output


def aggregate_oee(rows: list[dict[str, object]], group_by: str) -> list[dict[str, object]]:
    if group_by not in {"day", "month", "order", "product", "pair", "shift"}:
        raise ValueError("Chỉ được nhóm OEE theo ngày, tháng, PO, mã hàng, cặp máy hoặc kíp.")
    buckets: dict[object, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        key = {
            "day": row["date"],
            "month": str(row["date"])[:7],
            "order": row["po_no"],
            "product": row["product_code"],
            "pair": row["machine_pair"],
            "shift": row["shift"],
        }[group_by]
        buckets[key].append(row)
    results = []
    for key, items in buckets.items():
        planned = sum(int(row["planned_minutes"]) for row in items)
        downtime = sum(int(row["downtime_minutes"]) for row in items)
        run = sum(int(row["run_minutes"]) for row in items)
        ideal = sum(float(row["ideal_seconds"]) for row in items)
        produced = sum(int(row["produced"]) for row in items)
        a = run / planned if planned else None
        p = ideal / (run * 60) if run else None
        qc_order_rows = {row["order_id"]: row for row in items}
        qc_ok = sum(int(row["qc_order_first_pass_ok"] or 0) for row in qc_order_rows.values())
        qc_input = sum(int(row["qc_order_input"] or 0) for row in qc_order_rows.values())
        qc_complete = all(row["qc_order_complete"] for row in qc_order_rows.values())
        quality_scope = group_by == "order" and all(row["quality_scope_allowed"] for row in items)
        q = qc_ok / qc_input if quality_scope and qc_input and qc_complete else None
        results.append(
            {
                "group": key,
                "availability": a,
                "performance": p,
                "quality": q,
                "oee": a * p * q if a is not None and p is not None and q is not None else None,
                "planned_minutes": planned,
                "downtime_minutes": downtime,
                "run_minutes": run,
                "ideal_seconds": ideal,
                "produced": produced,
                "first_pass_ok": qc_ok if qc_input else None,
                "qc_pairs": sum(1 for row in items if row["qc_first_pass_ok"] is not None),
                "qc_complete": qc_complete,
                "quality_scope": quality_scope,
                "no_downtime_record_count": sum(1 for row in items if not row["downtime_recorded"]),
                "pair_shift_count": len(items),
                "no_downtime_record_percent": (
                    sum(1 for row in items if not row["downtime_recorded"]) / len(items) * 100
                    if items
                    else 0
                ),
            }
        )
    return sorted(results, key=lambda row: str(row["group"]))


def list_audit_log(
    db: Session,
    *,
    table_name: str | None = None,
    actor_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
) -> list[AuditLog]:
    query = select(AuditLog)
    if table_name:
        query = query.where(AuditLog.table_name == table_name)
    if actor_id:
        query = query.where(AuditLog.actor_id == actor_id)
    if date_from:
        query = query.where(func.date(AuditLog.created_at) >= date_from)
    if date_to:
        query = query.where(func.date(AuditLog.created_at) <= date_to)
    return list(
        db.scalars(query.order_by(AuditLog.created_at.desc()).limit(min(max(limit, 1), 500)))
    )


def _ng_row(row, stage: str, kind: str, quantity: int, complete: bool) -> dict[str, object]:
    return {
        "date": row[0].isoformat(),
        "shift": row[1],
        "order_id": row[2],
        "po_no": row[3],
        "product_code": row[4],
        "machine_pair": row[5] if stage == "QC" else None,
        "employee_code": row[6] if stage == "QC" else row[7],
        "stage": stage,
        "ng_kind": kind,
        "quantity": int(quantity),
        "qc_complete": complete,
    }
