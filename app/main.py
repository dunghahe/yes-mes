import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.csrf import set_csrf_cookie
from app.modules.assets.router import router as assets_router
from app.modules.auth.dependencies import SESSION_COOKIE_NAME, require_active_user
from app.modules.auth.models import User
from app.modules.auth.router import router as auth_router
from app.modules.employees.router import router as employees_router
from app.modules.health.router import router as health_router
from app.modules.products.router import router as products_router
from app.modules.users.router import router as users_router

settings = get_settings()
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
app.include_router(users_router)
app.include_router(products_router)


@app.middleware("http")
async def security_headers_and_sliding_cookie(request: Request, call_next):
    response = await call_next(request)
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
def home(request: Request, user: Annotated[User, Depends(require_active_user)]) -> HTMLResponse:
    csrf_token = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "title": "Hệ thống nhập liệu sản lượng, NG và OEE",
            "display_name": user.display_name,
            "role": user.role,
            "csrf_token": csrf_token,
        },
    )
    set_csrf_cookie(response, csrf_token)
    return response
