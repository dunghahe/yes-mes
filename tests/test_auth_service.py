from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.auth.models import AuthEvent, AuthIPLimit, User
from app.modules.auth.service import (
    AuthenticationError,
    RateLimitError,
    authenticate_password,
    begin_admin_totp_enrollment,
    confirm_admin_totp_enrollment,
    create_login_session,
    hash_password,
    next_auth_state,
    resolve_login_session,
    revoke_user_sessions,
    verify_admin_totp,
    verify_password,
)
from app.modules.auth.totp import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    rotate_encrypted_totp_secret,
    totp_code_for_counter,
)


def test_bcrypt_password_hash_round_trip() -> None:
    stored_hash = hash_password("MatKhau-thu-nghiem-2026")

    assert stored_hash.startswith("$2")
    assert verify_password("MatKhau-thu-nghiem-2026", stored_hash)
    assert not verify_password("matkhau-sai", stored_hash)


def test_bcrypt_rejects_password_longer_than_72_utf8_bytes() -> None:
    with pytest.raises(ValueError):
        hash_password("a" * 73)
    assert not verify_password("a" * 73, hash_password("valid"))


def test_password_must_be_changed_after_three_calendar_months() -> None:
    user = User(
        username="age-test",
        display_name="Kiểm tra hạn mật khẩu",
        password_hash=hash_password("MatKhau-123"),
        role="data_entry",
        must_change_password=False,
        password_changed_at=datetime(2026, 7, 31, 9, 0, tzinfo=UTC),
    )

    assert next_auth_state(user, now=datetime(2026, 10, 30, 9, 0, tzinfo=UTC)) == "active"
    assert next_auth_state(user, now=datetime(2026, 10, 31, 9, 0, tzinfo=UTC)) == "password_change"


def test_five_failed_passwords_lock_account_and_log_events() -> None:
    now = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    username = f"auth-test-{uuid4().hex}"
    db = SessionLocal()
    try:
        db.begin()
        user = User(
            username=username,
            display_name="Tài khoản thử nghiệm",
            password_hash=hash_password("DungMatKhau-123"),
            role="data_entry",
        )
        db.add(user)
        db.flush()

        for attempt in range(5):
            with pytest.raises(AuthenticationError):
                authenticate_password(
                    db,
                    username,
                    "sai",
                    "192.0.2.10",
                    now=now,
                )
            assert user.failed_login_count == attempt + 1

        assert user.locked_until == now.replace(minute=10)
        events = list(
            db.scalars(select(AuthEvent).where(AuthEvent.user_id == user.id).order_by(AuthEvent.id))
        )
        assert [event.event_type for event in events] == [
            "login_failure",
            "login_failure",
            "login_failure",
            "login_failure",
            "lockout",
        ]
        assert all(event.ip_address == "192.0.2.10" for event in events)
        assert all("sai" not in str(event.__dict__) for event in events)
        ip_limit = db.get(AuthIPLimit, "192.0.2.10")
        assert ip_limit.failure_count == 5
    finally:
        db.rollback()
        db.close()


def test_ip_rate_limit_blocks_attempts_after_one_hundred_failures() -> None:
    now = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    ip_address = "192.0.2.11"
    db = SessionLocal()
    try:
        db.begin()
        db.add(
            AuthIPLimit(
                ip_address=ip_address,
                window_started_at=now,
                failure_count=100,
            )
        )
        db.flush()

        with pytest.raises(RateLimitError):
            authenticate_password(
                db,
                "unknown-user",
                "invalid-password",
                ip_address,
                now=now,
            )
        assert db.get(AuthIPLimit, ip_address).failure_count == 100
    finally:
        db.rollback()
        db.close()


def test_expired_lockout_allows_a_fresh_login_attempt() -> None:
    now = datetime(2026, 11, 5, 10, 11, tzinfo=UTC)
    username = f"auth-unlock-{uuid4().hex}"
    db = SessionLocal()
    try:
        db.begin()
        user = User(
            username=username,
            display_name="Tài khoản hết khóa",
            password_hash=hash_password("DungMatKhau-123"),
            role="data_entry",
            failed_login_count=5,
            locked_until=now.replace(minute=0),
        )
        db.add(user)
        db.flush()

        authenticated = authenticate_password(
            db,
            username,
            "DungMatKhau-123",
            "192.0.2.12",
            now=now,
        )

        assert authenticated.id == user.id
        assert user.failed_login_count == 0
        assert user.locked_until is None
    finally:
        db.rollback()
        db.close()


def test_unknown_username_uses_same_generic_failure_and_does_not_log_password() -> None:
    db = SessionLocal()
    try:
        db.begin()
        with pytest.raises(AuthenticationError) as error:
            authenticate_password(
                db,
                f"missing-{uuid4().hex}",
                "secret-that-must-not-be-stored",
                "192.0.2.13",
            )

        event = db.scalar(select(AuthEvent).order_by(AuthEvent.id.desc()))
        assert "không đúng" in str(error.value)
        assert event.user_id is None
        assert "secret-that-must-not-be-stored" not in str(event.__dict__)
    finally:
        db.rollback()
        db.close()


def test_login_session_slides_for_sixty_minutes_and_can_be_revoked() -> None:
    now = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    db = SessionLocal()
    try:
        db.begin()
        user = User(
            username=f"auth-session-{uuid4().hex}",
            display_name="Tài khoản phiên thử nghiệm",
            password_hash=hash_password("DungMatKhau-123"),
            role="data_entry",
        )
        db.add(user)
        db.flush()

        raw_token, session = create_login_session(db, user.id, now=now)
        assert len(session.token_hash) == 64
        assert raw_token not in session.token_hash
        assert session.expires_at == now.replace(minute=0) + timedelta(hours=1)

        resolved = resolve_login_session(
            db,
            raw_token,
            now=now + timedelta(minutes=45),
        )
        assert resolved is not None
        assert resolved[0].id == user.id
        assert resolved[1].expires_at == now + timedelta(minutes=105)

        revoke_user_sessions(db, user.id, now=now + timedelta(minutes=46))
        assert (
            resolve_login_session(
                db,
                raw_token,
                now=now + timedelta(minutes=47),
            )
            is None
        )
    finally:
        db.rollback()
        db.close()


def test_login_session_is_rejected_after_idle_expiry() -> None:
    now = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    db = SessionLocal()
    try:
        db.begin()
        user = User(
            username=f"auth-expired-{uuid4().hex}",
            display_name="Tài khoản phiên hết hạn",
            password_hash=hash_password("DungMatKhau-123"),
            role="data_entry",
        )
        db.add(user)
        db.flush()
        raw_token, _ = create_login_session(db, user.id, now=now)

        assert resolve_login_session(db, raw_token, now=now + timedelta(hours=1)) is None
    finally:
        db.rollback()
        db.close()


def test_admin_totp_enrollment_encrypts_secret_and_recovery_codes_are_one_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("TOTP_ENCRYPTION_KEYS", encryption_key)
    get_settings.cache_clear()
    now = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    db = SessionLocal()
    try:
        db.begin()
        admin = User(
            username=f"auth-totp-{uuid4().hex}",
            display_name="Admin TOTP thử nghiệm",
            password_hash=hash_password("DungMatKhau-123"),
            role="admin",
        )
        db.add(admin)
        db.flush()

        secret, uri = begin_admin_totp_enrollment(db, admin)
        assert admin.totp_secret_encrypted != secret
        assert uri.startswith("otpauth://totp/")

        counter = int(now.timestamp() // 30)
        code = totp_code_for_counter(secret, counter)
        recovery_codes = confirm_admin_totp_enrollment(db, admin, code, now=now)
        assert recovery_codes is not None
        assert len(recovery_codes) == 10
        assert admin.totp_enabled
        assert not verify_admin_totp(db, admin, code, now=now)

        recovery_code = recovery_codes[0]
        assert verify_admin_totp(db, admin, recovery_code, now=now)
        assert not verify_admin_totp(db, admin, recovery_code, now=now)
    finally:
        db.rollback()
        db.close()
        get_settings.cache_clear()


def test_totp_secret_can_be_reencrypted_then_old_key_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_key = Fernet.generate_key().decode("ascii")
    new_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("TOTP_ENCRYPTION_KEYS", old_key)
    get_settings.cache_clear()
    secret = "JBSWY3DPEHPK3PXP"
    old_ciphertext = encrypt_totp_secret(secret)

    monkeypatch.setenv("TOTP_ENCRYPTION_KEYS", f"{new_key},{old_key}")
    get_settings.cache_clear()
    rotated_ciphertext = rotate_encrypted_totp_secret(old_ciphertext)
    assert decrypt_totp_secret(rotated_ciphertext) == secret

    monkeypatch.setenv("TOTP_ENCRYPTION_KEYS", new_key)
    get_settings.cache_clear()
    assert decrypt_totp_secret(rotated_ciphertext) == secret
    get_settings.cache_clear()
