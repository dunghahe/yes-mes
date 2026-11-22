import re
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.core.db import SessionLocal, get_db
from app.core.permissions import ROLE_PERMISSIONS, has_permission
from app.main import app
from app.modules.auth.dependencies import require_active_user
from app.modules.auth.models import User
from app.modules.users.models import PERMISSION_MODULES


@pytest.mark.parametrize("role", list(ROLE_PERMISSIONS))
def test_all_screens_respect_role_and_disable_sensitive_caching(role):
    db = SessionLocal()
    actor = User(
        username=f"screens-{uuid4().hex}",
        display_name="Kiểm tra quyền",
        password_hash="unused",
        role=role,
    )
    db.add(actor)
    db.flush()

    def identity(request: Request):
        request.state.current_user = actor
        request.state.extra_permissions = frozenset()
        request.state.navigation_access = {
            module: {
                action: has_permission(role, module, action)
                for action in ("view", "create", "edit", "delete", "deliver")
            }
            for module in (*PERMISSION_MODULES, "accounts")
        }
        return actor

    def database():
        yield db

    screens = [
        ("/", None, "view"),
        ("/orders", "orders", "view"),
        ("/schedules", "schedules", "view"),
        ("/schedules?view=list", "schedules", "view"),
        ("/blank-requests", "blank_requests", "view"),
        ("/daily-reports", "daily_reports", "view"),
        ("/qc", "qc", "view"),
        ("/repairs", "repairs", "view"),
        ("/reports", "reports", "view"),
        ("/master-data", "master", "view"),
        ("/audit-log/view", "audit", "view"),
        ("/warehouse/blank-requests", "blank_requests", "deliver"),
        ("/admin/users", "admin", "view"),
        ("/admin/products", "admin", "view"),
        ("/admin/machines", "admin", "view"),
        ("/admin/shifts", "admin", "view"),
        ("/admin/employees", "admin", "view"),
        ("/admin/defect-codes", "admin", "view"),
        ("/admin/downtime-reasons", "admin", "view"),
        ("/admin/form-templates", "admin", "view"),
    ]
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[require_active_user] = identity
    try:
        with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
            for path, module, action in screens:
                allowed = module is None or (
                    role == "admin" if module == "admin" else has_permission(role, module, action)
                )
                response = client.get(path)
                assert response.status_code == (200 if allowed else 403), (
                    role,
                    path,
                    response.text[:100],
                )
                assert response.headers["cache-control"] == "private, no-store"
                assert "unsafe-inline" not in response.headers["content-security-policy"]
                if allowed:
                    assert '<main id="main-content"' in response.text
                    assert ' style="' not in response.text
                    assets = re.findall(r'(?:src|href)="([^"]*/static/[^"]+)"', response.text)
                    assert assets and all(url.startswith('/static/') for url in assets)
            if role == "admin":
                page = client.get("/repairs")
                csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
                malformed = client.post(
                    "/repairs/rechecks",
                    content="{broken",
                    headers={"x-csrf-token": csrf, "content-type": "application/json"},
                )
                assert malformed.status_code == 400
                invalid = client.post(
                    "/repairs/rechecks",
                    json={
                        "repair_code": "SR-1",
                        "inspected_date": "2026-11-23",
                        "shift_id": 1,
                        "qc_employee_id": 1,
                        "quantity_in": 10,
                        "quantity_ok": 5,
                        "ng_scrap": 1,
                        "ng_repair": 1,
                    },
                    headers={"x-csrf-token": csrf},
                )
                assert invalid.status_code == 422
                assert "phải bằng" in invalid.json()["detail"][0]["msg"]
    finally:
        app.dependency_overrides.clear()
        db.rollback()
        db.close()
