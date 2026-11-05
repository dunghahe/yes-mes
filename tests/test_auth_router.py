import re
from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import engine, get_db
from app.main import app
from app.modules.auth.dependencies import SESSION_COOKIE_NAME
from app.modules.auth.models import AuditLog, User
from app.modules.auth.service import hash_password, verify_password
from app.modules.auth.totp import totp_code_for_counter


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
            assert "mes_session=" in home_response.headers["set-cookie"]
            assert "content-security-policy" in home_response.headers
            assert "strict-transport-security" in home_response.headers
            logout_token = re.search(
                r'action="/auth/logout".*?name="csrf_token" value="([^"]+)"',
                home_response.text,
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
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        outer_transaction.rollback()
        connection.close()
        get_settings.cache_clear()
