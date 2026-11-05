import re
from collections.abc import Generator
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import engine, get_db
from app.main import app
from app.modules.assets.models import Machine, MachineGroup, MachineGroupAssignment, MachinePair
from app.modules.auth.dependencies import SESSION_COOKIE_NAME
from app.modules.auth.models import AuditLog, User
from app.modules.auth.service import hash_password, verify_password
from app.modules.auth.totp import totp_code_for_counter
from app.modules.blank_requests.models import (
    BlankRequest,
    BlankRequestOperator,
    BlankRequestPair,
    BlankRequestPrint,
)
from app.modules.defects.models import DefectCode
from app.modules.downtime.models import DowntimeReason
from app.modules.employees.models import Employee
from app.modules.orders.models import ProductionOrder
from app.modules.products.models import Product
from app.modules.schedules.models import ProductionSchedule
from app.modules.shifts.models import Shift


def test_login_protects_home_and_logout_revokes_session() -> None:
    connection = engine.connect()
    outer_transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    username = f"auth-router-{uuid4().hex}"
    user = User(
        username=username,
        display_name="Người dùng thử",
        password_hash=hash_password("MatKhauHopLe-123"),
        role="data_entry",
        must_change_password=False,
        password_changed_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()

    def override_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
            protected_response = client.get("/")
            assert protected_response.status_code == 303
            assert protected_response.headers["location"] == "/auth/login"

            login_page = client.get("/auth/login")
            token_match = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text)
            assert login_page.status_code == 200
            assert token_match is not None
            csrf_token = token_match.group(1)
            invalid_csrf = client.post(
                "/auth/login",
                data={
                    "username": username,
                    "password": "MatKhauHopLe-123",
                    "totp_code": "",
                    "csrf_token": "token-khong-hop-le",
                },
            )
            assert invalid_csrf.status_code == 403
            login_page = client.get("/auth/login")
            csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text).group(1)

            login_response = client.post(
                "/auth/login",
                data={
                    "username": username,
                    "password": "MatKhauHopLe-123",
                    "totp_code": "",
                    "csrf_token": csrf_token,
                },
            )
            assert login_response.status_code == 303
            assert login_response.headers["location"] == "/"
            assert SESSION_COOKIE_NAME in login_response.cookies
            cookie_header = login_response.headers["set-cookie"].lower()
            assert "secure" in cookie_header
            assert "httponly" in cookie_header
            assert "samesite=lax" in cookie_header

            home_response = client.get("/")
            assert home_response.status_code == 200
            assert "Người dùng thử" in home_response.text
            assert client.get("/admin/users").status_code == 403
            assert client.get("/admin/products").status_code == 403
            assert client.get("/admin/machines").status_code == 403
            assert client.get("/admin/employees").status_code == 403
            assert client.get("/admin/defect-codes").status_code == 403
            assert client.get("/admin/downtime-reasons").status_code == 403
            assert client.get("/admin/shifts").status_code == 403
            schedule_page = client.get("/schedules")
            assert schedule_page.status_code == 200
            assert 'method="post" action="/schedules"' not in schedule_page.text
            schedule_token = client.cookies.get("mes_csrf")
            assert schedule_token
            assert (
                client.post(
                    "/schedules",
                    data={
                        "csrf_token": schedule_token,
                        "production_dates": ["2026-11-05"],
                        "shift_id": 1,
                        "order_id": 1,
                        "planned_quantity": 1,
                    },
                ).status_code
                == 403
            )
            assert "mes_session=" in home_response.headers["set-cookie"]
            assert "content-security-policy" in home_response.headers
            assert "strict-transport-security" in home_response.headers
            logout_page = client.get("/")
            logout_token = re.search(
                r'action="/auth/logout".*?name="csrf_token" value="([^"]+)"',
                logout_page.text,
                re.DOTALL,
            )
            assert logout_token is not None
            logout_response = client.post(
                "/auth/logout", data={"csrf_token": logout_token.group(1)}
            )
            assert logout_response.status_code == 303
            assert logout_response.headers["location"] == "/auth/login"
            assert client.get("/").status_code == 303
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        outer_transaction.rollback()
        connection.close()


def test_order_routes_allow_planning_and_reject_data_entry() -> None:
    connection = engine.connect()
    outer_transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    username = f"planning-orders-{uuid4().hex}"
    user = User(
        username=username,
        display_name="Kế hoạch thử nghiệm",
        password_hash=hash_password("MatKhauHopLe-123"),
        role="planning",
        must_change_password=False,
        password_changed_at=datetime.now(UTC),
    )
    product = Product(
        code=f"ORD-{uuid4().hex}",
        name="Mã hàng PO thử",
        cycle_time_seconds=3,
        default_process_type="FULL",
        is_active=True,
    )
    shift = Shift(
        name=f"Kíp lịch {uuid4().hex}",
        start_time=time(7),
        end_time=time(15),
        planned_break_minutes=30,
        crosses_midnight=False,
        is_active=True,
    )
    db.add_all([user, product, shift])
    db.flush()

    def override_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
            login_page = client.get("/auth/login")
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', login_page.text).group(1)
            login = client.post(
                "/auth/login",
                data={
                    "username": username,
                    "password": "MatKhauHopLe-123",
                    "csrf_token": csrf,
                },
            )
            assert login.status_code == 303
            order_list = client.get("/orders")
            assert order_list.status_code == 200
            assert 'href="/orders/new"' in order_list.text
            form_page = client.get("/orders/new")
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', form_page.text).group(1)
            po_no = f"PO-{uuid4().hex}"
            response = client.post(
                "/orders",
                data={
                    "csrf_token": csrf,
                    "po_no": po_no,
                    "product_id": product.id,
                    "ordered_quantity": 120,
                    "process_type": "FULL",
                    "raw_material_code": "RM-01",
                    "drawing_number": "DWG-01",
                    "revision": "A",
                    "material": "Thép",
                    "blank_size": "10x20",
                    "order_received_date": "2026-11-05",
                    "notes": "",
                },
            )
            assert response.status_code == 303
            assert po_no in client.get("/orders").text
            order = db.query(ProductionOrder).filter_by(po_no=po_no).one()
            schedule_page = client.get("/schedules")
            schedule_csrf = re.search(
                r'name="csrf_token" value="([^\"]+)"', schedule_page.text
            ).group(1)
            scheduled = client.post(
                "/schedules",
                data={
                    "csrf_token": schedule_csrf,
                    "production_dates": ["2026-11-06", "2026-11-07"],
                    "shift_id": shift.id,
                    "order_id": order.id,
                    "planned_quantity": 50,
                },
            )
            assert scheduled.status_code == 200
            assert "Đã lưu 2 dòng lịch." in scheduled.text
            assert db.query(ProductionSchedule).filter_by(order_id=order.id).count() == 2
            day_view = client.get(
                f"/schedules?view=day&on=2026-11-06&shift_id={shift.id}&order_id={order.id}"
            )
            assert day_view.status_code == 200
            assert "Ngày này chưa có lịch sản xuất." not in day_view.text
            assert po_no in day_view.text
            week_view = client.get("/schedules?view=week&on=2026-11-06")
            assert "Thứ 2" in week_view.text
            assert po_no in week_view.text
            month_view = client.get("/schedules?view=month&on=2026-11-01")
            assert "Tháng 11/2026" in month_view.text

        data_entry = User(
            username=f"operator-orders-{uuid4().hex}",
            display_name="Nhập liệu thử nghiệm",
            password_hash=hash_password("MatKhauHopLe-123"),
            role="data_entry",
            must_change_password=False,
            password_changed_at=datetime.now(UTC),
        )
        db.add(data_entry)
        db.flush()
        with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
            login_page = client.get("/auth/login")
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', login_page.text).group(1)
            login = client.post(
                "/auth/login",
                data={
                    "username": data_entry.username,
                    "password": "MatKhauHopLe-123",
                    "csrf_token": csrf,
                },
            )
            assert login.status_code == 303
            order_list = client.get("/orders")
            assert order_list.status_code == 200
            assert 'href="/orders/new"' not in order_list.text
            assert client.get("/orders/new").status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        outer_transaction.rollback()
        connection.close()


def test_admin_first_login_forces_password_change_and_totp_setup(
    monkeypatch,
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("TOTP_ENCRYPTION_KEYS", encryption_key)
    get_settings.cache_clear()

    connection = engine.connect()
    outer_transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    username = f"auth-admin-{uuid4().hex}"
    db.add(
        User(
            username=username,
            display_name="Admin thử nghiệm",
            password_hash=hash_password("MatKhauTam-123"),
            role="admin",
            must_change_password=True,
        )
    )
    db.flush()

    def override_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
            login_page = client.get("/auth/login")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text).group(1)
            login_response = client.post(
                "/auth/login",
                data={"username": username, "password": "MatKhauTam-123", "csrf_token": csrf},
            )
            assert login_response.status_code == 303
            assert login_response.headers["location"] == "/auth/change-password"
            assert client.get("/").headers["location"] == "/auth/change-password"

            password_page = client.get("/auth/change-password")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', password_page.text).group(1)
            changed = client.post(
                "/auth/change-password",
                data={
                    "csrf_token": csrf,
                    "current_password": "MatKhauTam-123",
                    "new_password": "MatKhauMoi-123",
                    "confirm_password": "MatKhauMoi-123",
                },
            )
            assert changed.status_code == 303
            assert changed.headers["location"] == "/auth/totp/setup"

            setup_page = client.get("/auth/totp/setup")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', setup_page.text).group(1)
            begun = client.post("/auth/totp/setup/begin", data={"csrf_token": csrf})
            secret_match = re.search(r"<code>([A-Z2-7]{24,40})</code>", begun.text)
            assert begun.status_code == 200
            assert secret_match is not None
            secret = secret_match.group(1)
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', begun.text).group(1)
            counter = int(datetime.now(UTC).timestamp() // 30)
            code = totp_code_for_counter(secret, counter)
            confirmed = client.post(
                "/auth/totp/setup/confirm",
                data={"csrf_token": csrf, "code": code},
            )
            assert confirmed.status_code == 200
            assert "Mã dự phòng TOTP" in confirmed.text
            recovery_codes = re.findall(r"<li><code>([0-9a-f]{24})</code></li>", confirmed.text)
            assert len(recovery_codes) == 10
            home_response = client.get("/")
            assert home_response.status_code == 200
            logout_csrf = re.search(
                r'action="/auth/logout".*?name="csrf_token" value="([^"]+)"',
                home_response.text,
                re.DOTALL,
            ).group(1)
            client.post("/auth/logout", data={"csrf_token": logout_csrf})

            login_page = client.get("/auth/login")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text).group(1)
            missing_totp = client.post(
                "/auth/login",
                data={
                    "username": username,
                    "password": "MatKhauMoi-123",
                    "totp_code": "",
                    "csrf_token": csrf,
                },
            )
            assert missing_totp.status_code == 401
            assert "mã xác thực không đúng" in missing_totp.text

            login_page = client.get("/auth/login")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text).group(1)
            recovery_login = client.post(
                "/auth/login",
                data={
                    "username": username,
                    "password": "MatKhauMoi-123",
                    "totp_code": recovery_codes[0],
                    "csrf_token": csrf,
                },
            )
            assert recovery_login.status_code == 303
            assert recovery_login.headers["location"] == "/"

            users_page = client.get("/admin/users")
            assert users_page.status_code == 200
            new_user_page = client.get("/admin/users/new")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', new_user_page.text).group(1)
            created_username = f"operator-created-{uuid4().hex}"
            created = client.post(
                "/admin/users",
                data={
                    "csrf_token": csrf,
                    "username": created_username,
                    "display_name": "Nhân viên vận hành",
                    "role": "data_entry",
                },
            )
            assert created.status_code == 200
            temporary_password = re.search(
                r'<code class="temporary-password">([^<]+)</code>', created.text
            ).group(1)
            assert created.headers["cache-control"] == "private, no-store"
            assert len(temporary_password) >= 24
            created_user = db.query(User).filter_by(username=created_username).one()
            assert created_user.must_change_password
            assert verify_password(temporary_password, created_user.password_hash)
            audit = (
                db.query(AuditLog).filter_by(table_name="users", record_id=created_user.id).one()
            )
            assert temporary_password not in str(audit.new_values)

            product_page = client.get("/admin/products/new")
            assert product_page.status_code == 200
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', product_page.text).group(1)
            product_code = f"SP-{uuid4().hex[:12]}"
            created_product = client.post(
                "/admin/products",
                data={
                    "csrf_token": csrf,
                    "code": product_code,
                    "name": "Sản phẩm thử nghiệm",
                    "cycle_time_seconds": "4.25",
                    "default_process_type": "FULL",
                },
            )
            assert created_product.status_code == 303
            product = db.query(Product).filter_by(code=product_code).one()
            assert str(product.cycle_time_seconds) == "4.250"
            product_audit = (
                db.query(AuditLog).filter_by(table_name="products", record_id=product.id).one()
            )
            assert product_audit.actor_id is not None
            assert product_audit.new_values["default_process_type"] == "FULL"

            assets_page = client.get("/admin/machines")
            assert assets_page.status_code == 200
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', assets_page.text).group(1)
            asset_key = uuid4().hex[:12]
            first_machine_code = f"M1-{asset_key}"
            second_machine_code = f"M2-{asset_key}"
            for machine_code, area in (
                (first_machine_code, "Khu A"),
                (second_machine_code, "Khu B"),
            ):
                response = client.post(
                    "/admin/machines/machines",
                    data={
                        "csrf_token": csrf,
                        "code": machine_code,
                        "name": f"Máy {machine_code}",
                        "production_area": area,
                    },
                )
                assert response.status_code == 303
            group_code = f"G-{asset_key}"
            response = client.post(
                "/admin/machines/groups",
                data={"csrf_token": csrf, "code": group_code, "name": "Nhóm máy thử"},
            )
            assert response.status_code == 303
            first_machine = db.query(Machine).filter_by(code=first_machine_code).one()
            second_machine = db.query(Machine).filter_by(code=second_machine_code).one()
            group = db.query(MachineGroup).filter_by(code=group_code).one()
            response = client.post(
                "/admin/machines/pairs",
                data={
                    "csrf_token": csrf,
                    "machine_1_id": first_machine.id,
                    "machine_2_id": second_machine.id,
                },
            )
            assert response.status_code == 303
            pair = (
                db.query(MachinePair)
                .filter_by(
                    machine_1_id=min(first_machine.id, second_machine.id),
                    machine_2_id=max(first_machine.id, second_machine.id),
                )
                .one()
            )
            response = client.post(
                f"/admin/machines/pairs/{pair.id}/group",
                data={"csrf_token": csrf, "machine_group_id": group.id},
            )
            assert response.status_code == 303
            assert group.name in client.get("/admin/machines").text

            employee_page = client.get("/admin/employees")
            assert employee_page.status_code == 200
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', employee_page.text).group(1)
            employee_code = f"NV-{asset_key}"
            created_employee = client.post(
                "/admin/employees",
                data={
                    "csrf_token": csrf,
                    "code": employee_code,
                    "name": "Nhân viên thử nghiệm",
                    "employee_type": "operator",
                },
            )
            assert created_employee.status_code == 303
            employee = db.query(Employee).filter_by(code=employee_code).one()
            employee_audit = (
                db.query(AuditLog).filter_by(table_name="employees", record_id=employee.id).one()
            )
            assert employee_audit.new_values["employee_type"] == "operator"

            defect_page = client.get("/admin/defect-codes")
            assert defect_page.status_code == 200
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', defect_page.text).group(1)
            defect_code = f"NG-{asset_key}"
            created_defect = client.post(
                "/admin/defect-codes",
                data={
                    "csrf_token": csrf,
                    "code": defect_code,
                    "name": "Xước bề mặt",
                    "defect_group": "Ngoại quan",
                    "detected_at": "SX",
                },
            )
            assert created_defect.status_code == 303
            defect = db.query(DefectCode).filter_by(code=defect_code).one()
            defect_audit = (
                db.query(AuditLog).filter_by(table_name="defect_codes", record_id=defect.id).one()
            )
            assert defect_audit.new_values["detected_at"] == "SX"

            downtime_page = client.get("/admin/downtime-reasons")
            assert downtime_page.status_code == 200
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', downtime_page.text).group(1)
            reason_code = f"CUSTOM-{asset_key}"
            created_reason = client.post(
                "/admin/downtime-reasons",
                data={"csrf_token": csrf, "code": reason_code, "name": "Chờ vật tư phụ"},
            )
            assert created_reason.status_code == 303
            assert db.query(DowntimeReason).filter_by(code=reason_code).one().is_active

            shift_page = client.get("/admin/shifts")
            assert shift_page.status_code == 200
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', shift_page.text).group(1)
            created_shift = client.post(
                "/admin/shifts",
                data={
                    "csrf_token": csrf,
                    "name": f"Kíp đêm {asset_key}",
                    "start_time": "22:00",
                    "end_time": "06:00",
                    "planned_break_minutes": 30,
                    "crosses_midnight": "true",
                },
            )
            assert created_shift.status_code == 303
            shift = db.query(Shift).filter_by(name=f"Kíp đêm {asset_key}").one()
            shift_audit = (
                db.query(AuditLog).filter_by(table_name="shifts", record_id=shift.id).one()
            )
            assert shift.crosses_midnight
            assert shift_audit.new_values["crosses_midnight"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        outer_transaction.rollback()
        connection.close()
        get_settings.cache_clear()


def test_engineering_can_create_blank_request_and_warehouse_can_only_view() -> None:
    connection = engine.connect()
    outer_transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    now = datetime.now(UTC)
    engineering = User(
        username=f"engineering-request-{uuid4().hex}",
        display_name="Kỹ thuật yêu cầu",
        password_hash=hash_password("MatKhauHopLe-123"),
        role="engineering",
        must_change_password=False,
        password_changed_at=now,
    )
    warehouse = User(
        username=f"warehouse-request-{uuid4().hex}",
        display_name="Kho xem yêu cầu",
        password_hash=hash_password("MatKhauHopLe-123"),
        role="warehouse",
        must_change_password=False,
        password_changed_at=now,
    )
    data_entry = User(
        username=f"data-entry-request-{uuid4().hex}",
        display_name="Nhập liệu sửa yêu cầu",
        password_hash=hash_password("MatKhauHopLe-123"),
        role="data_entry",
        must_change_password=False,
        password_changed_at=now,
    )
    product = Product(
        code=f"BR-{uuid4().hex}",
        name="Sản phẩm yêu cầu",
        cycle_time_seconds=3,
        default_process_type="FULL",
        is_active=True,
    )
    shift = Shift(
        name=f"Kíp YC {uuid4().hex}",
        start_time=time(7),
        end_time=time(15),
        planned_break_minutes=30,
        crosses_midnight=False,
        is_active=True,
    )
    group = MachineGroup(code=f"G-{uuid4().hex}", name="Nhóm YC", is_active=True)
    machine_1 = Machine(code=f"M1-{uuid4().hex[:8]}", name="Máy YC 1", production_area="Khu A")
    machine_2 = Machine(code=f"M2-{uuid4().hex[:8]}", name="Máy YC 2", production_area="Khu A")
    operator = Employee(
        code=f"NV-{uuid4().hex}", name="Vận hành YC", employee_type="operator", is_active=True
    )
    db.add_all(
        [engineering, warehouse, data_entry, product, shift, group, machine_1, machine_2, operator]
    )
    db.flush()
    pair = MachinePair(
        machine_1_id=min(machine_1.id, machine_2.id),
        machine_2_id=max(machine_1.id, machine_2.id),
        is_active=True,
    )
    db.add(pair)
    db.flush()
    db.add(
        MachineGroupAssignment(
            machine_pair_id=pair.id,
            machine_group_id=group.id,
            valid_from=now - timedelta(days=1),
            created_by=engineering.id,
            updated_by=engineering.id,
        )
    )
    order = ProductionOrder(
        po_no=f"PO-{uuid4().hex}",
        product_id=product.id,
        ordered_quantity=50,
        process_type="FULL",
        raw_material_code="RM-01",
        drawing_number="DWG-01",
        revision="A",
        material="Thép",
        blank_size="10x20",
        order_received_date=now.date(),
        created_by=engineering.id,
        updated_by=engineering.id,
    )
    db.add(order)
    db.flush()
    schedule = ProductionSchedule(
        production_date=now.date(),
        shift_id=shift.id,
        order_id=order.id,
        planned_quantity=50,
        created_by=engineering.id,
        updated_by=engineering.id,
    )
    db.add(schedule)
    db.flush()

    def override_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
            login_page = client.get("/auth/login")
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', login_page.text).group(1)
            login = client.post(
                "/auth/login",
                data={
                    "username": engineering.username,
                    "password": "MatKhauHopLe-123",
                    "csrf_token": csrf,
                },
            )
            assert login.status_code == 303
            request_page = client.get(
                f"/blank-requests/new?schedule_id={schedule.id}&machine_group_id={group.id}"
            )
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', request_page.text).group(1)
            assert machine_1.code in request_page.text
            created = client.post(
                "/blank-requests",
                data={
                    "csrf_token": csrf,
                    "schedule_id": schedule.id,
                    "blank_quantity": 40,
                    "machine_group_id": group.id,
                    "machine_pair_ids": [pair.id],
                    "operator_ids": [operator.id],
                },
            )
            assert created.status_code == 303
            blank_request = db.query(BlankRequest).one()
            assert blank_request.status == "submitted"
            assert re.fullmatch(r"YC-\d{6}-01", blank_request.req_no)
            assert (
                db.query(BlankRequestPair).filter_by(blank_request_id=blank_request.id).count() == 1
            )
            assert (
                db.query(BlankRequestOperator).filter_by(blank_request_id=blank_request.id).count()
                == 1
            )
            delivered_request = blank_request
            request_page = client.get(
                f"/blank-requests/new?schedule_id={schedule.id}&machine_group_id={group.id}"
            )
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', request_page.text).group(1)
            second_created = client.post(
                "/blank-requests",
                data={
                    "csrf_token": csrf,
                    "schedule_id": schedule.id,
                    "blank_quantity": 40,
                    "machine_group_id": group.id,
                    "machine_pair_ids": [pair.id],
                    "operator_ids": [operator.id],
                },
            )
            assert second_created.status_code == 303
            blank_request = db.query(BlankRequest).order_by(BlankRequest.id.desc()).first()

        with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
            login_page = client.get("/auth/login")
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', login_page.text).group(1)
            login = client.post(
                "/auth/login",
                data={
                    "username": warehouse.username,
                    "password": "MatKhauHopLe-123",
                    "csrf_token": csrf,
                },
            )
            assert login.status_code == 303
            queue_page = client.get("/warehouse/blank-requests")
            assert queue_page.status_code == 200
            assert "2" in re.search(r'id="queue-count"[^>]*>(.*?)</span>', queue_page.text).group(1)
            assert client.get("/warehouse/blank-requests/queue-fragment").status_code == 200
            production_print = client.get(
                f"/warehouse/blank-requests/{delivered_request.id}/print/production"
            )
            qc_print = client.get(f"/warehouse/blank-requests/{delivered_request.id}/print/qc")
            assert production_print.status_code == qc_print.status_code == 200
            assert delivered_request.req_no in production_print.text
            assert delivered_request.req_no in qc_print.text
            assert "data:image/png;base64," in production_print.text
            assert (
                db.query(BlankRequestPrint).filter_by(blank_request_id=delivered_request.id).count()
                == 2
            )
            delivery_page = client.get(f"/warehouse/blank-requests/{delivered_request.id}/delivery")
            assert delivery_page.status_code == 200
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', delivery_page.text).group(1)
            delivered = client.post(
                f"/warehouse/blank-requests/{delivered_request.id}/delivery",
                data={
                    "csrf_token": csrf,
                    "version": delivered_request.version,
                    "actual_quantity": 38,
                },
            )
            assert delivered.status_code == 303
            assert "quantity_mismatch=1" in delivered.headers["location"]
            assert delivered_request.status == "delivered"
            assert delivered_request.delivered_quantity == 38

        with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
            login_page = client.get("/auth/login")
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', login_page.text).group(1)
            login = client.post(
                "/auth/login",
                data={
                    "username": data_entry.username,
                    "password": "MatKhauHopLe-123",
                    "csrf_token": csrf,
                },
            )
            assert login.status_code == 303
            assert client.get("/warehouse/blank-requests").status_code == 403
            assert (
                client.get(
                    f"/warehouse/blank-requests/{blank_request.id}/print/production"
                ).status_code
                == 403
            )
            assert (
                client.get(f"/warehouse/blank-requests/{delivered_request.id}/delivery").status_code
                == 403
            )
            edit_page = client.get(f"/blank-requests/{blank_request.id}")
            assert edit_page.status_code == 200
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', edit_page.text).group(1)
            updated = client.post(
                f"/blank-requests/{blank_request.id}",
                data={
                    "csrf_token": csrf,
                    "version": blank_request.version,
                    "blank_quantity": 35,
                    "machine_group_id": group.id,
                    "machine_pair_ids": [pair.id],
                    "operator_ids": [operator.id],
                    "reason": "Sửa theo giấy mới",
                },
            )
            assert updated.status_code == 303
            assert blank_request.blank_quantity == 35
            assert blank_request.version == 2
            cancel_page = client.get(f"/blank-requests/{blank_request.id}")
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', cancel_page.text).group(1)
            cancelled = client.post(
                f"/blank-requests/{blank_request.id}/cancel",
                data={
                    "csrf_token": csrf,
                    "version": blank_request.version,
                    "reason": "Kế hoạch xác nhận hủy",
                },
            )
            assert cancelled.status_code == 303
            assert blank_request.status == "cancelled"
            assert client.get(f"/blank-requests/{blank_request.id}").status_code == 403

        with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
            login_page = client.get("/auth/login")
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', login_page.text).group(1)
            login = client.post(
                "/auth/login",
                data={
                    "username": warehouse.username,
                    "password": "MatKhauHopLe-123",
                    "csrf_token": csrf,
                },
            )
            assert login.status_code == 303
            assert client.get("/blank-requests").status_code == 200
            assert client.get("/blank-requests/new").status_code == 403
            queue_page = client.get("/warehouse/blank-requests")
            assert queue_page.status_code == 200
            assert "0" in re.search(r'id="queue-count"[^>]*>(.*?)</span>', queue_page.text).group(1)
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        outer_transaction.rollback()
        connection.close()
