from datetime import date, time
from types import SimpleNamespace

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader


def _environment() -> Environment:
    return Environment(
        loader=ChoiceLoader(
            [
                DictLoader({"base.html": "{% block content %}{% endblock %}"}),
                FileSystemLoader("app/templates"),
            ]
        ),
        autoescape=True,
    )


def _rows(count: int):
    day = date(2026, 11, 22)
    shift = SimpleNamespace(id=2, name="Kíp 2", start_time=time(19))
    return [
        (
            SimpleNamespace(
                id=index + 1,
                production_date=day,
                shift_id=2,
                order_id=7,
                planned_quantity=100,
                version=4,
            ),
            SimpleNamespace(id=7, po_no=f"PO-{index + 1}", ordered_quantity=1000),
            shift,
            SimpleNamespace(code="H-1", name="Hàng thử"),
        )
        for index in range(count)
    ]


def test_month_limits_cards_and_opens_all_rows_with_current_filters() -> None:
    day = date(2026, 11, 22)
    rows = _rows(20)
    html = (
        _environment()
        .get_template("schedules/list.html")
        .render(
            can_edit=True,
            can_create=False,
            schedule=None,
            submitted={},
            errors={},
            view="month",
            anchor_date=day,
            anchor=day.isoformat(),
            calendar_title="11/2026",
            calendar_weeks=[[day]],
            schedules_by_date={day: rows},
            schedules=rows,
            weekday_names=["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"],
            active_orders=[],
            active_shifts=[],
            shift_filter=2,
            order_filter=7,
            schedule_base_url="/schedules",
            previous_date="2026-10-01",
            next_date="2026-12-01",
        )
    )
    month = html.split('class="calendar-grid month-calendar"')[1].split('class="month-agenda"')[0]
    assert month.count("data-edit-schedule") == 3
    assert "+17 lịch" in month
    assert "/schedules/day-details?on=2026-11-22&amp;shift_id=2&amp;order_id=7" in month
    assert 'id="schedule-form"' in html  # Edit-only users can still open the edit form.


def test_day_popup_keeps_all_rows_and_hides_edit_for_viewers() -> None:
    rows = _rows(20)
    template = _environment().get_template("schedules/day_details.html")
    readonly = template.render(schedules=rows, can_edit=False)
    assert readonly.count("<tr>") == 21  # Header and every schedule.
    assert "data-edit-schedule" not in readonly
    assert "<button" not in readonly
    editable = template.render(schedules=rows, can_edit=True)
    assert editable.count("data-edit-schedule") == 20
    assert 'data-edit-url="/schedules/20"' in editable


def test_day_popup_shows_empty_state() -> None:
    html = (
        _environment()
        .get_template("schedules/day_details.html")
        .render(schedules=[], can_edit=False)
    )
    assert "Ngày này chưa có lịch sản xuất." in html


def test_list_view_groups_rows_and_keeps_selection_in_edit_form() -> None:
    day = date(2026, 11, 22)
    rows = _rows(20)
    html = (
        _environment()
        .get_template("schedules/list.html")
        .render(
            can_edit=True,
            can_create=True,
            schedule=None,
            submitted={},
            errors={},
            view="list",
            anchor_date=day,
            anchor=day.isoformat(),
            calendar_title="16/11 – 22/11",
            calendar_days=[day],
            schedules_by_date={day: rows},
            schedules=rows,
            week_schedule_count=20,
            selected_day=day,
            query_text="PO-1",
            weekday_names=["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"],
            active_orders=[],
            active_shifts=[],
            shift_filter=2,
            order_filter=None,
            schedule_base_url="/schedules",
            previous_date="2026-11-15",
            next_date="2026-11-29",
        )
    )
    assert html.count('class="schedule-table-row schedule-edit-card"') == 20
    assert html.count('class="schedule-date-divider"') == 1
    assert 'name="return_query" value="PO-1"' in html
    assert 'name="return_day" value="2026-11-22"' in html
    assert 'data-date="2026-11-22"' in html
    assert 'aria-current="date"' in html
