from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import require_permission
from app.modules.assets.service import list_machines, list_pairs
from app.modules.auth.models import User
from app.modules.defects.service import list_defect_codes
from app.modules.downtime.service import list_reasons
from app.modules.employees.service import list_employees
from app.modules.products.service import list_products
from app.modules.shifts.service import list_shifts

router = APIRouter(prefix="/master-data", tags=["master-data"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def master_data_page(
    request: Request,
    _actor: Annotated[User, Depends(require_permission("master", "view"))],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="master_data/index.html",
        context={
            "title": "Danh mục dùng chung",
            "products": list_products(db),
            "machines": list_machines(db),
            "machine_pairs": list_pairs(db),
            "employees": list_employees(db),
            "defect_codes": list_defect_codes(db),
            "downtime_reasons": list_reasons(db),
            "shifts": list_shifts(db),
        },
    )
