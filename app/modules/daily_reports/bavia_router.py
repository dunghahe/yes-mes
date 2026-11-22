from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid
from app.core.db import get_db
from app.core.permissions import require_permission
from app.core.validation import read_json, validation_details
from app.modules.auth.models import User
from app.modules.daily_reports.bavia_schemas import BaviaQcInput, BaviaReportInput
from app.modules.daily_reports.bavia_service import (
    BaviaReportError,
    list_bavia_reports,
    save_bavia_qc,
    save_bavia_report,
)

router = APIRouter(prefix="/bavia-reports", tags=["bavia-reports"])


def _require_csrf(request: Request) -> None:
    if not csrf_is_valid(request, request.headers.get("x-csrf-token", "")):
        raise HTTPException(status_code=403, detail="Phiên biểu mẫu không hợp lệ.")


@router.get("")
def bavia_reports_get(
    _actor: Annotated[User, Depends(require_permission("daily_reports", "view"))],
    db: Annotated[Session, Depends(get_db)],
    order_id: int | None = Query(default=None, gt=0),
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, object]]:
    return list_bavia_reports(db, order_id=order_id, date_from=date_from, date_to=date_to)


@router.post("", status_code=status.HTTP_201_CREATED)
async def save_bavia_report_submit(
    request: Request,
    actor: Annotated[User, Depends(require_permission("daily_reports", "create"))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _require_csrf(request)
    from pydantic import ValidationError

    try:
        data = BaviaReportInput.model_validate(await read_json(request))
        if data.version:
            require_permission("daily_reports", "edit")(request, actor, db)
        row = save_bavia_report(db, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=validation_details(exc)) from exc
    except BaviaReportError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Báo cáo Bavia vừa được thay đổi; hãy tải lại."
        ) from exc
    return {
        "id": row.id,
        "order_id": row.order_id,
        "quantity_produced": row.quantity_produced,
        "version": row.version,
    }


@router.post("/{bavia_report_id}/qc", status_code=status.HTTP_200_OK)
async def save_bavia_qc_submit(
    bavia_report_id: int,
    request: Request,
    actor: Annotated[User, Depends(require_permission("qc", "create"))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _require_csrf(request)
    from pydantic import ValidationError

    try:
        data = BaviaQcInput.model_validate(await read_json(request))
        row = save_bavia_qc(db, bavia_report_id, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=validation_details(exc)) from exc
    except BaviaReportError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="QC Bavia vừa được thay đổi; hãy tải lại."
        ) from exc
    return {
        "id": row.id,
        "bavia_report_id": row.bavia_report_id,
        "quantity_in": row.quantity_in,
        "version": row.version,
    }
