from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.csrf import csrf_is_valid, csrf_token_for_request, set_csrf_cookie
from app.core.db import get_db
from app.core.excel_imports import (
    discard_preview,
    get_preview,
    parse_xlsx,
    store_preview,
)
from app.core.permissions import require_admin
from app.modules.auth.models import User
from app.modules.products.models import Product
from app.modules.products.schemas import ProductCreate, ProductUpdate
from app.modules.products.service import (
    ProductManagementError,
    count_products,
    create_product,
    list_products,
    update_product,
)

router = APIRouter(prefix="/admin/products", tags=["products"])
templates = Jinja2Templates(directory="app/templates")


def _render(
    request: Request,
    template_name: str,
    context: dict[str, object],
    *,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    csrf_token = csrf_token_for_request(request)
    response = templates.TemplateResponse(
        request=request,
        name=template_name,
        context={**context, "csrf_token": csrf_token},
        status_code=status_code,
    )
    set_csrf_cookie(response, csrf_token)
    return response


def _field_errors(error: ValidationError) -> dict[str, str]:
    messages = {
        "code": "Nhập mã hàng từ 1 đến 100 ký tự.",
        "name": "Nhập tên hàng từ 1 đến 200 ký tự.",
        "cycle_time_seconds": "Cycle time phải lớn hơn 0 và tối đa 3 chữ số thập phân.",
        "version": "Dữ liệu biểu mẫu không còn mới. Hãy tải lại trang.",
    }
    return {
        str(item["loc"][0]) if item["loc"] else "form": messages.get(
            str(item["loc"][0]) if item["loc"] else "form",
            "Giá trị không hợp lệ.",
        )
        for item in error.errors()
    }


def _form_context(
    *,
    product: Product | None = None,
    error: str | None = None,
    errors: dict[str, str] | None = None,
    submitted: dict[str, str | bool] | None = None,
) -> dict[str, object]:
    return {
        "title": "Sửa mã hàng" if product else "Tạo mã hàng",
        "product": product,
        "error": error,
        "errors": errors or {},
        "submitted": submitted or {},
    }


def _product_list_context(
    db: Session,
    *,
    submitted=None,
    errors=None,
    error=None,
    open_create=False,
    open_import=False,
    page: int | None = None,
):
    context = {
        "title": "Quản lý mã hàng",
        "products": list_products(db, limit=100, offset=(page - 1) * 100)
        if page
        else list_products(db),
        "submitted": submitted or {},
        "errors": errors or {},
        "error": error,
        "open_create": open_create,
        "open_import": open_import,
    }
    if page:
        total = count_products(db)
        context.update({"page": page, "page_count": max(1, (total + 99) // 100)})
    return context


@router.get("", response_class=HTMLResponse)
def product_list_page(
    request: Request,
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    new: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
) -> HTMLResponse:
    return _render(
        request,
        "products/list.html",
        _product_list_context(db, open_create=new, page=page),
    )


@router.get("/new", response_class=HTMLResponse)
def new_product_page(
    request: Request,
    _actor: Annotated[User, Depends(require_admin)],
) -> Response:
    return RedirectResponse("/admin/products?new=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("", response_class=HTMLResponse)
def create_product_submit(
    request: Request,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    cycle_time_seconds: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {
        "code": code,
        "name": name,
        "cycle_time_seconds": cycle_time_seconds,
    }
    try:
        data = ProductCreate.model_validate(submitted)
        create_product(db, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _render(
            request,
            "products/list.html",
            _product_list_context(
                db, errors=_field_errors(exc), submitted=submitted, open_create=True
            ),
            status_code=422,
        )
    except (ProductManagementError, IntegrityError) as exc:
        db.rollback()
        message = (
            str(exc) if isinstance(exc, ProductManagementError) else "Mã hàng này đã được sử dụng."
        )
        return _render(
            request,
            "products/list.html",
            _product_list_context(
                db, errors={"code": message}, submitted=submitted, open_create=True
            ),
            status_code=422,
        )
    return RedirectResponse("/admin/products", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/import/template")
def product_import_template(
    _actor: Annotated[User, Depends(require_admin)],
) -> StreamingResponse:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Products"
    headers = ["Mã hàng", "Tên hàng", "Cycle time (giây)"]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1D4ED8")
    for index, width in enumerate((22, 32, 20), start=1):
        sheet.column_dimensions[chr(64 + index)].width = width
    sheet.freeze_panes = "A2"
    guide = workbook.create_sheet("HuongDan")
    guide.append(["HƯỚNG DẪN NHẬP MÃ HÀNG"])
    guide.append(["Mỗi dòng trên sheet Products là một mã hàng."])
    guide.append(["Không đổi tên sheet hoặc hàng tiêu đề."])
    guide.append(["Cycle time tính bằng giây/sản phẩm và phải lớn hơn 0."])
    guide.append(["Lưu file .xlsx, tải lên phần mềm để kiểm tra rồi xác nhận nhập."])
    from io import BytesIO

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="mau-ma-hang.xlsx"'},
    )


@router.post("/import/preview", response_class=HTMLResponse)
async def product_import_preview(
    request: Request,
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    csrf_token: Annotated[str, Form()],
    upload: Annotated[UploadFile, File()],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    if not upload.filename or not upload.filename.lower().endswith(".xlsx"):
        return _render(
            request,
            "products/list.html",
            _product_list_context(db, error="Chỉ nhận file .xlsx.", open_import=True),
            status_code=422,
        )
    try:
        rows = parse_xlsx(
            await upload.read(10 * 1024 * 1024 + 1),
            "Products",
            ["Mã hàng", "Tên hàng", "Cycle time (giây)"],
        )
    except ValueError as exc:
        return _render(
            request,
            "products/list.html",
            _product_list_context(db, error=str(exc), open_import=True),
            status_code=422,
        )
    existing = {product.code.casefold() for product in list_products(db)}
    seen: set[str] = set()
    errors: list[dict[str, int | str]] = []
    for row in rows:
        code = row["Mã hàng"].strip()
        if not code or len(code) > 100:
            errors.append(
                {"row": int(row["__row__"]), "message": "Mã hàng bắt buộc, tối đa 100 ký tự."}
            )
        elif code.casefold() in existing or code.casefold() in seen:
            errors.append(
                {"row": int(row["__row__"]), "message": f"Mã hàng '{code}' đã tồn tại hoặc bị lặp."}
            )
        if code:
            seen.add(code.casefold())
        try:
            ProductCreate.model_validate(
                {
                    "code": code,
                    "name": row["Tên hàng"],
                    "cycle_time_seconds": row["Cycle time (giây)"],
                }
            )
        except ValidationError as exc:
            errors.append(
                {"row": int(row["__row__"]), "message": "; ".join(_field_errors(exc).values())}
            )
    token = store_preview(db, actor.id, "products", rows, errors) if not errors else ""
    if token:
        db.commit()
    return _render(
        request,
        "imports/preview.html",
        {
            "title": "Kiểm tra file mã hàng",
            "resource": "products",
            "resource_label": "mã hàng",
            "rows": rows,
            "errors": errors,
            "token": token,
            "confirm_url": f"/admin/products/import/{token}/confirm" if token else "",
            "return_url": "/admin/products",
        },
    )


@router.post("/import/{token}/confirm", response_class=HTMLResponse)
def product_import_confirm(
    request: Request,
    token: str,
    csrf_token: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    preview = get_preview(db, token, actor.id, "products")
    if preview is None:
        return _render(
            request,
            "products/list.html",
            _product_list_context(db, error="Phiên xem trước đã hết hạn. Hãy tải file lên lại."),
            status_code=410,
        )
    if preview.errors:
        return Response("File còn lỗi, chưa thể nhập.", status_code=422)
    try:
        for row in preview.rows:
            data = ProductCreate.model_validate(
                {
                    "code": row["Mã hàng"],
                    "name": row["Tên hàng"],
                    "cycle_time_seconds": row["Cycle time (giây)"],
                }
            )
            create_product(db, data, actor.id)
        discard_preview(db, preview)
        db.commit()
    except (ValidationError, ProductManagementError, IntegrityError) as exc:
        db.rollback()
        return _render(
            request,
            "products/list.html",
            _product_list_context(
                db, error=f"Không nhập được file; chưa có dòng nào được lưu. {exc}"
            ),
            status_code=422,
        )
    return RedirectResponse("/admin/products", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{product_id}", response_class=HTMLResponse)
def edit_product_page(
    request: Request,
    product_id: int,
    _actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    product = db.get(Product, product_id)
    if product is None or product.deleted_at is not None:
        return Response("Không tìm thấy mã hàng.", status_code=404)
    return _render(request, "products/form.html", _form_context(product=product))


@router.post("/{product_id}", response_class=HTMLResponse)
def update_product_submit(
    request: Request,
    product_id: int,
    csrf_token: Annotated[str, Form()],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    cycle_time_seconds: Annotated[str, Form()],
    actor: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    is_active: Annotated[bool, Form()] = False,
    version: Annotated[int, Form()] = 1,
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return Response("Phiên biểu mẫu không hợp lệ.", status_code=403)
    submitted = {
        "code": code,
        "name": name,
        "cycle_time_seconds": cycle_time_seconds,
        "is_active": is_active,
        "version": version,
    }
    try:
        data = ProductUpdate.model_validate(submitted)
        update_product(db, product_id, data, actor.id)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        product = db.get(Product, product_id)
        if product is None or product.deleted_at is not None:
            return Response("Không tìm thấy mã hàng.", status_code=404)
        return _render(
            request,
            "products/form.html",
            _form_context(
                product=product,
                errors=_field_errors(exc),
                submitted={
                    key: value if key == "is_active" else str(value)
                    for key, value in submitted.items()
                },
            ),
            status_code=422,
        )
    except (ProductManagementError, IntegrityError) as exc:
        db.rollback()
        product = db.get(Product, product_id)
        if product is None or product.deleted_at is not None:
            return Response("Không tìm thấy mã hàng.", status_code=404)
        message = (
            str(exc) if isinstance(exc, ProductManagementError) else "Mã hàng này đã được sử dụng."
        )
        return _render(
            request,
            "products/form.html",
            _form_context(product=product, error=message),
            status_code=422,
        )
    return RedirectResponse("/admin/products", status_code=status.HTTP_303_SEE_OTHER)
