from types import SimpleNamespace

from fastapi.responses import Response
from jinja2 import Environment, FileSystemLoader

from app.modules.blank_requests import router as warehouse


def test_failed_form_generation_does_not_register_print(monkeypatch) -> None:
    calls = []
    db = SimpleNamespace(rollback=lambda: calls.append("rollback"))
    monkeypatch.setattr(
        warehouse, "get_printable_request", lambda *_: [SimpleNamespace(status="submitted")]
    )
    monkeypatch.setattr(
        warehouse, "_render_blank_request_forms", lambda *_: Response("Lỗi mẫu", 422)
    )
    monkeypatch.setattr(warehouse, "register_print", lambda *_: calls.append("register"))
    response = warehouse._print_and_register(None, 1, "production", SimpleNamespace(id=1), db)
    assert response.status_code == 422
    assert calls == ["rollback"]


def test_successful_form_is_prepared_before_registering_print(monkeypatch) -> None:
    calls = []
    db = SimpleNamespace(commit=lambda: calls.append("commit"))
    monkeypatch.setattr(
        warehouse, "get_printable_request", lambda *_: [SimpleNamespace(status="submitted")]
    )

    def render(*_):
        calls.append("render")
        return Response("Biểu in")

    monkeypatch.setattr(warehouse, "_render_blank_request_forms", render)
    monkeypatch.setattr(warehouse, "register_print", lambda *_: calls.append("register"))
    warehouse._print_and_register(None, 1, "production", SimpleNamespace(id=1), db)
    assert calls == ["render", "register", "commit"]


def test_queue_warns_after_print_and_uses_material_information() -> None:
    from datetime import date

    row = (
        SimpleNamespace(id=1, req_no="YC-1", version=2),
        SimpleNamespace(production_date=date(2026, 11, 22)),
        SimpleNamespace(
            po_no="PO-1",
            raw_material_code="NVL-1",
            blank_size="10x20",
            material="Thép",
            process_type="FULL",
        ),
        SimpleNamespace(code="H-1"),
        SimpleNamespace(name="Kíp 1"),
    )
    template = Environment(loader=FileSystemLoader("app/templates"), autoescape=True).get_template(
        "warehouse/queue_fragment.html"
    )
    context = dict(
        requests=[row],
        queue_count=1,
        queue_status="submitted",
        print_stats={1: {"production": (None, 0)}},
    )
    unprinted = template.render(**context)
    assert "NVL-1" in unprinted and "10x20" in unprinted and "Thép" in unprinted
    assert "disabled" in unprinted and "Đã gửi in · Chưa giao" not in unprinted
    context["print_stats"][1]["production"] = (None, 1)
    printed = template.render(**context)
    assert 'class="queue-awaiting-delivery"' in printed
    assert "Đã gửi in · Chưa giao" in printed and "disabled" not in printed
    assert "Cặp · người làm" not in printed and "Số lượng phôi" not in printed
