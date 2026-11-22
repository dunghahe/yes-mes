from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.modules.assets.models import Machine, MachinePair
from app.modules.auth.models import AuditLog
from app.modules.blank_requests.models import (
    BlankRequest,
    BlankRequestCounter,
    BlankRequestOperator,
    BlankRequestPair,
    BlankRequestPrint,
)
from app.modules.blank_requests.schemas import BlankRequestCreate, BlankRequestUpdate
from app.modules.employees.models import Employee
from app.modules.orders.models import ProductionOrder
from app.modules.products.models import Product
from app.modules.schedules.models import ProductionSchedule
from app.modules.shifts.models import Shift

LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class BlankRequestManagementError(Exception):
    """A blank request business rule rejected the requested change."""


class ConcurrentBlankRequestChange(BlankRequestManagementError):
    """The request changed since the user loaded it."""


def create_blank_request(
    db: Session, data: BlankRequestCreate, actor_id: int, *, today: date | None = None
) -> BlankRequest:
    now = datetime.now(UTC)
    schedule = db.scalar(
        select(ProductionSchedule)
        .where(
            ProductionSchedule.id == data.schedule_id,
            ProductionSchedule.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if schedule is None:
        raise BlankRequestManagementError("Chọn dòng lịch đang sử dụng.")

    order = db.scalar(
        select(ProductionOrder)
        .where(ProductionOrder.id == schedule.order_id, ProductionOrder.deleted_at.is_(None))
        .with_for_update()
    )
    if order is None:
        raise BlankRequestManagementError("Không tìm thấy PO của lịch đã chọn.")
    if order.process_type == "BAVIA_ONLY":
        if data.machine_pair_ids or data.operator_ids:
            raise BlankRequestManagementError(
                "PO chỉ Bavia không cần khai báo máy hoặc người làm máy."
            )
        operators = []
    else:
        if not data.machine_pair_ids or not data.operator_ids:
            raise BlankRequestManagementError("Chọn ít nhất một cặp máy và người làm.")
        operators = _validate_resources(db, data.machine_pair_ids, data.operator_ids)

    counter_date = today or datetime.now(LOCAL_TZ).date()
    counter_insert = insert(BlankRequestCounter).values(
        counter_date=counter_date,
        last_number=0,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.execute(counter_insert.on_conflict_do_nothing(index_elements=["counter_date"]))
    counter = db.scalar(
        select(BlankRequestCounter)
        .where(BlankRequestCounter.counter_date == counter_date)
        .with_for_update()
    )
    old_number = counter.last_number
    counter.last_number += 1
    counter.updated_by = actor_id
    counter.updated_at = now
    req_no = f"YC-{counter_date:%y%m%d}-{counter.last_number:02d}"
    db.add(
        AuditLog(
            table_name="blank_request_counters",
            record_id=counter.id,
            action="update",
            old_values={"last_number": old_number},
            new_values={"last_number": counter.last_number},
            reason="Sinh số yêu cầu phôi",
            actor_id=actor_id,
        )
    )

    blank_request = BlankRequest(
        req_no=req_no,
        schedule_id=schedule.id,
        blank_quantity=None,
        status="submitted",
        created_at=now,
        updated_at=now,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(blank_request)
    db.flush()
    for pair_id, employee in zip(data.machine_pair_ids, operators, strict=True):
        link = BlankRequestPair(
            blank_request_id=blank_request.id,
            machine_pair_id=pair_id,
            employee_id=employee.id,
            created_at=now,
            updated_at=now,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(link)
        db.flush()
        _audit(
            db,
            actor_id,
            "blank_request_pairs",
            link.id,
            "create",
            None,
            {
                "blank_request_id": blank_request.id,
                "machine_pair_id": pair_id,
                "employee_id": employee.id,
            },
            "Chọn cặp máy và người làm cho yêu cầu phôi",
        )
    _audit(
        db,
        actor_id,
        "blank_requests",
        blank_request.id,
        "create",
        None,
        {
            "req_no": req_no,
            "schedule_id": schedule.id,
            "order_id": schedule.order_id,
            "machine_pair_ids": data.machine_pair_ids,
            "operator_ids": data.operator_ids,
            "status": "submitted",
        },
        "Kỹ thuật tạo yêu cầu xuất phôi",
    )
    return blank_request


def update_blank_request(
    db: Session,
    request_id: int,
    data: BlankRequestUpdate,
    actor_id: int,
    actor_role: str,
) -> BlankRequest:
    blank_request = db.scalar(
        select(BlankRequest)
        .where(BlankRequest.id == request_id, BlankRequest.deleted_at.is_(None))
        .with_for_update()
    )
    if blank_request is None:
        raise BlankRequestManagementError("Không tìm thấy yêu cầu phôi.")
    if blank_request.version != data.version:
        raise ConcurrentBlankRequestChange("Yêu cầu đã thay đổi. Hãy tải lại trang rồi thử lại.")
    if blank_request.status != "submitted" and not (
        actor_role == "admin" and blank_request.status == "delivered"
    ):
        raise BlankRequestManagementError(
            "Chỉ sửa yêu cầu đang chờ giao; yêu cầu đã giao chỉ Admin được sửa."
        )

    now = datetime.now(UTC)
    current_pair_ids, current_operator_ids = request_resources(db, [request_id])[request_id]
    old_values = _request_values(blank_request, current_pair_ids, current_operator_ids)
    schedule = db.get(ProductionSchedule, blank_request.schedule_id)
    order = db.get(ProductionOrder, schedule.order_id) if schedule else None
    if order is None or order.deleted_at is not None:
        raise BlankRequestManagementError("Không tìm thấy PO của yêu cầu phôi.")
    if order.process_type == "BAVIA_ONLY":
        if data.machine_pair_ids or data.operator_ids:
            raise BlankRequestManagementError(
                "PO chỉ Bavia không cần khai báo máy hoặc người làm máy."
            )
        operators = []
    else:
        if not data.machine_pair_ids or not data.operator_ids:
            raise BlankRequestManagementError("Chọn ít nhất một cặp máy và người làm.")
        operators = _validate_resources(
            db,
            data.machine_pair_ids,
            data.operator_ids,
            allowed_existing_pair_ids=set(current_pair_ids),
            allowed_existing_operator_ids=set(current_operator_ids),
        )
    _replace_pair_links(db, blank_request, data.machine_pair_ids, data.operator_ids, actor_id, now)
    blank_request.version += 1
    blank_request.updated_at = now
    blank_request.updated_by = actor_id
    _audit(
        db,
        actor_id,
        "blank_requests",
        blank_request.id,
        "update",
        old_values,
        _request_values(
            blank_request, data.machine_pair_ids, [employee.id for employee in operators]
        ),
        data.reason,
    )
    return blank_request


def cancel_blank_request(
    db: Session, request_id: int, reason: str, version: int, actor_id: int
) -> BlankRequest:
    blank_request = db.scalar(
        select(BlankRequest)
        .where(BlankRequest.id == request_id, BlankRequest.deleted_at.is_(None))
        .with_for_update()
    )
    if blank_request is None:
        raise BlankRequestManagementError("Không tìm thấy yêu cầu phôi.")
    if blank_request.version != version:
        raise ConcurrentBlankRequestChange("Yêu cầu đã thay đổi. Hãy tải lại trang rồi thử lại.")
    if blank_request.status != "submitted":
        raise BlankRequestManagementError("Chỉ hủy được yêu cầu đang chờ Kho NVL giao.")
    pair_ids, operator_ids = request_resources(db, [request_id])[request_id]
    old_values = _request_values(blank_request, pair_ids, operator_ids)
    now = datetime.now(UTC)
    blank_request.status = "cancelled"
    blank_request.version += 1
    blank_request.updated_at = now
    blank_request.updated_by = actor_id
    new_values = _request_values(blank_request, pair_ids, operator_ids)
    _audit(
        db,
        actor_id,
        "blank_requests",
        blank_request.id,
        "cancel",
        old_values,
        new_values,
        reason,
    )
    return blank_request


def confirm_delivery(
    db: Session,
    request_id: int,
    actual_quantity: int | None,
    version: int,
    actor_id: int,
) -> tuple[BlankRequest, bool]:
    order_id = db.scalar(
        select(ProductionSchedule.order_id)
        .join(BlankRequest, BlankRequest.schedule_id == ProductionSchedule.id)
        .where(BlankRequest.id == request_id, BlankRequest.deleted_at.is_(None))
    )
    if order_id is None:
        raise BlankRequestManagementError("Không tìm thấy PO của yêu cầu phôi.")
    order = db.scalar(
        select(ProductionOrder)
        .where(ProductionOrder.id == order_id, ProductionOrder.deleted_at.is_(None))
        .with_for_update()
    )
    if order is None:
        raise BlankRequestManagementError("Không tìm thấy PO của yêu cầu phôi.")
    blank_request = db.scalar(
        select(BlankRequest)
        .where(BlankRequest.id == request_id, BlankRequest.deleted_at.is_(None))
        .with_for_update()
    )
    if blank_request is None:
        raise BlankRequestManagementError("Không tìm thấy yêu cầu phôi.")
    if blank_request.version != version:
        raise ConcurrentBlankRequestChange("Yêu cầu đã thay đổi. Hãy tải lại trang rồi thử lại.")
    if blank_request.status != "submitted":
        raise BlankRequestManagementError("Chỉ xác nhận giao được yêu cầu đang chờ Kho NVL.")
    if actual_quantity is not None and actual_quantity <= 0:
        raise BlankRequestManagementError("Số lượng thực giao phải là số nguyên dương.")
    if not queue_print_count(db, request_id, "production"):
        raise BlankRequestManagementError("Cần gửi in biểu trước khi xác nhận giao phôi.")

    pair_ids, operator_ids = request_resources(db, [request_id])[request_id]
    old_values = _request_values(blank_request, pair_ids, operator_ids)
    now = datetime.now(UTC)
    blank_request.status = "delivered"
    blank_request.delivered_quantity = actual_quantity
    blank_request.delivered_at = now
    blank_request.delivered_by = actor_id
    blank_request.version += 1
    blank_request.updated_at = now
    blank_request.updated_by = actor_id
    new_values = _request_values(blank_request, pair_ids, operator_ids)
    _audit(
        db,
        actor_id,
        "blank_requests",
        blank_request.id,
        "deliver",
        old_values,
        new_values,
        "Kho NVL xác nhận đã giao phôi",
    )
    return blank_request, (
        blank_request.blank_quantity is not None
        and actual_quantity is not None
        and actual_quantity != blank_request.blank_quantity
    )


def get_blank_request(db: Session, request_id: int):
    return db.execute(
        select(BlankRequest, ProductionSchedule, ProductionOrder, Product, Shift)
        .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
        .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(Shift, Shift.id == ProductionSchedule.shift_id)
        .where(BlankRequest.id == request_id, BlankRequest.deleted_at.is_(None))
    ).first()


def can_edit_request(blank_request: BlankRequest, actor_role: str) -> bool:
    return blank_request.status == "submitted" or (
        actor_role == "admin" and blank_request.status == "delivered"
    )


def _validate_resources(
    db: Session,
    pair_ids: list[int],
    operator_ids: list[int],
    *,
    allowed_existing_pair_ids: set[int] | None = None,
    allowed_existing_operator_ids: set[int] | None = None,
):
    machine_1 = aliased(Machine)
    machine_2 = aliased(Machine)
    active_pair_ids = set(
        db.scalars(
            select(MachinePair.id)
            .join(machine_1, machine_1.id == MachinePair.machine_1_id)
            .join(machine_2, machine_2.id == MachinePair.machine_2_id)
            .where(
                MachinePair.is_active.is_(True),
                MachinePair.deleted_at.is_(None),
                machine_1.is_active.is_(True),
                machine_1.deleted_at.is_(None),
                machine_2.is_active.is_(True),
                machine_2.deleted_at.is_(None),
            )
        )
    )
    active_pair_ids.update(allowed_existing_pair_ids or set())
    if not set(pair_ids).issubset(active_pair_ids):
        raise BlankRequestManagementError("Chỉ chọn cặp máy đang sử dụng.")

    operators = list(
        db.scalars(
            select(Employee).where(
                Employee.id.in_(operator_ids),
                Employee.employee_type == "operator",
                Employee.is_active.is_(True),
                Employee.deleted_at.is_(None),
            )
        )
    )
    operator_by_id = {employee.id: employee for employee in operators}
    if allowed_existing_operator_ids:
        for employee in db.scalars(
            select(Employee).where(
                Employee.id.in_(allowed_existing_operator_ids & set(operator_ids)),
                Employee.employee_type == "operator",
            )
        ):
            operator_by_id.setdefault(employee.id, employee)
    if set(operator_by_id) != set(operator_ids):
        raise BlankRequestManagementError("Chỉ chọn nhân viên vận hành đang sử dụng.")
    return [operator_by_id[employee_id] for employee_id in operator_ids]


def _replace_pair_links(
    db: Session,
    blank_request: BlankRequest,
    pair_ids: list[int],
    employee_ids: list[int],
    actor_id: int,
    now: datetime,
) -> None:
    current = list(
        db.scalars(
            select(BlankRequestPair).where(
                BlankRequestPair.blank_request_id == blank_request.id,
                BlankRequestPair.deleted_at.is_(None),
            )
        )
    )
    requested = dict(zip(pair_ids, employee_ids, strict=True))
    current_by_id = {link.machine_pair_id: link for link in current}
    for pair_id, link in current_by_id.items():
        employee_id = requested.get(pair_id)
        if employee_id == link.employee_id:
            continue
        link.deleted_at = now
        link.updated_at = now
        link.updated_by = actor_id
        _audit(
            db,
            actor_id,
            "blank_request_pairs",
            link.id,
            "delete",
            {
                "blank_request_id": blank_request.id,
                "machine_pair_id": pair_id,
                "employee_id": link.employee_id,
            },
            {"deleted_at": now.isoformat()},
            "Gỡ cặp máy khỏi yêu cầu phôi",
        )
    for pair_id, employee_id in requested.items():
        if pair_id in current_by_id and current_by_id[pair_id].employee_id == employee_id:
            continue
        link = BlankRequestPair(
            blank_request_id=blank_request.id,
            machine_pair_id=pair_id,
            employee_id=employee_id,
            created_at=now,
            updated_at=now,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(link)
        db.flush()
        _audit(
            db,
            actor_id,
            "blank_request_pairs",
            link.id,
            "create",
            None,
            {
                "blank_request_id": blank_request.id,
                "machine_pair_id": pair_id,
                "employee_id": employee_id,
            },
            "Gán cặp máy và người vận hành cho yêu cầu phôi",
        )


def _replace_operator_links(
    db: Session, blank_request: BlankRequest, employee_ids: list[int], actor_id: int, now: datetime
) -> None:
    current = list(
        db.scalars(
            select(BlankRequestOperator).where(
                BlankRequestOperator.blank_request_id == blank_request.id,
                BlankRequestOperator.deleted_at.is_(None),
            )
        )
    )
    current_by_id = {link.employee_id: link for link in current}
    requested = set(employee_ids)
    for employee_id, link in current_by_id.items():
        if employee_id in requested:
            continue
        link.deleted_at = now
        link.updated_at = now
        link.updated_by = actor_id
        _audit(
            db,
            actor_id,
            "blank_request_operators",
            link.id,
            "delete",
            {"blank_request_id": blank_request.id, "employee_id": employee_id},
            {"deleted_at": now.isoformat()},
            "Gỡ người vận hành khỏi yêu cầu phôi",
        )
    for employee_id in requested - set(current_by_id):
        link = BlankRequestOperator(
            blank_request_id=blank_request.id,
            employee_id=employee_id,
            created_at=now,
            updated_at=now,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(link)
        db.flush()
        _audit(
            db,
            actor_id,
            "blank_request_operators",
            link.id,
            "create",
            None,
            {"blank_request_id": blank_request.id, "employee_id": employee_id},
            "Thêm người vận hành vào yêu cầu phôi",
        )


def _request_values(
    blank_request: BlankRequest, pair_ids: list[int], operator_ids: list[int]
) -> dict[str, object]:
    return {
        "req_no": blank_request.req_no,
        "schedule_id": blank_request.schedule_id,
        "blank_quantity": blank_request.blank_quantity,
        "machine_pair_ids": pair_ids,
        "operator_ids": operator_ids,
        "status": blank_request.status,
        "delivered_quantity": blank_request.delivered_quantity,
        "delivered_at": blank_request.delivered_at.isoformat()
        if blank_request.delivered_at
        else None,
        "delivered_by": blank_request.delivered_by,
    }


def list_blank_requests(
    db: Session,
    *,
    status: str | None = None,
    limit: int | None = None,
    offset: int = 0,
):
    query = (
        select(
            BlankRequest,
            ProductionSchedule,
            ProductionOrder,
            Product,
            Shift,
        )
        .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
        .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(Shift, Shift.id == ProductionSchedule.shift_id)
        .where(BlankRequest.deleted_at.is_(None))
        .order_by(BlankRequest.created_at.desc(), BlankRequest.id.desc())
        .offset(offset)
    )
    if status is not None:
        query = query.where(BlankRequest.status == status)
    if limit is not None:
        query = query.limit(limit)
    return list(db.execute(query))


def count_blank_request_rows(db: Session) -> int:
    return (
        db.scalar(select(func.count(BlankRequest.id)).where(BlankRequest.deleted_at.is_(None))) or 0
    )


def count_blank_requests(db: Session, *, status: str) -> int:
    return (
        db.scalar(
            select(func.count(BlankRequest.id)).where(
                BlankRequest.status == status,
                BlankRequest.deleted_at.is_(None),
            )
        )
        or 0
    )


def queue_print_stats(db: Session, request_ids: list[int]):
    stats: dict[int, dict[str, tuple[datetime | None, int]]] = {
        request_id: {
            "production": (None, 0),
            "qc": (None, 0),
        }
        for request_id in request_ids
    }
    if not request_ids:
        return stats
    for request_id, form_type, last_printed_at, print_count in db.execute(
        select(
            BlankRequestPrint.blank_request_id,
            BlankRequestPrint.form_type,
            func.max(BlankRequestPrint.printed_at),
            func.count(BlankRequestPrint.id),
        )
        .where(
            BlankRequestPrint.blank_request_id.in_(request_ids),
            BlankRequestPrint.deleted_at.is_(None),
        )
        .group_by(BlankRequestPrint.blank_request_id, BlankRequestPrint.form_type)
    ):
        stats[request_id][form_type] = (last_printed_at, print_count)
    return stats


def get_printable_request(db: Session, request_id: int):
    return db.execute(
        select(BlankRequest, ProductionSchedule, ProductionOrder, Product, Shift)
        .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
        .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(Shift, Shift.id == ProductionSchedule.shift_id)
        .where(BlankRequest.id == request_id, BlankRequest.deleted_at.is_(None))
    ).first()


def register_print(
    db: Session, request_id: int, form_type: str, actor_id: int
) -> tuple[BlankRequestPrint, object]:
    db.scalar(
        select(BlankRequest)
        .where(BlankRequest.id == request_id, BlankRequest.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = get_printable_request(db, request_id)
    if row is None:
        raise BlankRequestManagementError("Không tìm thấy yêu cầu phôi.")
    blank_request = row[0]
    if blank_request.status == "cancelled":
        raise BlankRequestManagementError("Không thể in yêu cầu đã hủy.")
    now = datetime.now(UTC)
    print_event = BlankRequestPrint(
        blank_request_id=blank_request.id,
        form_type=form_type,
        printed_at=now,
        printed_by=actor_id,
        created_at=now,
        updated_at=now,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(print_event)
    db.flush()
    _audit(
        db,
        actor_id,
        "blank_request_prints",
        print_event.id,
        "print",
        None,
        {
            "blank_request_id": blank_request.id,
            "req_no": blank_request.req_no,
            "form_type": form_type,
            "printed_at": now.isoformat(),
        },
        "Kho NVL in lại biểu"
        if queue_print_count(db, request_id, form_type) > 1
        else "Kho NVL in biểu",
    )
    return print_event, row


def queue_print_count(db: Session, request_id: int, form_type: str) -> int:
    return db.scalar(
        select(func.count(BlankRequestPrint.id)).where(
            BlankRequestPrint.blank_request_id == request_id,
            BlankRequestPrint.form_type == form_type,
            BlankRequestPrint.deleted_at.is_(None),
        )
    )


def print_resource_details(db: Session, request_id: int):
    assignments = request_pair_assignments(db, request_id)
    pair_ids = [pair_id for pair_id, _employee_id in assignments]
    _selected_pair_ids, operator_ids = request_resources(db, [request_id])[request_id]
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
    pairs = [pair_by_id[pair_id] for pair_id in pair_ids if pair_id in pair_by_id]
    employees_by_id = {
        employee.id: employee
        for employee in db.scalars(select(Employee).where(Employee.id.in_(operator_ids)))
    }
    pair_workers = [employees_by_id.get(employee_id) for _pair_id, employee_id in assignments]
    employees = list(
        db.scalars(select(Employee).where(Employee.id.in_(operator_ids)).order_by(Employee.code))
    )
    return pairs, employees, pair_workers


def active_pairs(db: Session):
    machine_1 = aliased(Machine)
    machine_2 = aliased(Machine)
    return list(
        db.execute(
            select(MachinePair, machine_1, machine_2)
            .join(machine_1, machine_1.id == MachinePair.machine_1_id)
            .join(machine_2, machine_2.id == MachinePair.machine_2_id)
            .where(
                MachinePair.is_active.is_(True),
                MachinePair.deleted_at.is_(None),
                machine_1.is_active.is_(True),
                machine_1.deleted_at.is_(None),
                machine_2.is_active.is_(True),
                machine_2.deleted_at.is_(None),
            )
            .order_by(MachinePair.id)
        ).unique()
    )


def active_operators(db: Session) -> list[Employee]:
    return list(
        db.scalars(
            select(Employee)
            .where(
                Employee.employee_type == "operator",
                Employee.is_active.is_(True),
                Employee.deleted_at.is_(None),
            )
            .order_by(Employee.code)
        )
    )


def request_pair_options(db: Session, selected_pair_ids: list[int]):
    options = {row[0].id: row for row in active_pairs(db)}
    if selected_pair_ids:
        machine_1 = aliased(Machine)
        machine_2 = aliased(Machine)
        historical = db.execute(
            select(MachinePair, machine_1, machine_2)
            .join(machine_1, machine_1.id == MachinePair.machine_1_id)
            .join(machine_2, machine_2.id == MachinePair.machine_2_id)
            .where(MachinePair.id.in_(selected_pair_ids))
        ).all()
        for row in historical:
            options.setdefault(row[0].id, row)
    return list(options.values())


def operators_for_request(db: Session, selected_employee_ids: list[int]) -> list[Employee]:
    query = select(Employee).where(
        Employee.employee_type == "operator",
        or_(
            and_(Employee.is_active.is_(True), Employee.deleted_at.is_(None)),
            Employee.id.in_(selected_employee_ids),
        ),
    )
    return list(db.scalars(query.order_by(Employee.code)))


def available_schedules(db: Session):
    return list(
        db.execute(
            select(ProductionSchedule, ProductionOrder, Product, Shift)
            .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
            .join(Product, Product.id == ProductionOrder.product_id)
            .join(Shift, Shift.id == ProductionSchedule.shift_id)
            .where(ProductionSchedule.deleted_at.is_(None))
            .order_by(
                ProductionSchedule.production_date.desc(), Shift.start_time, ProductionOrder.po_no
            )
        )
    )


def request_resources(
    db: Session, request_ids: list[int]
) -> dict[int, tuple[list[int], list[int]]]:
    resources = {request_id: ([], []) for request_id in request_ids}
    if not request_ids:
        return resources
    pair_workers: dict[int, list[tuple[int, int | None]]] = {key: [] for key in request_ids}
    for request_id, pair_id, employee_id in db.execute(
        select(
            BlankRequestPair.blank_request_id,
            BlankRequestPair.machine_pair_id,
            BlankRequestPair.employee_id,
        )
        .where(
            BlankRequestPair.blank_request_id.in_(request_ids),
            BlankRequestPair.deleted_at.is_(None),
        )
        .order_by(BlankRequestPair.id)
    ):
        resources[request_id][0].append(pair_id)
        pair_workers[request_id].append((pair_id, employee_id))
    legacy_operators: dict[int, list[int]] = {key: [] for key in request_ids}
    for request_id, employee_id in db.execute(
        select(BlankRequestOperator.blank_request_id, BlankRequestOperator.employee_id).where(
            BlankRequestOperator.blank_request_id.in_(request_ids),
            BlankRequestOperator.deleted_at.is_(None),
        )
    ):
        legacy_operators[request_id].append(employee_id)
    for request_id in request_ids:
        assignments = pair_workers[request_id]
        if (
            len(assignments) == 1
            and assignments[0][1] is None
            and len(legacy_operators[request_id]) == 1
        ):
            pair_id, _employee_id = assignments[0]
            pair_workers[request_id][0] = (pair_id, legacy_operators[request_id][0])
        resources[request_id][1].extend(
            employee_id for _pair_id, employee_id in pair_workers[request_id] if employee_id
        )
        if not any(employee_id for _pair_id, employee_id in pair_workers[request_id]):
            resources[request_id][1].extend(legacy_operators[request_id])
    return resources


def request_pair_assignments(db: Session, request_id: int) -> list[tuple[int, int | None]]:
    rows = list(
        db.execute(
            select(BlankRequestPair.machine_pair_id, BlankRequestPair.employee_id)
            .where(
                BlankRequestPair.blank_request_id == request_id,
                BlankRequestPair.deleted_at.is_(None),
            )
            .order_by(BlankRequestPair.id)
        )
    )
    if len(rows) != 1 or rows[0][1] is not None:
        return rows
    legacy_employee_ids = list(
        db.scalars(
            select(BlankRequestOperator.employee_id).where(
                BlankRequestOperator.blank_request_id == request_id,
                BlankRequestOperator.deleted_at.is_(None),
            )
        )
    )
    if len(legacy_employee_ids) == 1:
        return [(rows[0][0], legacy_employee_ids[0])]
    return rows


def _audit(
    db: Session,
    actor_id: int,
    table_name: str,
    record_id: int,
    action: str,
    old_values: dict[str, object] | None,
    new_values: dict[str, object],
    reason: str,
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
