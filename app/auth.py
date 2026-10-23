"""One password for the whole site (SITE_PASSWORD), which grants everything:
view, upload, delete, covers, download. Login is kept in a signed cookie for 90 days.

The cookie is signed with a key derived from SESSION_SECRET *and* the password, so
changing SITE_PASSWORD logs every device out — no need to rotate SESSION_SECRET too.

The iOS Shortcut has its own token (SHORTCUT_TOKEN), good for uploading and nothing else."""
import hashlib
import hmac
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import settings

COOKIE = "kc_session"
SESSION_SECONDS = 90 * 24 * 3600  # 90 days

_failures: dict[str, list[float]] = defaultdict(list)
MAX_FAILURES, WINDOW = 5, 15 * 60


def _session_key() -> str:
    """Signing key tied to the current password: change it and every cookie dies."""
    return hmac.new(settings.session_secret.encode(), b"kid-capsule|" + settings.site_password.encode(),
                    hashlib.sha256).hexdigest()


_signer = URLSafeTimedSerializer(_session_key(), salt="kid-capsule-session")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def too_many_attempts(ip: str) -> bool:
    now = time.time()
    _failures[ip] = [t for t in _failures[ip] if now - t < WINDOW]
    return len(_failures[ip]) >= MAX_FAILURES


def record_failure(ip: str) -> None:
    _failures[ip].append(time.time())


def clear_failures(ip: str) -> None:
    _failures.pop(ip, None)


def password_ok(password: str) -> bool:
    return hmac.compare_digest(password.encode(), settings.site_password.encode())


def make_cookie() -> str:
    return _signer.dumps({"v": 1})


def logged_in(request: Request) -> bool:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return False
    try:
        _signer.loads(raw, max_age=SESSION_SECONDS)
    except BadSignature:
        return False
    return True


def require_session(request: Request) -> None:
    if not logged_in(request):
        raise HTTPException(status_code=401, detail="Log in first")


def shortcut_token_ok(request: Request) -> bool:
    if not settings.shortcut_token:
        return False
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.headers.get("x-shortcut-token", "")
    return bool(token) and hmac.compare_digest(token.encode(), settings.shortcut_token.encode())
