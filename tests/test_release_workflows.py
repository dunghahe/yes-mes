from datetime import date, time
from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import select, text

from app.core.db import SessionLocal
from app.modules.assets.models import Machine, MachinePair
from app.modules.auth.models import AuditLog, User
from app.modules.blank_requests.schemas import BlankRequestCreate
from app.modules.blank_requests.service import (
    confirm_delivery,
    create_blank_request,
    register_print,
)
from app.modules.daily_reports.bavia_schemas import BaviaReportInput
from app.modules.daily_reports.bavia_service import BaviaReportError, save_bavia_report
from app.modules.daily_reports.schemas import DailyProductionReportCreate
from app.modules.daily_reports.service import (
    DailyReportError,
    create_daily_production_report,
    update_daily_production_report,
)
from app.modules.defects.models import DefectCode
from app.modules.employees.models import Employee
from app.modules.form_templates.service import (
    TEMPLATE_PATH,
    _replace_sheet_tokens,
    template_status,
    upload_template,
)
from app.modules.orders.models import ProductionLot
from app.modules.orders.schemas import OrderCreate
from app.modules.orders.service import create_order
from app.modules.products.models import Product
from app.modules.qc.schemas import LotQcInput
from app.modules.qc.service import QcInspectionError, save_lot_qc
from app.modules.repairs.schemas import RepairJobCreate, RepairRecheckCreate
from app.modules.repairs.service import (
    RepairWorkflowError,
    create_repair_job,
    create_repair_recheck,
    repair_balances,
)
from app.modules.reporting.router import _to_xlsx
from app.modules.reporting.service import po_summaries
from app.modules.schedules.models import ProductionSchedule
from app.modules.shifts.models import Shift


@pytest.fixture
def flow():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def _setup(db, process_type="SX_ONLY"):
    token = uuid4().hex[:12]
    actor = User(
        username=f"release-{token}", password_hash="unused", role="admin", display_name="Kiểm thử"
    )
    product = Product(code=f"P-{token}", name="Kiểm thử", cycle_time_seconds=3)
    shift = Shift(
        name=f"K-{token}",
        start_time=time(7),
        end_time=time(19),
        planned_break_minutes=0,
        crosses_midnight=False,
    )
    worker = Employee(code=f"W-{token}", name="Người làm", employee_type="operator")
    qc = Employee(code=f"Q-{token}", name="Người QC", employee_type="qc")
    m1 = Machine(code=f"A-{token}", name="Máy A", production_area="A")
    m2 = Machine(code=f"B-{token}", name="Máy B", production_area="A")
    defect = DefectCode(code=f"NG-{token}", name="Xước", detected_at="SX", defect_group="")
    db.add_all([actor, product, shift, worker, qc, m1, m2, defect])
    db.flush()
    pair = MachinePair(machine_1_id=m1.id, machine_2_id=m2.id)
    db.add(pair)
    db.flush()
    order = create_order(
        db,
        OrderCreate(
            po_no=f"PO-{token}",
            product_id=product.id,
            ordered_quantity=100,
            lot_size=100,
            process_type=process_type,
            raw_material_code="NVL",
            drawing_number="BV",
            revision="A",
            material="Thép",
            blank_size="10x20",
            order_received_date=date(2026, 11, 22),
        ),
        actor.id,
    )
    schedule = ProductionSchedule(
        production_date=date(2026, 11, 22),
        shift_id=shift.id,
        order_id=order.id,
        planned_quantity=100,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(schedule)
    db.flush()
    request = create_blank_request(
        db,
        BlankRequestCreate(
            schedule_id=schedule.id,
            machine_pair_ids=[pair.id],
            operator_ids=[worker.id],
        ),
        actor.id,
    )
    register_print(db, request.id, "production", actor.id)
    confirm_delivery(db, request.id, None, request.version, actor.id)
    report, _ = create_daily_production_report(
        db,
        DailyProductionReportCreate.model_validate(
            {
                "blank_request_id": request.id,
                "report_date": "2026-11-22",
                "shifts": [
                    {
                        "shift_id": shift.id,
                        "pairs": [
                            {
                                "source_machine_pair_id": pair.id,
                                "machine_pair_id": pair.id,
                                "employee_id": worker.id,
                                "quantity_produced": 100,
                            }
                        ],
                    }
                ],
            }
        ),
        actor.id,
    )
    lot = db.scalar(
        select(ProductionLot).where(
            ProductionLot.order_id == order.id, ProductionLot.deleted_at.is_(None)
        )
    )
    return dict(
        actor=actor,
        order=order,
        lot=lot,
        qc=qc,
        shift=shift,
        worker=worker,
        machine=m1,
        defect=defect,
        report=report,
        request=request,
        pair=pair,
    )


def _qc(f, ok, scrap=0, repair=0, version=0):
    defects = [
        {
            "defect_code_id": f["defect"].id,
            "machine_id": f["machine"].id,
            "disposition": kind,
            "quantity": qty,
        }
        for kind, qty in (("scrap", scrap), ("repair", repair))
        if qty
    ]
    return LotQcInput(
        inspected_date=date(2026, 11, 22),
        shift_id=f["shift"].id,
        qc_employee_id=f["qc"].id,
        version=version,
        quantity_ok=ok,
        quantity_ng=scrap + repair,
        ng_scrap=scrap,
        ng_repair=repair,
        defects=defects,
    )


def test_lot_qc_closes_reopens_and_audits_po(flow):
    f = _setup(flow)
    inspection = save_lot_qc(flow, f["lot"].lot_code, _qc(f, 100), f["actor"].id)
    assert f["order"].status == "done"
    assert (
        flow.execute(
            text("SELECT finished_quantity FROM v_po_summary WHERE order_id=:id"),
            {"id": f["order"].id},
        ).scalar_one()
        == 100
    )
    flow.flush()
    save_lot_qc(
        flow, f["lot"].lot_code, _qc(f, 99, scrap=1, version=inspection.version), f["actor"].id
    )
    assert f["order"].status == "in_progress"
    transitions = list(
        flow.scalars(
            select(AuditLog).where(
                AuditLog.table_name == "orders", AuditLog.record_id == f["order"].id
            )
        )
    )
    assert any(row.new_values.get("status") == "done" for row in transitions)
    assert any(row.old_values and row.old_values.get("status") == "done" for row in transitions)


def test_repair_returns_remain_in_original_lot_without_increasing_production(flow):
    f = _setup(flow)
    inspection = save_lot_qc(flow, f["lot"].lot_code, _qc(f, 80, 5, 15), f["actor"].id)
    job = create_repair_job(
        flow,
        RepairJobCreate(
            order_id=f["order"].id,
            production_lot_id=f["lot"].id,
            stage="QC",
            repair_employee_id=f["worker"].id,
            repair_date=date(2026, 11, 22),
            quantity_repaired=10,
        ),
        f["actor"].id,
    )
    assert job.repair_code.startswith("SR-")
    recheck = create_repair_recheck(
        flow,
        RepairRecheckCreate(
            repair_code=job.repair_code,
            inspected_date=date(2026, 11, 22),
            shift_id=f["shift"].id,
            qc_employee_id=f["qc"].id,
            quantity_in=10,
            quantity_ok=8,
            ng_scrap=1,
            ng_repair=1,
        ),
        f["actor"].id,
    )
    flow.flush()
    assert recheck.production_lot_id == f["lot"].id
    assert repair_balances(flow, f["order"].id, "QC", f["lot"].id)["repair_waiting"] == 6
    summary = (
        flow.execute(text("SELECT * FROM v_po_summary WHERE order_id=:id"), {"id": f["order"].id})
        .mappings()
        .one()
    )
    assert summary["finished_quantity"] == 88
    report_summary = next(row for row in po_summaries(flow) if row["order_id"] == f["order"].id)
    assert report_summary["finished_quantity"] == 88
    assert report_summary["produced"] == 100
    with pytest.raises(QcInspectionError, match="mang đi sửa"):
        save_lot_qc(flow, f["lot"].lot_code, _qc(f, 95, 0, 5, inspection.version), f["actor"].id)
    with pytest.raises(RepairWorkflowError, match="vượt"):
        create_repair_recheck(
            flow,
            RepairRecheckCreate(
                repair_code=job.repair_code,
                inspected_date=date(2026, 11, 22),
                shift_id=f["shift"].id,
                qc_employee_id=f["qc"].id,
                quantity_in=1,
                quantity_ok=1,
                ng_scrap=0,
                ng_repair=0,
            ),
            f["actor"].id,
        )


def test_full_bavia_uses_lot_ok_and_blocks_retroactive_shortage(flow):
    f = _setup(flow, "FULL")
    inspection = save_lot_qc(flow, f["lot"].lot_code, _qc(f, 80, 20), f["actor"].id)
    data = BaviaReportInput(
        order_id=f["order"].id,
        report_date=date(2026, 11, 22),
        shift_id=f["shift"].id,
        employee_id=f["worker"].id,
        quantity_produced=81,
    )
    with pytest.raises(BaviaReportError, match="vượt"):
        save_bavia_report(flow, data, f["actor"].id)
    save_bavia_report(flow, data.model_copy(update={"quantity_produced": 80}), f["actor"].id)
    flow.flush()
    with pytest.raises(QcInspectionError, match="Bavia"):
        save_lot_qc(
            flow, f["lot"].lot_code, _qc(f, 79, 21, version=inspection.version), f["actor"].id
        )


def test_production_cannot_drop_below_lots_already_checked(flow):
    f = _setup(flow)
    inspection = save_lot_qc(flow, f["lot"].lot_code, _qc(f, 100), f["actor"].id)
    with pytest.raises(QcInspectionError, match="vừa được cập nhật"):
        save_lot_qc(flow, f["lot"].lot_code, _qc(f, 100, version=0), f["actor"].id)
    assert inspection.version == 1
    data = DailyProductionReportCreate.model_validate(
        {
            "blank_request_id": f["request"].id,
            "report_date": "2026-11-22",
            "shifts": [
                {
                    "shift_id": f["shift"].id,
                    "pairs": [
                        {
                            "source_machine_pair_id": f["pair"].id,
                            "machine_pair_id": f["pair"].id,
                            "employee_id": f["worker"].id,
                            "quantity_produced": 99,
                        }
                    ],
                }
            ],
        }
    )
    with pytest.raises(DailyReportError, match="QC theo lô"):
        update_daily_production_report(
            flow, f["report"].id, data, f["report"].version, f["actor"].id
        )


def test_excel_exports_and_print_tokens_keep_formula_text_literal():
    hostile = '=HYPERLINK("https://example.invalid", "click")'
    exported = load_workbook(BytesIO(_to_xlsx([{"po": hostile}], "PO")), data_only=False)
    assert exported.active["A2"].value == hostile
    assert exported.active["A2"].data_type == "s"
    workbook = Workbook()
    workbook.active["A1"] = "@@po_no"
    _replace_sheet_tokens(workbook.active, {"po_no": hostile}, "LOT-001")
    stream = BytesIO()
    workbook.save(stream)
    rendered = load_workbook(BytesIO(stream.getvalue()), data_only=False)
    assert rendered.active["A1"].value == hostile
    assert rendered.active["A1"].data_type == "s"


def test_template_replacement_deactivates_previous_version_before_inserting(flow):
    actor = User(
        username=f"template-{uuid4().hex}",
        display_name="Admin thử",
        password_hash="unused",
        role="admin",
    )
    flow.add(actor)
    flow.flush()
    first = upload_template(flow, "mau-1.xlsx", TEMPLATE_PATH.read_bytes(), actor.id)
    second = upload_template(flow, "mau-2.xlsx", TEMPLATE_PATH.read_bytes(), actor.id)
    assert second.version == first.version + 1
    assert first.is_active is False
    assert template_status(flow).id == second.id
