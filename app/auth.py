import hashlib
import hmac
import secrets

from fastapi import Request
from fastapi.responses import RedirectResponse

from .config import get_settings

COOKIE_NAME = "brokershield_session"


def _session_token() -> str:
    settings = get_settings()
    secret = hashlib.sha256(f"brokershield:{settings.admin_password}".encode()).digest()
    return hmac.new(secret, b"admin-session", hashlib.sha256).hexdigest()


def is_authenticated(request: Request) -> bool:
    return hmac.compare_digest(request.cookies.get(COOKIE_NAME, ""), _session_token())


def login_response(password: str) -> RedirectResponse | None:
    if not secrets.compare_digest(password, get_settings().admin_password):
        return None
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        _session_token(),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return response


def logout_response() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


PUBLIC_PATHS = {"/login", "/healthz"}


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/static"):
        return await call_next(request)
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)
