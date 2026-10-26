"""
Admin authentication.

Before: the admin username/password and a fixed admin token were written in
index.html (public on GitHub), so anyone could read every participant's name,
email and phone. Now:
  - credentials live only on the server (ADMIN_USERNAME / ADMIN_PASSWORD in .env
    or the hosting dashboard),
  - POST /api/admin/login returns a signed token that expires (ADMIN_TOKEN_HOURS),
  - admin routes require "Authorization: Bearer <token>",
  - 5 failed logins from one address lock it out for 5 minutes.
A static X-Admin-Token is still accepted for scripts, but only if ADMIN_API_TOKEN
is explicitly set — there is no built-in default any more.
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from typing import Dict, List, Optional

from fastapi import Header, HTTPException, Request

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")                 # no default: login disabled until set
# Optional PBKDF2-SHA256 hash of the admin password, so the secret itself need not
# sit in .env in the clear. Format: "pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>".
# When set it takes precedence over ADMIN_PASSWORD.
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH")
ADMIN_SECRET = os.getenv("ADMIN_SECRET") or secrets.token_hex(32)   # random = tokens reset on restart
ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN")               # optional, for scripts
TOKEN_HOURS = float(os.getenv("ADMIN_TOKEN_HOURS", "8"))

MAX_FAILURES = 5
LOCKOUT_SECONDS = 300
MAX_TRACKED_CLIENTS = 4096          # bounds _failures so rotating IPs cannot grow it forever
_failures: Dict[str, List[float]] = {}
_lock = threading.Lock()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _safe_eq(a: Optional[str], b: Optional[str]) -> bool:
    """
    Constant-time string comparison that never raises on non-ASCII input.

    hmac.compare_digest() rejects any str containing a non-ASCII code point and
    raises TypeError. Header values are attacker-controlled, so a request with
    `X-Session-Token: café` used to escape verify_token() as an unhandled 500.
    Encoding to bytes first makes the comparison total.
    """
    if a is None or b is None:
        return False
    return hmac.compare_digest(a.encode("utf-8", "surrogatepass"),
                              b.encode("utf-8", "surrogatepass"))


def _sign(payload: str) -> str:
    return _b64(hmac.new(ADMIN_SECRET.encode(), payload.encode(), hashlib.sha256).digest())


def create_token(username: str) -> dict:
    expires = int(time.time() + TOKEN_HOURS * 3600)
    payload = _b64(json.dumps({"u": username, "exp": expires}).encode())
    return {"token": f"{payload}.{_sign(payload)}", "expires_at": expires, "username": username}


def verify_token(token: str) -> Optional[str]:
    try:
        payload, sig = token.split(".", 1)
        if not _safe_eq(sig, _sign(payload)):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if not isinstance(data, dict):
            return None
        return data["u"] if data["exp"] > time.time() else None
    except (ValueError, KeyError, TypeError, AttributeError,
            json.JSONDecodeError, binascii.Error, UnicodeDecodeError):
        return None


def _password_matches(password: str) -> bool:
    """Check a submitted password against ADMIN_PASSWORD_HASH, or ADMIN_PASSWORD."""
    if ADMIN_PASSWORD_HASH:
        try:
            algo, iterations, salt_hex, hash_hex = ADMIN_PASSWORD_HASH.split("$")
            if algo != "pbkdf2_sha256":
                return False
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
            )
            return hmac.compare_digest(digest.hex(), hash_hex)
        except (ValueError, TypeError):
            return False
    return _safe_eq(password, ADMIN_PASSWORD)


def check_login(request: Request, username: str, password: str) -> dict:
    """Validate credentials with brute-force protection. Returns a token or raises."""
    if not ADMIN_PASSWORD and not ADMIN_PASSWORD_HASH:
        raise HTTPException(status_code=503, detail="Admin login is not configured - set ADMIN_PASSWORD_HASH or ADMIN_PASSWORD on the server.")
    client = request.client.host if request.client else "unknown"
    now = time.time()
    with _lock:
        recent = [t for t in _failures.get(client, []) if now - t < LOCKOUT_SECONDS]
        _failures[client] = recent
        if len(_failures) > MAX_TRACKED_CLIENTS:
            # Evict the least-recently-seen address so a rotating source cannot
            # grow this dict without bound.
            for stale in sorted(_failures, key=lambda k: (_failures[k][-1] if _failures[k] else 0))[:len(_failures) - MAX_TRACKED_CLIENTS]:
                _failures.pop(stale, None)
        if len(recent) >= MAX_FAILURES:
            wait = int(LOCKOUT_SECONDS - (now - recent[0]))
            raise HTTPException(status_code=429, detail=f"Too many failed attempts - try again in {wait // 60 + 1} min.",
                                headers={"Retry-After": str(wait)})
    # Both comparisons always run so a wrong username and a wrong password cost
    # the same time.
    ok = _safe_eq(username, ADMIN_USERNAME) and _password_matches(password)
    if not ok:
        with _lock:
            _failures.setdefault(client, []).append(now)
        raise HTTPException(status_code=401, detail="Incorrect username or password.")
    with _lock:
        _failures.pop(client, None)
    return create_token(username)


def require_admin(authorization: Optional[str] = Header(default=None),
                  x_admin_token: Optional[str] = Header(default=None)) -> str:
    """FastAPI dependency for admin-only routes."""
    if authorization and authorization.lower().startswith("bearer "):
        user = verify_token(authorization[7:].strip())
        if user:
            return user
    if ADMIN_API_TOKEN and _safe_eq(x_admin_token, ADMIN_API_TOKEN):
        return "api-token"
    raise HTTPException(status_code=401, detail="Admin login required", headers={"WWW-Authenticate": "Bearer"})


# ─────────────────────────────────────────────────────────────────────────────
# Participant session access
# ─────────────────────────────────────────────────────────────────────────────
# Session ids are UUID4, which is not secret in practice: they appear in browser
# history, logs and screenshots. Every route that returns a participant's own
# personal data therefore also requires the access_token minted when the session
# was created. The token is per-session, random, and never leaves the browser
# except in the X-Session-Token header.

def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_token_matches(stored: Optional[str], presented: Optional[str]) -> bool:
    """Constant-time comparison of the session's stored token against the header."""
    if not stored or not presented:
        return False
    return _safe_eq(stored, presented)


def _looks_like_session_token(token: str) -> bool:
    """
    Shape check for a participant token: secrets.token_urlsafe(32) is always
    43 url-safe base64 characters.

    require_session_access() cannot compare against the stored value (it does not
    know which session is being asked for), so it must at least reject garbage.
    Without this, any non-empty header short-circuited the admin path and the
    route's own session_token_matches() call became the only thing standing
    between a caller and another participant's data.
    """
    return len(token) == 43 and all(c.isalnum() or c in "-_" for c in token)


def require_session_access(
    authorization: Optional[str] = Header(default=None),
    x_session_token: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> Optional[str]:
    """
    FastAPI dependency for participant data routes.

    Accepts EITHER the session's own access token (X-Session-Token) OR a valid
    admin token (Authorization: Bearer / X-Admin-Token), so the admin panel can
    still open any participant's report. Raises 401 otherwise.

    IMPORTANT: this only identifies WHO is asking. It does NOT prove the token
    belongs to the session in the path. Every route using it must still call
    session_token_matches() against the loaded session, and pass the returned
    caller string to its _load_session / _get_session_for helper - otherwise the
    caller string is ignored and the check is decorative.
    """
    if x_session_token and _looks_like_session_token(x_session_token):
        return f"session:{x_session_token}"
    # An admin token also grants access - admins are expected to read any report.
    # Tried even when a session token is present, so a stale browser token cannot
    # silently downgrade an admin request to a 403.
    try:
        return require_admin(authorization=authorization, x_admin_token=x_admin_token)
    except HTTPException:
        pass
    raise HTTPException(
        status_code=401,
        detail="This session's access token is required to view participant data.",
        headers={"WWW-Authenticate": "Bearer"},
    )

