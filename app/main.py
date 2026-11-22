from datetime import datetime
from functools import partial
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.cloudflare_access import (
    AccessTokenError,
    validate_access_configuration,
    verify_access_token,
)
from app.core.config import get_settings
from app.core.csrf import csrf_token_for_request, set_csrf_cookie
from app.core.db import get_db
from app.modules.assets.router import router as assets_router
from app.modules.auth.dependencies import SESSION_COOKIE_NAME, require_active_user
from app.modules.auth.models import User
from app.modules.auth.router import router as auth_router
from app.modules.blank_requests.router import (
    router as blank_requests_router,
)
from app.modules.blank_requests.router import (
    warehouse_router as warehouse_blank_requests_router,
)
from app.modules.blank_requests.service import count_blank_requests
from app.modules.daily_reports.bavia_router import router as bavia_reports_router
from app.modules.daily_reports.router import router as daily_reports_router
from app.modules.defects.router import router as defects_router
from app.modules.downtime.router import router as downtime_router
from app.modules.employees.router import router as employees_router
from app.modules.form_templates.router import router as form_templates_router
from app.modules.health.router import router as health_router
from app.modules.imports.router import router as master_imports_router
from app.modules.master_data.router import router as master_data_router
from app.modules.orders.router import router as orders_router
from app.modules.products.router import router as products_router
from app.modules.qc.router import router as qc_router
from app.modules.repairs.router import router as repairs_router
from app.modules.reporting.router import audit_router
from app.modules.reporting.router import router as reporting_router
from app.modules.schedules.router import router as schedules_router
from app.modules.schedules.service import list_schedules
from app.modules.settings.router import router as settings_router
from app.modules.shifts.router import router as shifts_router
from app.modules.users.router import router as users_router

settings = get_settings()
access_team_domain = validate_access_configuration(
    settings.cloudflare_access_team_domain, settings.cloudflare_access_audience
)
if settings.app_env == "production" and access_team_domain is None:
    raise RuntimeError("Cloudflare Access team domain và audience phải được cấu hình ở production.")
docs_url = "/docs" if settings.app_env == "development" else None

app = FastAPI(
    title="Hệ thống nhập liệu sản lượng, NG và OEE",
    docs_url=docs_url,
    redoc_url=None,
    openapi_url=f"{docs_url}/openapi.json" if docs_url else None,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(assets_router)
app.include_router(employees_router)
app.include_router(form_templates_router)
app.include_router(master_imports_router)
app.include_router(master_data_router)
app.include_router(defects_router)
app.include_router(daily_reports_router)
app.include_router(qc_router)
app.include_router(bavia_reports_router)
app.include_router(repairs_router)
app.include_router(reporting_router)
app.include_router(audit_router)
app.include_router(settings_router)
app.include_router(downtime_router)
app.include_router(users_router)
app.include_router(products_router)
app.include_router(shifts_router)
app.include_router(orders_router)
app.include_router(schedules_router)
app.include_router(blank_requests_router)
app.include_router(warehouse_blank_requests_router)


@app.middleware("http")
async def security_headers_and_sliding_cookie(request: Request, call_next):
    response = None
    if access_team_domain is not None:
        token = request.headers.get("Cf-Access-Jwt-Assertion", "")
        try:
            import anyio

            await anyio.to_thread.run_sync(
                partial(
                    verify_access_token,
                    token,
                    team_domain=access_team_domain,
                    audience=settings.cloudflare_access_audience,
                )
            )
        except AccessTokenError:
            response = HTMLResponse("Không xác minh được phiên Cloudflare Access.", status_code=403)
    if response is None:
        response = await call_next(request)
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "private, no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; "
        "object-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    raw_token = getattr(request.state, "raw_session_token", None)
    if raw_token:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=raw_token,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=settings.session_idle_timeout_minutes * 60,
        )
    return response


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(
    request: Request,
    user: Annotated[User, Depends(require_active_user)],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    csrf_token = csrf_token_for_request(request)
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    today_schedules = list_schedules(db, start_date=today, end_date=today)
    response = templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "title": "Hệ thống nhập liệu sản lượng, NG và OEE",
            "display_name": user.display_name,
            "role": user.role,
            "csrf_token": csrf_token,
            "today": today,
            "today_schedules": today_schedules,
            "warehouse_queue_count": count_blank_requests(db, status="submitted"),
        },
    )
    set_csrf_cookie(response, csrf_token)
    return response
