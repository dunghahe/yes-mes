from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.modules.health.router import router as health_router

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


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"title": "Hệ thống nhập liệu sản lượng, NG và OEE"},
    )
