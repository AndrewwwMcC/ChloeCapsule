"""One family password (view) and one admin password (view + upload + delete).
Login is kept in a signed cookie; "remember this device" keeps it for a year."""
import hmac
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import settings

COOKIE = "kc_session"
REMEMBER_SECONDS = 365 * 24 * 3600
_signer = URLSafeTimedSerializer(settings.session_secret, salt="kid-capsule")

_failures: dict[str, list[float]] = defaultdict(list)
MAX_FAILURES, WINDOW = 10, 15 * 60


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def too_many_attempts(ip: str) -> bool:
    now = time.time()
    _failures[ip] = [t for t in _failures[ip] if now - t < WINDOW]
    return len(_failures[ip]) >= MAX_FAILURES


def record_failure(ip: str) -> None:
    _failures[ip].append(time.time())


def check_password(password: str) -> str | None:
    pw = password.encode()
    if hmac.compare_digest(pw, settings.admin_password.encode()):
        return "admin"
    if hmac.compare_digest(pw, settings.family_password.encode()):
        return "family"
    return None


def make_cookie(role: str) -> str:
    return _signer.dumps({"role": role})


def role_of(request: Request) -> str | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _signer.loads(raw, max_age=REMEMBER_SECONDS)
    except BadSignature:
        return None
    role = data.get("role")
    return role if role in ("family", "admin") else None


def require_admin(request: Request) -> None:
    if role_of(request) != "admin":
        raise HTTPException(status_code=403, detail="Admins only")


def token_ok(request: Request) -> bool:
    if not settings.upload_token:
        return False
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.headers.get("x-upload-token", "")
    return bool(token) and hmac.compare_digest(token.encode(), settings.upload_token.encode())
