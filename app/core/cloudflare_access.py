import base64
import json
import math
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class AccessTokenError(ValueError):
    """The Cloudflare Access assertion is missing, invalid, or expired."""


_JWKS_CACHE_TTL_SECONDS = 300
_MAX_TOKEN_BYTES = 16_384
_cache_lock = threading.Lock()
_jwks_cache: dict[str, tuple[float, dict[str, object]]] = {}


def verify_access_token(
    token: str,
    *,
    team_domain: str,
    audience: str,
    now: float | None = None,
    jwks: dict[str, object] | None = None,
) -> dict[str, object]:
    if not token or len(token.encode("utf-8")) > _MAX_TOKEN_BYTES:
        raise AccessTokenError("Invalid Access token")
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        header = _decode_json(encoded_header)
        claims = _decode_json(encoded_payload)
        signature = _decode_segment(encoded_signature)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise AccessTokenError("Invalid Access token") from exc

    key_id = header.get("kid")
    if (
        header.get("alg") != "RS256"
        or header.get("crit")
        or not isinstance(key_id, str)
        or not key_id
    ):
        raise AccessTokenError("Invalid Access token")

    key_set = jwks if jwks is not None else _get_jwks(team_domain)
    raw_keys = key_set.get("keys") if isinstance(key_set, dict) else None
    keys = raw_keys if isinstance(raw_keys, list) else []
    key = next(
        (
            item
            for item in keys or []
            if isinstance(item, dict)
            and item.get("kid") == key_id
            and item.get("kty") == "RSA"
            and item.get("use", "sig") == "sig"
            and item.get("alg", "RS256") == "RS256"
        ),
        None,
    )
    if key is None:
        raise AccessTokenError("Invalid Access token")

    try:
        modulus = int.from_bytes(_decode_segment(str(key["n"])), "big")
        exponent = int.from_bytes(_decode_segment(str(key["e"])), "big")
        public_key = rsa.RSAPublicNumbers(exponent, modulus).public_key()
        if public_key.key_size < 2048:
            raise AccessTokenError("Invalid Access token")
        public_key.verify(
            signature,
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except (KeyError, ValueError, InvalidSignature) as exc:
        raise AccessTokenError("Invalid Access token") from exc

    current_time = time.time() if now is None else now
    exp = claims.get("exp")
    nbf = claims.get("nbf")
    issued_at = claims.get("iat")
    if (
        claims.get("iss") != team_domain.rstrip("/")
        or not _audience_matches(claims.get("aud"), audience)
        or not _is_numeric_date(exp)
        or current_time >= exp
        or (nbf is not None and (not _is_numeric_date(nbf) or current_time < nbf))
        or (issued_at is not None and (not _is_numeric_date(issued_at) or issued_at > current_time))
    ):
        raise AccessTokenError("Invalid Access token")
    return claims


def validate_access_configuration(team_domain: str | None, audience: str | None) -> str | None:
    if not team_domain and not audience:
        return None
    if not team_domain or not audience:
        raise ValueError("Cần cấu hình đồng thời Cloudflare Access team domain và audience.")
    normalized = team_domain.rstrip("/")
    from urllib.parse import urlsplit

    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".cloudflareaccess.com")
        or parsed.port is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Cloudflare Access team domain phải là HTTPS origin hợp lệ.")
    return normalized


def _get_jwks(team_domain: str) -> dict[str, object]:
    endpoint = f"{team_domain.rstrip('/')}/cdn-cgi/access/certs"
    now = time.monotonic()
    with _cache_lock:
        cached = _jwks_cache.get(endpoint)
        if cached and cached[0] > now:
            return cached[1]

    request = Request(endpoint, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=3) as response:
            raw = response.read(65_537)
    except (URLError, TimeoutError, OSError) as exc:
        raise AccessTokenError("Không xác minh được phiên Cloudflare Access.") from exc
    if len(raw) > 65_536:
        raise AccessTokenError("Không xác minh được phiên Cloudflare Access.")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise AccessTokenError("Không xác minh được phiên Cloudflare Access.") from exc
    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
        raise AccessTokenError("Không xác minh được phiên Cloudflare Access.")
    with _cache_lock:
        _jwks_cache[endpoint] = (time.monotonic() + _JWKS_CACHE_TTL_SECONDS, document)
    return document


def _decode_segment(value: str) -> bytes:
    if not value or any(char.isspace() for char in value):
        raise ValueError("Invalid base64url segment")
    padded = value + "=" * (-len(value) % 4)
    return base64.b64decode(padded, altchars=b"-_", validate=True)


def _decode_json(value: str) -> dict[str, object]:
    document = json.loads(_decode_segment(value))
    if not isinstance(document, dict):
        raise ValueError("JWT section must be an object")
    return document


def _audience_matches(value: object, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    return (
        isinstance(value, list)
        and expected in value
        and all(isinstance(item, str) for item in value)
    )


def _is_numeric_date(value: object) -> bool:
    if isinstance(value, int) and not isinstance(value, bool):
        return True
    return isinstance(value, float) and math.isfinite(value)
