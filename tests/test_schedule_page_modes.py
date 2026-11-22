from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app.core.db import SessionLocal, get_db
from app.core.permissions import require_active_user
from app.modules.schedules.router import router


def test_schedule_defaults_to_month_and_offers_list_to_read_only_users() -> None:
    app = FastAPI()
    app.include_router(router)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    db = SessionLocal()
    try:
        db.begin()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[require_active_user] = lambda: SimpleNamespace(
            id=0, role="manager"
        )
        with TestClient(app, base_url="https://testserver") as client:
            month = client.get("/schedules?on=2026-11-22")
            assert month.status_code == 200
            assert 'class="calendar-grid month-calendar"' in month.text
            assert 'aria-current="page">Tháng</a>' in month.text
            assert 'id="open-schedule-create"' not in month.text
            assert "data-edit-schedule" not in month.text
            listing = client.get("/schedules?view=list&on=2026-11-22")
            assert listing.status_code == 200
            assert 'class="schedule-planning-table"' in listing.text
            assert 'aria-current="page">Danh sách</a>' in listing.text
            assert 'id="open-schedule-create"' not in listing.text
    finally:
        db.rollback()
        db.close()
