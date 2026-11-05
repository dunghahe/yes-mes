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
        ("manager", "audit", "view", True),
        ("manager", "orders", "edit", False),
        ("unknown", "reports", "view", False),
    ],
)
def test_role_permission_matrix(role: str, module: str, action: str, allowed: bool) -> None:
    assert has_permission(role, module, action) is allowed


def test_user_permissions_only_add_to_role_permissions() -> None:
    extras = frozenset({("qc", "view"), ("qc", "edit")})

    assert has_permission("planning", "qc", "edit", extras)
    assert has_permission("planning", "orders", "edit", extras)
    assert not has_permission("planning", "qc", "delete", extras)
    assert not has_permission("unknown", "qc", "view", extras)
