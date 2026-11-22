"""Shared safeguards and short-lived preview storage for XLSX imports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from uuid import uuid4
from zipfile import BadZipFile, ZipFile, is_zipfile

from openpyxl import load_workbook
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.imports.models import ImportPreview

MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_IMPORT_ROWS = 5_000
PREVIEW_TTL_SECONDS = 15 * 60


def parse_xlsx(content: bytes, sheet_name: str, headers: list[str]) -> list[dict[str, str]]:
    if not content or len(content) > MAX_IMPORT_BYTES:
        raise ValueError("File Excel vượt giới hạn 10 MB.")
    if not is_zipfile(BytesIO(content)):
        raise ValueError("File không phải Excel .xlsx hợp lệ.")
    try:
        with ZipFile(BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_IMPORT_UNCOMPRESSED_BYTES:
                raise ValueError("File Excel có dữ liệu giải nén quá lớn.")
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except (BadZipFile, OSError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("Không đọc được file Excel. Hãy tải mẫu mới và thử lại.") from exc

    if sheet_name not in workbook.sheetnames:
        raise ValueError(f"File phải có sheet '{sheet_name}'. Hãy tải file mẫu.")
    worksheet = workbook[sheet_name]
    actual = [
        str(value or "").strip()
        for value in next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
    ]
    while actual and not actual[-1]:
        actual.pop()
    if actual != headers:
        raise ValueError("Tên hoặc thứ tự cột không đúng file mẫu.")

    rows: list[dict[str, str]] = []
    for row_number, values in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        values = list(values)
        if any(value not in (None, "") for value in values[len(headers) :]):
            raise ValueError(f"Dòng {row_number} có dữ liệu ngoài các cột mẫu.")
        values = values[: len(headers)]
        if not any(value not in (None, "") for value in values):
            continue
        if len(rows) >= MAX_IMPORT_ROWS:
            raise ValueError(f"File Excel tối đa {MAX_IMPORT_ROWS:,} dòng dữ liệu.")
        rows.append(
            {header: _cell_text(value) for header, value in zip(headers, values, strict=False)}
        )
        rows[-1]["__row__"] = str(row_number)
    workbook.close()
    if not rows:
        raise ValueError("File chưa có dòng dữ liệu.")
    return rows


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.date().isoformat() if hasattr(value, "date") else value.isoformat()
    return str(value).strip()


def _token_hash(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def store_preview(
    db: Session,
    actor_id: int,
    resource: str,
    rows: list[dict[str, str]],
    errors: list[dict[str, int | str]],
) -> str:
    now = datetime.now(UTC)
    db.execute(delete(ImportPreview).where(ImportPreview.expires_at <= now))
    token = uuid4().hex
    db.add(
        ImportPreview(
            token_hash=_token_hash(token),
            resource=resource,
            actor_id=actor_id,
            rows=rows,
            errors=errors,
            expires_at=now + timedelta(seconds=PREVIEW_TTL_SECONDS),
        )
    )
    return token


def get_preview(db: Session, token: str, actor_id: int, resource: str) -> ImportPreview | None:
    return db.scalar(
        select(ImportPreview)
        .where(
            ImportPreview.token_hash == _token_hash(token),
            ImportPreview.actor_id == actor_id,
            ImportPreview.resource == resource,
            ImportPreview.expires_at > datetime.now(UTC),
        )
        .with_for_update()
    )


def discard_preview(db: Session, preview: ImportPreview) -> None:
    db.delete(preview)
