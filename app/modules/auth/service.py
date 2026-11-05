import calendar
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import bcrypt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.auth.models import AuditLog, AuthEvent, AuthIPLimit, LoginSession, User
from app.modules.auth.totp import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_totp_secret,
    provisioning_uri,
    verify_totp_code,
)

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 10
MAX_IP_FAILURES = 100
IP_FAILURE_WINDOW_MINUTES = 10
_DUMMY_PASSWORD_HASH = b"$2b$12$J8j07.GUFqUX1O4nEUokquq3ukpxnrmvKgb65UfA8wpbpgLfsXMou"


class AuthenticationError(Exception):
    """Raised when login credentials cannot be accepted."""


class RateLimitError(Exception):
    """Raised when the source IP exceeded the failed-login threshold."""


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    if not 1 <= len(password_bytes) <= 72:
        raise ValueError("Mật khẩu phải có từ 1 đến 72 byte UTF-8")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    password_bytes = password.encode("utf-8")
    if not 1 <= len(password_bytes) <= 72:
        return False
    try:
        return bcrypt.checkpw(password_bytes, password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_login_session(
    db: Session,
    user_id: int,
    *,
    auth_state: str = "active",
    now: datetime | None = None,
) -> tuple[str, LoginSession]:
    current_time = now or datetime.now(UTC)
    raw_token = secrets.token_urlsafe(32)
    timeout = get_settings().session_idle_timeout_minutes
    session = LoginSession(
        user_id=user_id,
        token_hash=sha256(raw_token.encode("ascii")).hexdigest(),
        last_seen_at=current_time,
        expires_at=current_time + timedelta(minutes=timeout),
        auth_state=auth_state,
    )
    db.add(session)
    db.flush()
    return raw_token, session


def resolve_login_session(
    db: Session, raw_token: str | None, *, now: datetime | None = None
) -> tuple[User, LoginSession] | None:
    if not raw_token:
        return None
    current_time = now or datetime.now(UTC)
    token_hash = sha256(raw_token.encode("utf-8")).hexdigest()
    session = db.scalar(
        select(LoginSession)
        .where(
            LoginSession.token_hash == token_hash,
            LoginSession.revoked_at.is_(None),
            LoginSession.expires_at > current_time,
        )
        .with_for_update()
    )
    if session is None:
        return None

    user = db.scalar(
        select(User).where(
            User.id == session.user_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        session.revoked_at = current_time
        return None

    session.last_seen_at = current_time
    session.expires_at = current_time + timedelta(
        minutes=get_settings().session_idle_timeout_minutes
    )
    return user, session


def revoke_user_sessions(db: Session, user_id: int, *, now: datetime | None = None) -> None:
    current_time = now or datetime.now(UTC)
    sessions = db.scalars(
        select(LoginSession).where(
            LoginSession.user_id == user_id,
            LoginSession.revoked_at.is_(None),
        )
    )
    for session in sessions:
        session.revoked_at = current_time


def begin_admin_totp_enrollment(db: Session, user: User) -> tuple[str, str]:
    if user.role != "admin":
        raise ValueError("Chỉ tài khoản Admin được thiết lập TOTP bắt buộc.")
    if user.totp_enabled:
        raise ValueError("Tài khoản Admin đã bật TOTP.")

    secret = generate_totp_secret()
    user.totp_secret_encrypted = encrypt_totp_secret(secret)
    user.totp_recovery_hashes = []
    user.version += 1
    db.add(
        AuditLog(
            table_name="users",
            record_id=user.id,
            action="update",
            old_values={"totp_enabled": False},
            new_values={"totp_setup_pending": True},
            reason="Bắt đầu thiết lập TOTP cho Admin",
            actor_id=user.id,
        )
    )
    return secret, provisioning_uri(user.username, secret)


def confirm_admin_totp_enrollment(
    db: Session,
    user: User,
    submitted_code: str,
    *,
    now: datetime | None = None,
) -> list[str] | None:
    if user.role != "admin" or user.totp_enabled or not user.totp_secret_encrypted:
        return None
    current_time = now or datetime.now(UTC)
    secret = decrypt_totp_secret(user.totp_secret_encrypted)
    counter = verify_totp_code(secret, submitted_code, now=current_time.timestamp())
    if counter is None:
        return None

    recovery_codes = [secrets.token_hex(12) for _ in range(10)]
    user.totp_recovery_hashes = [
        sha256(code.encode("ascii")).hexdigest() for code in recovery_codes
    ]
    user.totp_enabled = True
    user.totp_last_used_counter = counter
    user.version += 1
    db.add(
        AuditLog(
            table_name="users",
            record_id=user.id,
            action="update",
            old_values={"totp_enabled": False},
            new_values={"totp_enabled": True},
            reason="Hoàn tất thiết lập TOTP cho Admin",
            actor_id=user.id,
        )
    )
    db.add(
        AuthEvent(
            user_id=user.id,
            username_attempt=user.username,
            event_type="totp_enrolled",
        )
    )
    return recovery_codes


def verify_admin_totp(
    db: Session,
    user: User,
    submitted_code: str,
    *,
    now: datetime | None = None,
) -> bool:
    if user.role != "admin" or not user.totp_enabled or not user.totp_secret_encrypted:
        return False
    current_time = now or datetime.now(UTC)
    secret = decrypt_totp_secret(user.totp_secret_encrypted)
    counter = verify_totp_code(secret, submitted_code, now=current_time.timestamp())
    if counter is not None:
        if user.totp_last_used_counter is not None and counter <= user.totp_last_used_counter:
            return False
        user.totp_last_used_counter = counter
        user.version += 1
        return True

    candidate_hash = sha256(submitted_code.strip().lower().encode("utf-8")).hexdigest()
    for index, recovery_hash in enumerate(user.totp_recovery_hashes):
        if hmac.compare_digest(candidate_hash, recovery_hash):
            user.totp_recovery_hashes = [
                saved_hash
                for saved_index, saved_hash in enumerate(user.totp_recovery_hashes)
                if saved_index != index
            ]
            user.version += 1
            db.add(
                AuthEvent(
                    user_id=user.id,
                    username_attempt=user.username,
                    event_type="totp_recovery_used",
                )
            )
            return True
    return False


def authenticate_password(
    db: Session,
    username: str,
    password: str,
    ip_address: str | None,
    *,
    now: datetime | None = None,
) -> User:
    """Verify account password and record the attempt; caller commits either outcome."""
    current_time = now or datetime.now(UTC)
    normalized_username = username.strip()
    if not ip_address:
        raise ValueError("Không xác định được địa chỉ IP đăng nhập")

    db.execute(
        insert(AuthIPLimit)
        .values(
            ip_address=ip_address,
            window_started_at=current_time,
            failure_count=0,
            updated_at=current_time,
        )
        .on_conflict_do_nothing(index_elements=[AuthIPLimit.ip_address])
    )
    ip_limit = db.scalar(
        select(AuthIPLimit).where(AuthIPLimit.ip_address == ip_address).with_for_update()
    )
    window_expired = ip_limit.window_started_at <= current_time - timedelta(
        minutes=IP_FAILURE_WINDOW_MINUTES
    )
    if window_expired:
        ip_limit.window_started_at = current_time
        ip_limit.failure_count = 0
    if ip_limit.failure_count >= MAX_IP_FAILURES:
        raise RateLimitError("Có quá nhiều lần đăng nhập sai từ địa chỉ IP này. Hãy thử lại sau.")

    user = db.scalar(
        select(User)
        .where(User.username == normalized_username, User.deleted_at.is_(None))
        .with_for_update()
    )
    if user is not None and user.locked_until is not None and user.locked_until <= current_time:
        user.failed_login_count = 0
        user.locked_until = None

    candidate_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH.decode("ascii")
    password_matches = verify_password(password, candidate_hash)
    locked = user is not None and user.locked_until is not None and user.locked_until > current_time
    accepted = user is not None and user.is_active and password_matches and not locked

    if not accepted:
        ip_limit.failure_count += 1
        ip_limit.updated_at = current_time
        if user is not None and user.is_active and not locked:
            user.failed_login_count += 1
            if user.failed_login_count >= MAX_FAILED_LOGINS:
                user.locked_until = current_time + timedelta(minutes=LOCKOUT_MINUTES)
                event_type = "lockout"
            else:
                event_type = "login_failure"
        else:
            event_type = "login_failure"

        db.add(
            AuthEvent(
                user_id=user.id if user else None,
                username_attempt=normalized_username[:100] or None,
                event_type=event_type,
                ip_address=ip_address,
            )
        )
        raise AuthenticationError("Tên đăng nhập hoặc mật khẩu không đúng, hoặc tài khoản bị khóa")

    return user


def complete_login(
    db: Session, user: User, ip_address: str, *, now: datetime | None = None
) -> None:
    current_time = now or datetime.now(UTC)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = current_time
    db.add(
        AuthEvent(
            user_id=user.id,
            username_attempt=user.username,
            event_type="login_success",
            ip_address=ip_address,
        )
    )


def record_login_factor_failure(
    db: Session,
    user: User,
    ip_address: str,
    *,
    now: datetime | None = None,
) -> None:
    current_time = now or datetime.now(UTC)
    ip_limit = db.scalar(
        select(AuthIPLimit).where(AuthIPLimit.ip_address == ip_address).with_for_update()
    )
    if ip_limit is None:
        raise ValueError("Không tìm thấy bộ đếm đăng nhập theo địa chỉ IP")
    if ip_limit.window_started_at <= current_time - timedelta(minutes=IP_FAILURE_WINDOW_MINUTES):
        ip_limit.window_started_at = current_time
        ip_limit.failure_count = 0
    if ip_limit.failure_count >= MAX_IP_FAILURES:
        raise RateLimitError("Có quá nhiều lần đăng nhập sai từ địa chỉ IP này. Hãy thử lại sau.")

    ip_limit.failure_count += 1
    ip_limit.updated_at = current_time
    if user.locked_until is None or user.locked_until <= current_time:
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = current_time + timedelta(minutes=LOCKOUT_MINUTES)
    db.add(
        AuthEvent(
            user_id=user.id,
            username_attempt=user.username,
            event_type="login_failure",
            ip_address=ip_address,
        )
    )


def next_auth_state(user: User, *, now: datetime | None = None) -> str:
    current_time = now or datetime.now(UTC)
    changed_at = user.password_changed_at
    if user.must_change_password or changed_at is None:
        return "password_change"
    deadline = _subtract_calendar_months(current_time, 3)
    if changed_at <= deadline:
        return "password_change"
    if user.role == "admin" and not user.totp_enabled:
        return "totp_setup"
    return "active"


def _subtract_calendar_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def change_password(
    db: Session,
    user: User,
    current_password: str,
    new_password: str,
    *,
    now: datetime | None = None,
) -> tuple[str, LoginSession]:
    if not verify_password(current_password, user.password_hash):
        raise AuthenticationError("Mật khẩu hiện tại không đúng.")
    if current_password == new_password:
        raise ValueError("Mật khẩu mới phải khác mật khẩu hiện tại.")

    current_time = now or datetime.now(UTC)
    old_state = {
        "must_change_password": user.must_change_password,
        "password_changed_at": user.password_changed_at.isoformat()
        if user.password_changed_at
        else None,
    }
    user.password_hash = hash_password(new_password)
    user.password_changed_at = current_time
    user.must_change_password = False
    user.version += 1
    revoke_user_sessions(db, user.id, now=current_time)
    state = next_auth_state(user, now=current_time)
    raw_token, session = create_login_session(db, user.id, auth_state=state, now=current_time)
    db.add(
        AuditLog(
            table_name="users",
            record_id=user.id,
            action="update",
            old_values=old_state,
            new_values={
                "must_change_password": False,
                "password_changed_at": current_time.isoformat(),
            },
            reason="Người dùng đổi mật khẩu",
            actor_id=user.id,
        )
    )
    return raw_token, session
