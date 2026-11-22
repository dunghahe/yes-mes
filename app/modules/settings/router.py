from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid
from app.core.db import get_db
from app.core.permissions import require_admin
from app.core.validation import read_json, validation_details
from app.modules.auth.models import User
from app.modules.settings.schemas import ProductionSettingsInput
from app.modules.settings.service import (
    SettingsError,
    get_production_settings,
    update_production_settings,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/production")
def production_settings_get(
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    value, version = get_production_settings(db)
    return {"po_auto_close_pct": value, "version": version}


@router.put("/production")
async def production_settings_update(
    request: Request,
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    token = request.headers.get("x-csrf-token", "")
    if not csrf_is_valid(request, token):
        raise HTTPException(status_code=403, detail="Phiên biểu mẫu không hợp lệ.")
    from pydantic import ValidationError

    try:
        data = ProductionSettingsInput.model_validate(await read_json(request))
        setting = update_production_settings(db, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=validation_details(exc)) from exc
    except SettingsError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"po_auto_close_pct": int(setting.value), "version": setting.version}
