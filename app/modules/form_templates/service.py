import base64
import copy
import hashlib
import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from threading import BoundedSemaphore
from zoneinfo import ZoneInfo

import qrcode
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as SheetImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.styles import Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.units import pixels_to_EMU
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.employees.models import Employee
from app.modules.form_templates.models import FormTemplateVersion

MAX_TEMPLATE_SIZE = 10 * 1024 * 1024
MAX_UNPACKED_SIZE = 50 * 1024 * 1024
TOKEN_RE = re.compile(r"@@?([A-Za-z][A-Za-z0-9_.]*)")
TEMPLATE_PATH = Path("docs/forms/Bieu_san_luong_va_QC_v1_2_da_sua.xlsx")
LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_LIBREOFFICE_SLOTS = BoundedSemaphore(1)


class FormTemplateError(Exception):
    """A template is invalid or cannot be rendered safely."""


def active_template(db: Session) -> bytes:
    active = db.scalar(
        select(FormTemplateVersion).where(
            FormTemplateVersion.is_active.is_(True),
            FormTemplateVersion.deleted_at.is_(None),
        )
    )
    try:
        content = active.content if active else TEMPLATE_PATH.read_bytes()
        return _with_lot_qc_sheet(content)
    except OSError as exc:
        raise FormTemplateError("Chưa có tệp mẫu biểu Excel được cài đặt.") from exc


def template_status(db: Session) -> FormTemplateVersion | None:
    return db.scalar(
        select(FormTemplateVersion)
        .where(FormTemplateVersion.is_active.is_(True), FormTemplateVersion.deleted_at.is_(None))
        .execution_options(populate_existing=True)
    )


def validate_template(content: bytes) -> None:
    if not content or len(content) > MAX_TEMPLATE_SIZE:
        raise FormTemplateError("Tệp Excel phải có dung lượng từ 1 byte đến 10 MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if sum(member.file_size for member in members) > MAX_UNPACKED_SIZE:
                raise FormTemplateError("Tệp Excel vượt quá giới hạn giải nén 50 MB.")
            names = {member.filename for member in members}
            if any(name.startswith("xl/externalLinks/") for name in names):
                raise FormTemplateError("Mẫu không được chứa liên kết tới tệp Excel bên ngoài.")
            if any(name.endswith("vbaProject.bin") for name in names):
                raise FormTemplateError("Không chấp nhận mẫu Excel có macro.")
            workbook = load_workbook(io.BytesIO(content), data_only=False, keep_links=False)
    except FormTemplateError:
        raise
    except Exception as exc:
        raise FormTemplateError("Không đọc được tệp Excel .xlsx.") from exc
    if not {"Sản lượng", "QC theo lô"}.issubset(workbook.sheetnames):
        raise FormTemplateError("Mẫu phải có đủ hai sheet 'Sản lượng' và 'QC theo lô'.")
    unknown: set[str] = set()
    sheet_names = ["Sản lượng", "QC theo lô"]
    for sheet_name in sheet_names:
        sheet = workbook[sheet_name]
        for row in sheet.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    raise FormTemplateError("Mẫu in không được chứa công thức Excel.")
                if isinstance(cell.value, str):
                    unknown.update(
                        key for key in TOKEN_RE.findall(cell.value) if not _known_token(key)
                    )
    if unknown:
        raise FormTemplateError("Mẫu có key chưa hỗ trợ: " + ", ".join(sorted(unknown)))
    workbook.close()


def upload_template(
    db: Session, file_name: str, content: bytes, actor_id: int
) -> FormTemplateVersion:
    if Path(file_name).suffix.lower() != ".xlsx":
        raise FormTemplateError("Chỉ nhận tệp Excel có đuôi .xlsx.")
    validate_template(content)
    # Serialize activation/version allocation even when no template exists yet.
    db.execute(text("SELECT pg_advisory_xact_lock(20261122, 18)"))
    now = datetime.now(UTC)
    current = template_status(db)
    version = db.scalar(select(func.coalesce(func.max(FormTemplateVersion.version), 0))) + 1
    old_values = {"version": current.version, "sha256": current.sha256} if current else None
    if current:
        current.is_active = False
        current.updated_at = now
        current.updated_by = actor_id
        db.flush()
    record = FormTemplateVersion(
        version=version,
        file_name=Path(file_name).name[:255],
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        is_active=True,
        created_at=now,
        created_by=actor_id,
        updated_at=now,
        updated_by=actor_id,
    )
    db.add(record)
    db.flush()
    db.add(
        AuditLog(
            table_name="form_template_versions",
            record_id=record.id,
            action="create",
            old_values=old_values,
            new_values={"version": version, "file_name": record.file_name, "sha256": record.sha256},
            reason="Thay mẫu in Excel",
            actor_id=actor_id,
        )
    )
    return record


def render_template_pdf(
    content: bytes, form_type: str, replacements: dict[str, str], qr_value: str
) -> bytes:
    validate_template(content)
    workbook = load_workbook(io.BytesIO(content), data_only=False, keep_links=False)
    keep_name = {"production": "Sản lượng"}.get(form_type)
    if keep_name is None or keep_name not in workbook.sheetnames:
        raise FormTemplateError("Không tìm thấy sheet biểu cần in trong mẫu Excel.")
    for sheet_name in list(workbook.sheetnames):
        if sheet_name != keep_name:
            del workbook[sheet_name]
    sheet = workbook[keep_name]
    _replace_sheet_tokens(sheet, replacements, qr_value)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return _convert_pdf(output.getvalue())


def render_lot_qc_batch_pdf(
    content: bytes,
    lots: list[tuple[dict[str, str], str]],
) -> bytes:
    """Render one Excel QC sheet per lot and return the merged PDF pages."""
    validate_template(content)
    if not lots or len(lots) > 100:
        raise FormTemplateError("Chọn từ 1 đến 100 lô để in.")
    workbook = load_workbook(io.BytesIO(content), data_only=False, keep_links=False)
    if "QC theo lô" not in workbook.sheetnames:
        workbook.close()
        raise FormTemplateError("Mẫu Excel chưa có sheet 'QC theo lô'.")
    base_sheet = workbook["QC theo lô"]
    if not any(
        isinstance(cell.value, str) and "@qr_yeu_cau" in cell.value
        for row in base_sheet.iter_rows()
        for cell in row
    ):
        workbook.close()
        raise FormTemplateError("Sheet 'QC theo lô' phải có key @qr_yeu_cau.")
    sheets = [base_sheet]
    for _ in lots[1:]:
        sheets.append(workbook.copy_worksheet(base_sheet))
    for index, (sheet, (replacements, qr_value)) in enumerate(zip(sheets, lots, strict=True), 1):
        sheet.title = f"QC lô {index:03d}"
        _replace_sheet_tokens(sheet, replacements, qr_value)
    for sheet_name in list(workbook.sheetnames):
        if sheet_name not in {sheet.title for sheet in sheets}:
            del workbook[sheet_name]
    workbook.active = 0
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return _convert_pdf(output.getvalue())


def _replace_sheet_tokens(sheet, replacements: dict[str, str], qr_value: str) -> None:
    qr_cell = next(
        (
            cell.coordinate
            for row in sheet.iter_rows()
            for cell in row
            if isinstance(cell.value, str) and "@qr_yeu_cau" in cell.value
        ),
        None,
    )
    if qr_cell:
        sheet.add_image(_make_centered_qr_image(sheet, qr_cell, qr_value, replacements), qr_cell)
    for row in sheet.iter_rows():
        for cell in row:
            if isinstance(cell.value, str):
                cell.value = TOKEN_RE.sub(
                    lambda match: replacements.get(match.group(1), ""), cell.value
                )
                cell.data_type = "s"


def _with_lot_qc_sheet(content: bytes) -> bytes:
    workbook = load_workbook(io.BytesIO(content), data_only=False, keep_links=False)
    if "QC" in workbook.sheetnames:
        workbook.remove(workbook["QC"])
    if "QC theo lô" in workbook.sheetnames:
        _normalize_lot_qc_sheet(workbook)
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        return output.getvalue()
    try:
        source_workbook = load_workbook(TEMPLATE_PATH, data_only=False, keep_links=False)
    except OSError as exc:
        workbook.close()
        raise FormTemplateError("Không tìm thấy sheet QC theo lô trong mẫu mặc định.") from exc
    source = source_workbook["QC theo lô"]
    target = workbook.create_sheet("QC theo lô")
    for row in source.iter_rows():
        for source_cell in row:
            target_cell = target.cell(source_cell.row, source_cell.column, source_cell.value)
            if source_cell.has_style:
                target_cell.font = copy.copy(source_cell.font)
                target_cell.fill = copy.copy(source_cell.fill)
                target_cell.border = copy.copy(source_cell.border)
                target_cell.alignment = copy.copy(source_cell.alignment)
                target_cell.number_format = source_cell.number_format
                target_cell.protection = copy.copy(source_cell.protection)
    for merged_range in source.merged_cells.ranges:
        target.merge_cells(str(merged_range))
    for index, dimension in source.row_dimensions.items():
        target.row_dimensions[index].height = dimension.height
        target.row_dimensions[index].hidden = dimension.hidden
    for key, dimension in source.column_dimensions.items():
        target.column_dimensions[key].width = dimension.width
        target.column_dimensions[key].hidden = dimension.hidden
    target.sheet_format = copy.copy(source.sheet_format)
    target.page_setup = copy.copy(source.page_setup)
    target.page_margins = copy.copy(source.page_margins)
    target.print_options = copy.copy(source.print_options)
    target.sheet_properties.pageSetUpPr = copy.copy(source.sheet_properties.pageSetUpPr)
    target.sheet_view.showGridLines = source.sheet_view.showGridLines
    target.freeze_panes = source.freeze_panes
    target.print_area = source.print_area
    target.print_title_rows = source.print_title_rows
    source_workbook.close()
    _normalize_lot_qc_sheet(workbook)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _normalize_lot_qc_sheet(workbook) -> None:
    if "QC theo lô" not in workbook.sheetnames:
        return
    sheet = workbook["QC theo lô"]
    if (isinstance(sheet["A30"].value, str) and sheet["A30"].value.startswith("V.")) or any(
        area.max_row >= 30 for area in sheet.merged_cells.ranges
    ):
        for merged_range in list(sheet.merged_cells.ranges):
            if merged_range.max_row >= 30:
                sheet.unmerge_cells(str(merged_range))
        for row in range(30, sheet.max_row + 1):
            for column in range(1, sheet.max_column + 1):
                sheet._cells.pop((row, column), None)
            sheet.row_dimensions.pop(row, None)
        sheet.print_area = "A1:J29"
    _normalize_lot_qc_processing_section(sheet)
    _match_lot_qc_section_headings(workbook)


def _normalize_lot_qc_processing_section(sheet) -> None:
    for merged_range in list(sheet.merged_cells.ranges):
        if merged_range.min_row <= 15 and merged_range.max_row >= 11:
            sheet.unmerge_cells(str(merged_range))

    label_style = copy.copy(sheet["A12"]._style)
    blank_style = copy.copy(sheet["B12"]._style)
    section_style = copy.copy(sheet["A11"]._style)
    section_fill_style = copy.copy(sheet["B11"]._style)
    section_end_style = copy.copy(sheet["J11"]._style)
    for row in range(11, 16):
        for column in range(1, 11):
            cell = sheet.cell(row, column)
            cell.value = None
            if row == 11:
                cell._style = copy.copy(
                    section_style
                    if column == 1
                    else section_end_style
                    if column == 10
                    else section_fill_style
                )
            else:
                cell._style = copy.copy(label_style if column % 2 == 1 else blank_style)

    labels = {
        "A11": "Công đoạn OP1+OP2",
        "A12": "Ký hiệu máy: Ghi OP+OP2",
        "G12": "Số lượng OK",
        "A13": "Thời gian bắt đầu",
        "D13": ".......... / .......... / ..........",
        "G13": "Số lượng NG",
        "A14": "Thời gian kết thúc",
        "D14": ".......... / .......... / ..........",
        "G14": "Người làm",
        "G15": "Kỹ thuật xác nhận",
    }
    for coordinate, value in labels.items():
        sheet[coordinate] = value

    for area in ("A11:J11", "A12:F12", "G12:H12", "I12:J12"):
        sheet.merge_cells(area)
    for row in (13, 14, 15):
        for area in (f"A{row}:C{row}", f"D{row}:F{row}", f"G{row}:H{row}", f"I{row}:J{row}"):
            sheet.merge_cells(area)

    left_area = sheet["A15"].border
    sheet["A15"].border = Border(
        left=left_area.left,
        right=left_area.right,
        top=left_area.top,
        bottom=left_area.bottom,
        diagonal=Side(style="thin", color="000000"),
        diagonalUp=True,
    )
    for row, height in {11: 22, 12: 26, 13: 28, 14: 28, 15: 28}.items():
        sheet.row_dimensions[row].height = height


def _match_lot_qc_section_headings(workbook) -> None:
    """Use the production form's section-bar formatting on QC-lot headings only."""
    if "Sản lượng" not in workbook.sheetnames or "QC theo lô" not in workbook.sheetnames:
        return
    production = workbook["Sản lượng"]
    qc_lot = workbook["QC theo lô"]
    source_row = 4
    for row_index in (4, 10, 16, 23):
        for column_index in range(1, 11):
            source_cell = production.cell(source_row, column_index)
            target_cell = qc_lot.cell(row_index, column_index)
            if source_cell.has_style:
                target_cell._style = copy.copy(source_cell._style)
        qc_lot.row_dimensions[row_index].height = production.row_dimensions[source_row].height


def _make_centered_qr_image(
    sheet, cell_coordinate: str, qr_value: str, replacements: dict[str, str]
) -> SheetImage:
    cell = sheet[cell_coordinate]
    caption = TOKEN_RE.sub(lambda match: replacements.get(match.group(1), ""), str(cell.value))
    caption_lines = [line.strip() for line in caption.splitlines() if line.strip()]
    merged_range = next(
        (area for area in sheet.merged_cells.ranges if cell_coordinate in area), None
    )
    if merged_range:
        min_col, min_row, max_col, max_row = merged_range.bounds
    else:
        min_col, min_row = cell.column, cell.row
        max_col, max_row = min_col, min_row
    default_width = sheet.sheet_format.defaultColWidth or 8.43
    default_height = sheet.sheet_format.defaultRowHeight or 15
    box_width = sum(
        int((sheet.column_dimensions[get_column_letter(index)].width or default_width) * 7 + 5)
        for index in range(min_col, max_col + 1)
    )
    box_height = sum(
        round((sheet.row_dimensions[index].height or default_height) * 4 / 3)
        for index in range(min_row, max_row + 1)
    )
    font = _qr_caption_font(14)
    draw_probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    caption_metrics = [draw_probe.textbbox((0, 0), line, font=font) for line in caption_lines]
    caption_height = sum(bottom - top for _left, top, _right, bottom in caption_metrics)
    line_spacing = 2
    gap = 6
    qr_size = min(150, box_width - 12, box_height - caption_height - gap * 2)
    if qr_size < 64:
        raise FormTemplateError("Ô mã QR trong mẫu quá nhỏ để in rõ cùng mã yêu cầu.")

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
    qr.add_data(qr_value)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    qr_pixels = Image.new("RGB", (len(matrix), len(matrix)), "white")
    pixels = qr_pixels.load()
    for y, row in enumerate(matrix):
        for x, is_dark in enumerate(row):
            if is_dark:
                pixels[x, y] = (0, 0, 0)
    qr_pixels = qr_pixels.resize((qr_size, qr_size), Image.Resampling.NEAREST)

    text_width = max((right - left for left, _top, right, _bottom in caption_metrics), default=0)
    image_width = min(box_width - 4, max(qr_size, text_width) + 8)
    text_height = caption_height + line_spacing * max(0, len(caption_lines) - 1)
    image_height = qr_size + gap + text_height
    composite = Image.new("RGB", (image_width, image_height), "white")
    composite.paste(qr_pixels, ((image_width - qr_size) // 2, 0))
    draw = ImageDraw.Draw(composite)
    y = qr_size + gap
    for line, (left, top, right, bottom) in zip(caption_lines, caption_metrics, strict=True):
        width = right - left
        draw.text(((image_width - width) // 2 - left, y - top), line, fill="black", font=font)
        y += bottom - top + line_spacing

    cell.value = ""
    image_buffer = io.BytesIO()
    composite.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    image = SheetImage(image_buffer)
    image.anchor = OneCellAnchor(
        _from=AnchorMarker(
            col=min_col - 1,
            row=min_row - 1,
            colOff=pixels_to_EMU((box_width - image_width) // 2),
            rowOff=pixels_to_EMU((box_height - image_height) // 2),
        ),
        ext=XDRPositiveSize2D(
            cx=pixels_to_EMU(image_width),
            cy=pixels_to_EMU(image_height),
        ),
    )
    return image


def _qr_caption_font(size: int):
    font_candidates = (
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    )
    for font_path in font_candidates:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size)
    return ImageFont.load_default(size=size)


def preview_template_pages(content: bytes) -> list[str]:
    validate_template(content)
    workbook = load_workbook(io.BytesIO(content), data_only=False, keep_links=False)
    for sheet_name in list(workbook.sheetnames):
        if sheet_name not in {"Sản lượng", "QC theo lô"}:
            del workbook[sheet_name]
    workbook.active = 0
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return pdf_pages_as_data_urls(_convert_pdf(output.getvalue()))


@lru_cache(maxsize=2)
def pdf_pages_as_data_urls(pdf_content: bytes, max_pages: int = 12) -> list[str]:
    pdfinfo = shutil.which("pdfinfo")
    pdftoppm = shutil.which("pdftoppm")
    if not pdfinfo or not pdftoppm:
        raise FormTemplateError("Dịch vụ xem và in biểu chưa được cài Poppler trong Docker.")
    with tempfile.TemporaryDirectory(prefix="mes-pdf-pages-") as temp_name:
        temp = Path(temp_name)
        source = temp / "document.pdf"
        source.write_bytes(pdf_content)
        try:
            info = subprocess.run(
                [pdfinfo, str(source)],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            match = re.search(r"^Pages:\s+(\d+)\s*$", info, re.MULTILINE)
            if not match:
                raise FormTemplateError("Không xác định được số trang của biểu mẫu.")
            page_count = int(match.group(1))
            if page_count < 1 or page_count > max_pages:
                raise FormTemplateError(f"Biểu mẫu phải có từ 1 đến {max_pages} trang.")
            prefix = temp / "page"
            subprocess.run(
                [
                    pdftoppm,
                    "-png",
                    "-r",
                    "200",
                    "-f",
                    "1",
                    "-l",
                    str(max_pages),
                    str(source),
                    str(prefix),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            pages = sorted(temp.glob("page-*.png"))
            if len(pages) != page_count:
                raise FormTemplateError("Không kết xuất đầy đủ các trang của biểu mẫu.")
            return [
                "data:image/png;base64," + base64.b64encode(page.read_bytes()).decode("ascii")
                for page in pages
            ]
        except FormTemplateError:
            raise
        except (subprocess.SubprocessError, OSError) as exc:
            raise FormTemplateError("Không kết xuất được trang biểu để xem và in.") from exc


@lru_cache(maxsize=2)
def _convert_pdf(workbook_content: bytes) -> bytes:
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise FormTemplateError("Dịch vụ in Excel chưa được cài LibreOffice trong Docker.")
    if not _LIBREOFFICE_SLOTS.acquire(timeout=30):
        raise FormTemplateError("Dịch vụ in đang bận. Vui lòng thử lại sau ít phút.")
    with tempfile.TemporaryDirectory(prefix="mes-print-") as temp_name:
        temp = Path(temp_name)
        source = temp / "form.xlsx"
        source.write_bytes(workbook_content)
        out = temp / "out"
        out.mkdir()
        profile = (temp / "lo-profile").as_uri()
        try:
            subprocess.run(
                [
                    executable,
                    "--headless",
                    f"-env:UserInstallation={profile}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(out),
                    str(source),
                ],
                check=True,
                capture_output=True,
                timeout=30,
                cwd=temp,
            )
            return (out / "form.pdf").read_bytes()
        except (subprocess.SubprocessError, OSError) as exc:
            raise FormTemplateError(
                "Không chuyển được Excel sang PDF. Kiểm tra lại mẫu in."
            ) from exc
        finally:
            _LIBREOFFICE_SLOTS.release()


def _known_token(key: str) -> bool:
    fixed = {
        "ma_san_pham",
        "ten_san_pham",
        "ma_ban_ve",
        "rev",
        "qr_yeu_cau",
        "ma_yeu_cau",
        "ma_nvl",
        "chat_lieu",
        "ngay_nhan_dh",
        "ma_don_hang",
        "kich_co_phoi",
        "ngay_xuat_phoi",
        "nguoi_giao",
        "nguoi_nhan",
        "ngay_san_xuat",
        "kip",
        "ngay_in",
        "nguoi_lam",
        "ma_lo",
        "so_bieu",
        "so_luong_lo",
        "cong_doan",
    }
    if key in fixed:
        return True
    match = re.fullmatch(r"cap([1-6])\.(ten|nguoi_lam)", key)
    return match is not None


def template_replacements(
    row: tuple,
    pair_options: list[tuple],
    operators: list[Employee] | None = None,
    *,
    sender_name: str = "",
    receiver_name: str = "",
    pair_workers: list[Employee | None] | None = None,
) -> dict[str, str]:
    blank_request, schedule, order, product, shift = row
    if len(pair_options) > 6:
        raise FormTemplateError(
            "Mẫu hiện có 6 dòng cặp máy nhưng yêu cầu này có nhiều hơn 6 cặp. "
            "Chưa in để tránh thiếu dữ liệu."
        )
    production_date = schedule.production_date.strftime("%d/%m/%Y")
    replacements = {
        "ma_san_pham": product.code,
        "ten_san_pham": product.name,
        "ma_ban_ve": order.drawing_number,
        "rev": order.revision,
        "qr_yeu_cau": "",
        "ma_yeu_cau": blank_request.req_no,
        "ma_nvl": order.raw_material_code,
        "chat_lieu": order.material,
        "ngay_nhan_dh": order.order_received_date.strftime("%d/%m/%Y"),
        "ma_don_hang": order.po_no,
        "kich_co_phoi": order.blank_size,
        "ngay_xuat_phoi": blank_request.delivered_at.strftime("%d/%m/%Y")
        if blank_request.delivered_at
        else "",
        "nguoi_giao": sender_name,
        "nguoi_nhan": receiver_name,
        "ngay_san_xuat": production_date,
        "kip": shift.name,
        "ngay_in": datetime.now(LOCAL_TZ).strftime("%d/%m/%Y"),
        "nguoi_lam": ", ".join(employee.name for employee in (operators or [])),
    }
    for index in range(1, 7):
        replacements[f"cap{index}.ten"] = ""
        replacements[f"cap{index}.nguoi_lam"] = ""
    for index, (_pair, machine_1, machine_2) in enumerate(pair_options, start=1):
        replacements[f"cap{index}.ten"] = f"{machine_1.code} - {machine_2.code}"
        worker = pair_workers[index - 1] if pair_workers and index <= len(pair_workers) else None
        replacements[f"cap{index}.nguoi_lam"] = worker.name if worker else ""
    return replacements
