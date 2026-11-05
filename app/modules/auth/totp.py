import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings

ISSUER = "YGC MES"
TOTP_PERIOD_SECONDS = 30


def _fernet() -> MultiFernet:
    configured_keys = get_settings().totp_encryption_keys
    if not configured_keys:
        raise RuntimeError("Chưa cấu hình khóa mã hóa TOTP trong biến môi trường.")
    try:
        keys = [Fernet(key.strip().encode("ascii")) for key in configured_keys.split(",")]
        return MultiFernet(keys)
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("Khóa mã hóa TOTP không hợp lệ.") from exc


def encrypt_totp_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_totp_secret(encrypted_secret: str) -> str:
    try:
        return _fernet().decrypt(encrypted_secret.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError(
            "Không giải mã được bí mật TOTP; kiểm tra khóa mã hóa cấu hình."
        ) from exc


def rotate_encrypted_totp_secret(encrypted_secret: str) -> str:
    try:
        return _fernet().rotate(encrypted_secret.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("Không xoay được khóa bí mật TOTP đã mã hóa.") from exc


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_code_for_counter(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}"


def verify_totp_code(secret: str, submitted_code: str, *, now: float | None = None) -> int | None:
    if len(submitted_code) != 6 or not submitted_code.isdigit():
        return None
    timestamp = now if now is not None else time.time()
    current_counter = int(timestamp // TOTP_PERIOD_SECONDS)
    for counter in range(current_counter - 1, current_counter + 2):
        if hmac.compare_digest(totp_code_for_counter(secret, counter), submitted_code):
            return counter
    return None


def provisioning_uri(username: str, secret: str) -> str:
    label = quote(f"{ISSUER}:{username}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}"
        "&algorithm=SHA1&digits=6&period=30"
    )
