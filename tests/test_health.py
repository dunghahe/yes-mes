from app.modules.health.router import live


def test_liveness_returns_ok() -> None:
    assert live() == {"status": "ok"}
