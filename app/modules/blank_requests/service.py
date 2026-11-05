from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.modules.assets.models import Machine, MachineGroup, MachineGroupAssignment, MachinePair
from app.modules.auth.models import AuditLog
from app.modules.blank_requests.models import (
    BlankRequest,
    BlankRequestCounter,
    BlankRequestOperator,
    BlankRequestPair,
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

    group, operators = _validate_resources(
        db,
        data.machine_group_id,
        data.machine_pair_ids,
        data.operator_ids,
        now,
    )

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
        blank_quantity=data.blank_quantity,
        machine_group_id=group.id,
        status="submitted",
        created_at=now,
        updated_at=now,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(blank_request)
    db.flush()
    for pair_id in data.machine_pair_ids:
        link = BlankRequestPair(
            blank_request_id=blank_request.id,
            machine_pair_id=pair_id,
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
            {"blank_request_id": blank_request.id, "machine_pair_id": pair_id},
            "Chọn cặp máy cho yêu cầu phôi",
        )
    for employee in operators:
        link = BlankRequestOperator(
            blank_request_id=blank_request.id,
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
            "blank_request_operators",
            link.id,
            "create",
            None,
            {"blank_request_id": blank_request.id, "employee_id": employee.id},
            "Chọn người vận hành cho yêu cầu phôi",
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
            "blank_quantity": data.blank_quantity,
            "machine_group_id": group.id,
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
    group_is_unchanged = data.machine_group_id == blank_request.machine_group_id
    group, operators = _validate_resources(
        db,
        data.machine_group_id,
        data.machine_pair_ids,
        data.operator_ids,
        now,
        allowed_existing_pair_ids=set(current_pair_ids) if group_is_unchanged else set(),
        allowed_existing_operator_ids=set(current_operator_ids),
        allow_inactive_group=group_is_unchanged,
    )
    _replace_pair_links(db, blank_request, data.machine_pair_ids, actor_id, now)
    _replace_operator_links(db, blank_request, data.operator_ids, actor_id, now)
    blank_request.blank_quantity = data.blank_quantity
    blank_request.machine_group_id = group.id
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
        raise BlankRequestManagementError("Chỉ hủy được yêu cầu đang chờ kho giao.")
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


def get_blank_request(db: Session, request_id: int):
    return db.execute(
        select(BlankRequest, ProductionSchedule, ProductionOrder, Product, Shift, MachineGroup)
        .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
        .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(Shift, Shift.id == ProductionSchedule.shift_id)
        .join(MachineGroup, MachineGroup.id == BlankRequest.machine_group_id)
        .where(BlankRequest.id == request_id, BlankRequest.deleted_at.is_(None))
    ).first()


def can_edit_request(blank_request: BlankRequest, actor_role: str) -> bool:
    return blank_request.status == "submitted" or (
        actor_role == "admin" and blank_request.status == "delivered"
    )


def _validate_resources(
    db: Session,
    group_id: int,
    pair_ids: list[int],
    operator_ids: list[int],
    now: datetime,
    *,
    allowed_existing_pair_ids: set[int] | None = None,
    allowed_existing_operator_ids: set[int] | None = None,
    allow_inactive_group: bool = False,
):
    group = db.scalar(
        select(MachineGroup).where(
            MachineGroup.id == group_id,
            MachineGroup.deleted_at.is_(None),
            (MachineGroup.is_active.is_(True) | allow_inactive_group),
        )
    )
    if group is None:
        raise BlankRequestManagementError("Chọn nhóm máy đang sử dụng.")

    machine_1 = aliased(Machine)
    machine_2 = aliased(Machine)
    assignments = list(
        db.scalars(
            select(MachineGroupAssignment)
            .join(MachinePair, MachinePair.id == MachineGroupAssignment.machine_pair_id)
            .join(machine_1, machine_1.id == MachinePair.machine_1_id)
            .join(machine_2, machine_2.id == MachinePair.machine_2_id)
            .where(
                MachineGroupAssignment.machine_group_id == group_id,
                MachineGroupAssignment.valid_from <= now,
                or_(
                    MachineGroupAssignment.valid_to.is_(None), MachineGroupAssignment.valid_to > now
                ),
                MachineGroupAssignment.deleted_at.is_(None),
                MachinePair.is_active.is_(True),
                MachinePair.deleted_at.is_(None),
                machine_1.is_active.is_(True),
                machine_1.deleted_at.is_(None),
                machine_2.is_active.is_(True),
                machine_2.deleted_at.is_(None),
                MachinePair.id.in_(pair_ids),
            )
        )
    )
    assigned_pair_ids = {assignment.machine_pair_id for assignment in assignments}
    assigned_pair_ids.update((allowed_existing_pair_ids or set()) & set(pair_ids))
    if assigned_pair_ids != set(pair_ids):
        raise BlankRequestManagementError("Chỉ chọn cặp máy đang thuộc nhóm máy đã chọn.")

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
    return group, [operator_by_id[employee_id] for employee_id in operator_ids]


def _replace_pair_links(
    db: Session, blank_request: BlankRequest, pair_ids: list[int], actor_id: int, now: datetime
) -> None:
    current = list(
        db.scalars(
            select(BlankRequestPair).where(
                BlankRequestPair.blank_request_id == blank_request.id,
                BlankRequestPair.deleted_at.is_(None),
            )
        )
    )
    current_by_id = {link.machine_pair_id: link for link in current}
    requested = set(pair_ids)
    for pair_id, link in current_by_id.items():
        if pair_id in requested:
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
            {"blank_request_id": blank_request.id, "machine_pair_id": pair_id},
            {"deleted_at": now.isoformat()},
            "Gỡ cặp máy khỏi yêu cầu phôi",
        )
    for pair_id in requested - set(current_by_id):
        link = BlankRequestPair(
            blank_request_id=blank_request.id,
            machine_pair_id=pair_id,
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
            {"blank_request_id": blank_request.id, "machine_pair_id": pair_id},
            "Thêm cặp máy vào yêu cầu phôi",
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
        "machine_group_id": blank_request.machine_group_id,
        "machine_pair_ids": pair_ids,
        "operator_ids": operator_ids,
        "status": blank_request.status,
    }


def list_blank_requests(db: Session):
    return list(
        db.execute(
            select(
                BlankRequest,
                ProductionSchedule,
                ProductionOrder,
                Product,
                Shift,
                MachineGroup,
            )
            .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
            .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
            .join(Product, Product.id == ProductionOrder.product_id)
            .join(Shift, Shift.id == ProductionSchedule.shift_id)
            .join(MachineGroup, MachineGroup.id == BlankRequest.machine_group_id)
            .where(BlankRequest.deleted_at.is_(None))
            .order_by(BlankRequest.created_at.desc(), BlankRequest.id.desc())
        )
    )


def active_groups(db: Session) -> list[MachineGroup]:
    return list(
        db.scalars(
            select(MachineGroup)
            .where(MachineGroup.is_active.is_(True), MachineGroup.deleted_at.is_(None))
            .order_by(MachineGroup.code)
        )
    )


def active_pairs_for_group(db: Session, group_id: int):
    now = datetime.now(UTC)
    machine_1 = aliased(Machine)
    machine_2 = aliased(Machine)
    return list(
        db.execute(
            select(MachinePair, machine_1, machine_2)
            .join(MachineGroupAssignment, MachineGroupAssignment.machine_pair_id == MachinePair.id)
            .join(machine_1, machine_1.id == MachinePair.machine_1_id)
            .join(machine_2, machine_2.id == MachinePair.machine_2_id)
            .where(
                MachineGroupAssignment.machine_group_id == group_id,
                MachineGroupAssignment.valid_from <= now,
                or_(
                    MachineGroupAssignment.valid_to.is_(None), MachineGroupAssignment.valid_to > now
                ),
                MachineGroupAssignment.deleted_at.is_(None),
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


def request_pair_options(db: Session, group_id: int, selected_pair_ids: list[int]):
    options = {row[0].id: row for row in active_pairs_for_group(db, group_id)}
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
    for request_id, pair_id in db.execute(
        select(BlankRequestPair.blank_request_id, BlankRequestPair.machine_pair_id).where(
            BlankRequestPair.blank_request_id.in_(request_ids),
            BlankRequestPair.deleted_at.is_(None),
        )
    ):
        resources[request_id][0].append(pair_id)
    for request_id, employee_id in db.execute(
        select(BlankRequestOperator.blank_request_id, BlankRequestOperator.employee_id).where(
            BlankRequestOperator.blank_request_id.in_(request_ids),
            BlankRequestOperator.deleted_at.is_(None),
        )
    ):
        resources[request_id][1].append(employee_id)
    return resources


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
