import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from app import main
from app.core import cloudflare_access
from app.core.cloudflare_access import (
    AccessTokenError,
    validate_access_configuration,
    verify_access_token,
)

TEAM_DOMAIN = "https://mes-team.cloudflareaccess.com"
AUDIENCE = "mes-application-audience"
CURRENT_TIME = 1_800_000_000


@pytest.fixture(scope="module")
def signing_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    jwk = {
        "kid": "test-key",
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "n": _encode_segment(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
        "e": _encode_segment(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
    }
    return private_key, {"keys": [jwk]}


def test_access_jwt_accepts_valid_signature_and_claims(signing_material) -> None:
    private_key, jwks = signing_material
    token = _make_token(private_key)

    claims = verify_access_token(
        token,
        team_domain=TEAM_DOMAIN,
        audience=AUDIENCE,
        now=CURRENT_TIME,
        jwks=jwks,
    )

    assert claims["iss"] == TEAM_DOMAIN
    assert AUDIENCE in claims["aud"]


@pytest.mark.parametrize(
    "claim_changes",
    [
        {"iss": "https://wrong.cloudflareaccess.com"},
        {"aud": ["another-application"]},
        {"exp": CURRENT_TIME},
        {"nbf": CURRENT_TIME + 1},
        {"nbf": True},
        {"iat": CURRENT_TIME + 1},
        {"exp": "later"},
        {"exp": float("nan")},
    ],
)
def test_access_jwt_rejects_invalid_claims(signing_material, claim_changes) -> None:
    private_key, jwks = signing_material
    token = _make_token(private_key, **claim_changes)

    with pytest.raises(AccessTokenError):
        verify_access_token(
            token,
            team_domain=TEAM_DOMAIN,
            audience=AUDIENCE,
            now=CURRENT_TIME,
            jwks=jwks,
        )


def test_access_jwt_rejects_tampered_signature_and_unknown_key(signing_material) -> None:
    private_key, jwks = signing_material
    token = _make_token(private_key)
    header, _, signature = token.split(".")
    tampered_payload = _encode_segment(b'{"aud":"attacker"}')
    tampered = f"{header}.{tampered_payload}.{signature}"
    unknown_key = {"keys": [{**jwks["keys"][0], "kid": "another-key"}]}

    with pytest.raises(AccessTokenError):
        verify_access_token(
            tampered,
            team_domain=TEAM_DOMAIN,
            audience=AUDIENCE,
            now=CURRENT_TIME,
            jwks=jwks,
        )
    with pytest.raises(AccessTokenError):
        verify_access_token(
            token,
            team_domain=TEAM_DOMAIN,
            audience=AUDIENCE,
            now=CURRENT_TIME,
            jwks=unknown_key,
        )


def test_access_jwt_rejects_non_rs256_algorithm(signing_material) -> None:
    private_key, jwks = signing_material
    token = _make_token(private_key, algorithm="HS256")

    with pytest.raises(AccessTokenError):
        verify_access_token(
            token,
            team_domain=TEAM_DOMAIN,
            audience=AUDIENCE,
            now=CURRENT_TIME,
            jwks=jwks,
        )


def test_access_configuration_requires_a_valid_origin_and_audience() -> None:
    assert validate_access_configuration(None, None) is None
    assert validate_access_configuration(TEAM_DOMAIN + "/", AUDIENCE) == TEAM_DOMAIN
    with pytest.raises(ValueError, match="đồng thời"):
        validate_access_configuration(TEAM_DOMAIN, None)
    with pytest.raises(ValueError, match="HTTPS"):
        validate_access_configuration("http://mes-team.cloudflareaccess.com", AUDIENCE)
    with pytest.raises(ValueError, match="HTTPS"):
        validate_access_configuration(TEAM_DOMAIN + "/path", AUDIENCE)
    with pytest.raises(ValueError, match="HTTPS"):
        validate_access_configuration("https://example.com", AUDIENCE)


def test_app_rejects_missing_or_invalid_access_assertion(monkeypatch) -> None:
    def verify(token, *, team_domain, audience):
        if token != "valid-access-token":
            raise AccessTokenError("invalid")
        assert team_domain == TEAM_DOMAIN
        assert audience == AUDIENCE

    monkeypatch.setattr(main, "access_team_domain", TEAM_DOMAIN)
    monkeypatch.setattr(main.settings, "cloudflare_access_audience", AUDIENCE)
    monkeypatch.setattr(main, "verify_access_token", verify)
    with TestClient(main.app) as client:
        assert client.get("/health/live").status_code == 403
        invalid = client.get(
            "/health/live", headers={"Cf-Access-Jwt-Assertion": "invalid-access-token"}
        )
        valid = client.get(
            "/health/live", headers={"Cf-Access-Jwt-Assertion": "valid-access-token"}
        )

    assert invalid.status_code == 403
    assert valid.status_code == 200
    assert "Content-Security-Policy" in invalid.headers


def test_access_jwks_fetch_uses_certs_endpoint_and_caches_keys(monkeypatch) -> None:
    document = {"keys": [{"kid": "rotation-key", "kty": "RSA"}]}
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(document).encode()

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return FakeResponse()

    monkeypatch.setattr(cloudflare_access, "urlopen", fake_urlopen)
    cloudflare_access._jwks_cache.clear()
    try:
        assert cloudflare_access._get_jwks(TEAM_DOMAIN) == document
        assert cloudflare_access._get_jwks(TEAM_DOMAIN) == document
        assert calls == [(f"{TEAM_DOMAIN}/cdn-cgi/access/certs", 3)]
    finally:
        cloudflare_access._jwks_cache.clear()


def _make_token(private_key, **claim_changes) -> str:
    algorithm = claim_changes.pop("algorithm", "RS256")
    header = {"alg": algorithm, "kid": "test-key", "typ": "JWT"}
    claims = {
        "iss": TEAM_DOMAIN,
        "aud": [AUDIENCE],
        "exp": CURRENT_TIME + 300,
        "nbf": CURRENT_TIME - 10,
        "iat": CURRENT_TIME - 10,
        **claim_changes,
    }
    signing_input = (
        f"{_encode_segment(json.dumps(header).encode())}."
        f"{_encode_segment(json.dumps(claims).encode())}"
    )
    signature = private_key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_encode_segment(signature)}"


def _encode_segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
