from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook
from openpyxl.utils.units import EMU_to_pixels

from app.modules.form_templates.service import (
    FormTemplateError,
    _make_centered_qr_image,
    template_replacements,
    validate_template,
)

TEMPLATE = Path("docs/forms/Bieu_san_luong_va_QC_v1_2_da_sua.xlsx")


def _workbook_with_change(cell: str, value: str) -> bytes:
    workbook = load_workbook(TEMPLATE)
    workbook["Sản lượng"][cell] = value
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def test_current_production_and_qc_workbook_is_a_valid_template() -> None:
    validate_template(TEMPLATE.read_bytes())


def test_template_rejects_unknown_data_keys() -> None:
    with pytest.raises(FormTemplateError, match="key chưa hỗ trợ"):
        validate_template(_workbook_with_change("A1", "@@du_lieu_tuy_y"))


def test_template_rejects_excel_formulas() -> None:
    with pytest.raises(FormTemplateError, match="không được chứa công thức"):
        validate_template(_workbook_with_change("A1", "=1+1"))


def test_request_form_uses_delivery_actor_and_requester_names() -> None:
    blank_request = SimpleNamespace(req_no="YC-261112-01", delivered_at=None)
    schedule = SimpleNamespace(production_date=date(2026, 11, 12))
    order = SimpleNamespace(
        drawing_number="DWG-01",
        revision="A",
        raw_material_code="RM-01",
        material="Thép",
        order_received_date=date(2026, 11, 1),
        po_no="PO-01",
        blank_size="10x20",
    )
    product = SimpleNamespace(code="SP-01", name="Sản phẩm")
    shift = SimpleNamespace(name="Kíp 1")

    replacements = template_replacements(
        (blank_request, schedule, order, product, shift),
        [],
        sender_name="Người giao",
        receiver_name="Người yêu cầu",
    )

    assert replacements["nguoi_giao"] == "Người giao"
    assert replacements["nguoi_nhan"] == "Người yêu cầu"


def test_qr_is_enlarged_and_centered_inside_merged_qr_cell() -> None:
    workbook = load_workbook(TEMPLATE)
    sheet = workbook["Sản lượng"]
    image = _make_centered_qr_image(
        sheet,
        "I5",
        "YC-261112-01",
        {"ma_yeu_cau": "YC-261112-01"},
    )

    anchor = image.anchor
    assert 150 <= EMU_to_pixels(anchor.ext.cx) <= 160
    assert EMU_to_pixels(anchor.ext.cy) > 72
    assert anchor._from.colOff == 17 * 9525
    assert sheet["I5"].value == ""
    workbook.close()
