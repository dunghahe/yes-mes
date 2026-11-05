import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.main import app
from app.modules.auth.models import LoginSession, User
from app.modules.auth.service import hash_password


def test_twenty_users_can_login_concurrently() -> None:
    usernames = [f"phase1-concurrent-{index:02d}" for index in range(20)]
    password_hash = hash_password("Concurrency-Test-2026!")
    now = datetime.now(UTC)

    with SessionLocal() as db:
        users = list(db.scalars(select(User).where(User.username.in_(usernames))))
        users_by_name = {user.username: user for user in users}
        for username in usernames:
            user = users_by_name.get(username)
            if user is None:
                user = User(
                    username=username,
                    display_name=username,
                    password_hash=password_hash,
                    role="data_entry",
                    is_active=True,
                    must_change_password=False,
                    password_changed_at=now,
                )
                db.add(user)
            else:
                user.deleted_at = None
                user.is_active = True
                user.password_hash = password_hash
                user.role = "data_entry"
                user.must_change_password = False
                user.password_changed_at = now
                user.failed_login_count = 0
                user.locked_until = None
                user.totp_enabled = False
                user.totp_secret_encrypted = None
        db.flush()
        user_ids = [users_by_name[name].id for name in usernames if name in users_by_name]
        user_ids.extend(
            user.id
            for user in db.scalars(select(User).where(User.username.in_(usernames)))
            if user.id not in user_ids
        )
        db.commit()

    barrier = Barrier(20)

    def login(username: str) -> int:
        with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
            login_page = client.get("/auth/login")
            csrf = re.search(r'name="csrf_token" value="([^\"]+)"', login_page.text).group(1)
            barrier.wait(timeout=20)
            response = client.post(
                "/auth/login",
                data={
                    "username": username,
                    "password": "Concurrency-Test-2026!",
                    "csrf_token": csrf,
                },
            )
            return response.status_code

    try:
        with ThreadPoolExecutor(max_workers=20) as executor:
            statuses = list(executor.map(login, usernames))
        assert statuses == [303] * 20
    finally:
        finished_at = datetime.now(UTC)
        with SessionLocal() as db:
            for session in db.scalars(
                select(LoginSession).where(LoginSession.user_id.in_(user_ids))
            ):
                session.revoked_at = finished_at
            for user in db.scalars(select(User).where(User.id.in_(user_ids))):
                user.is_active = False
                user.deleted_at = finished_at
                user.updated_at = finished_at
            db.commit()
