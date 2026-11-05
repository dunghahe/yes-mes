import hmac
import secrets

from fastapi import Request, Response

CSRF_COOKIE_NAME = "mes_csrf"


def issue_csrf_token(response: Response) -> str:
    token = secrets.token_urlsafe(32)
    set_csrf_cookie(response, token)
    return token


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
