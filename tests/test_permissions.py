import pytest

from app.core.permissions import has_permission


@pytest.mark.parametrize(
    ("role", "module", "action", "allowed"),
    [
        ("admin", "anything", "delete", True),
        ("planning", "orders", "edit", True),
        ("planning", "blank_requests", "create", False),
        ("engineering", "blank_requests", "create", True),
        ("engineering", "blank_requests", "deliver", False),
        ("warehouse", "blank_requests", "deliver", True),
        ("warehouse", "orders", "edit", False),
        ("data_entry", "daily_reports", "edit", True),
        ("manager", "audit_log", "view", True),
        ("manager", "orders", "edit", False),
        ("unknown", "reports", "view", False),
    ],
)
def test_role_permission_matrix(role: str, module: str, action: str, allowed: bool) -> None:
    assert has_permission(role, module, action) is allowed
