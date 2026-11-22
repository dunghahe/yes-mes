import html
import json
import re

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_release_workflows import _qc, _setup

from app.core.db import engine, get_db
from app.core.permissions import has_permission
from app.main import app
from app.modules.auth.dependencies import require_active_user
from app.modules.daily_reports.bavia_schemas import BaviaReportInput
from app.modules.daily_reports.bavia_service import save_bavia_report
from app.modules.qc.service import save_lot_qc
from app.modules.users.models import PERMISSION_MODULES, UserPermission


def test_invalid_production_keeps_submitted_payload_and_create_cannot_edit_bavia():
    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    f = _setup(db, "FULL")
    save_lot_qc(db, f["lot"].lot_code, _qc(f, 80, 20), f["actor"].id)
    bavia_data = BaviaReportInput(
        order_id=f["order"].id,
        report_date=f["report"].report_date,
        shift_id=f["shift"].id,
        employee_id=f["worker"].id,
        quantity_produced=80,
    )
    bavia = save_bavia_report(db, bavia_data, f["actor"].id)
    db.commit()
    extras = frozenset()

    def identity(request: Request):
        request.state.current_user = f["actor"]
        request.state.extra_permissions = extras
        request.state.navigation_access = {
            module: {
                action: has_permission(f["actor"].role, module, action, extras)
                for action in ("view", "create", "edit", "delete", "deliver")
            }
            for module in (*PERMISSION_MODULES, "accounts")
        }
        return f["actor"]

    def database():
        yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[require_active_user] = identity
    try:
        with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
            page = client.get(f"/daily-reports?request_number={f['request'].req_no}")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            payload = json.dumps(
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
                                    "quantity_produced": -1,
                                }
                            ],
                        }
                    ],
                }
            )
            response = client.post(
                f"/daily-reports/{f['report'].id}",
                data={
                    "csrf_token": csrf,
                    "request_number": f["request"].req_no,
                    "report_payload": payload,
                    "version": f["report"].version,
                },
            )
            assert response.status_code == 422
            stored = re.search(r'name="report_payload" value="([^"]*)"', response.text).group(1)
            assert json.loads(html.unescape(stored)) == json.loads(payload)

            f["actor"].role = "planning"
            db.add(
                UserPermission(
                    user_id=f["actor"].id,
                    module="daily_reports",
                    can_view=True,
                    can_create=True,
                    can_edit=False,
                    can_delete=False,
                )
            )
            db.flush()
            extras = frozenset({("daily_reports", "view"), ("daily_reports", "create")})
            api = client.post(
                "/bavia-reports",
                json=bavia_data.model_copy(
                    update={"quantity_produced": 79, "version": bavia.version}
                ).model_dump(mode="json"),
                headers={"x-csrf-token": csrf},
            )
            assert api.status_code == 403
            # Omitting the record ID must not turn an update into an allowed create.
            form = client.post(
                "/daily-reports/bavia",
                data={
                    "csrf_token": csrf,
                    "request_number": f["request"].req_no,
                    "report_date": "2026-11-22",
                    "shift_id": f["shift"].id,
                    "employee_id": f["worker"].id,
                    "quantity_produced": 79,
                    "version": bavia.version,
                },
            )
            assert form.status_code == 403
            db.refresh(bavia)
            assert bavia.quantity_produced == 80
    finally:
        app.dependency_overrides.clear()
        db.close()
        transaction.rollback()
        connection.close()
