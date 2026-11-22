import asyncio
from io import BytesIO

from openpyxl import load_workbook

from app.core.excel_imports import parse_xlsx
from app.modules.imports.router import SPECS, _validate_row, import_template


def test_defect_excel_round_trip_without_group() -> None:
    response = import_template("defects", None)

    async def collect() -> bytes:
        return b"".join([chunk async for chunk in response.body_iterator])

    workbook = load_workbook(BytesIO(asyncio.run(collect())))
    sheet = workbook["Defects"]
    assert list(next(sheet.values)) == ["Mã lỗi", "Tên lỗi", "Phát hiện tại (SX/BAVIA)"]
    assert str(sheet.data_validations.dataValidation[0].sqref) == "C2:C5001"
    sheet.append(["NG-1", "Xước bề mặt", "SX"])
    output = BytesIO()
    workbook.save(output)
    rows = parse_xlsx(output.getvalue(), "Defects", SPECS["defects"][2])
    data = _validate_row("defects", rows[0])
    assert (data.code, data.name, data.detected_at) == ("NG-1", "Xước bề mặt", "SX")
    assert data.defect_group == ""
