import hmac
import secrets

from fastapi import Request, Response

CSRF_COOKIE_NAME = "mes_csrf"


def issue_csrf_token(response: Response) -> str:
    token = secrets.token_urlsafe(32)
    set_csrf_cookie(response, token)
    return token


def csrf_token_for_request(request: Request) -> str:
    """Reuse the browser's synchronizer token so forms in other tabs stay valid."""
    token = request.cookies.get(CSRF_COOKIE_NAME, "")
    if 32 <= len(token) <= 128 and token.isascii():
        return token
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        secure=True,
        httponly=False,
        samesite="strict",
        path="/",
    )


def csrf_is_valid(request: Request, submitted_token: str) -> bool:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
    return bool(cookie_token and submitted_token) and hmac.compare_digest(
        cookie_token, submitted_token
    )
