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
ADMIN_SECRET = os.getenv("ADMIN_SECRET") or secrets.token_hex(32)   # random = tokens reset on restart
ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN")               # optional, for scripts
TOKEN_HOURS = float(os.getenv("ADMIN_TOKEN_HOURS", "8"))

MAX_FAILURES = 5
LOCKOUT_SECONDS = 300
_failures: Dict[str, List[float]] = {}
_lock = threading.Lock()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign(payload: str) -> str:
    return _b64(hmac.new(ADMIN_SECRET.encode(), payload.encode(), hashlib.sha256).digest())


def create_token(username: str) -> dict:
    expires = int(time.time() + TOKEN_HOURS * 3600)
    payload = _b64(json.dumps({"u": username, "exp": expires}).encode())
    return {"token": f"{payload}.{_sign(payload)}", "expires_at": expires, "username": username}


def verify_token(token: str) -> Optional[str]:
    try:
        payload, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return data["u"] if data["exp"] > time.time() else None
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def check_login(request: Request, username: str, password: str) -> dict:
    """Validate credentials with brute-force protection. Returns a token or raises."""
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Admin login is not configured - set ADMIN_PASSWORD on the server.")
    client = request.client.host if request.client else "unknown"
    now = time.time()
    with _lock:
        recent = [t for t in _failures.get(client, []) if now - t < LOCKOUT_SECONDS]
        _failures[client] = recent
        if len(recent) >= MAX_FAILURES:
            wait = int(LOCKOUT_SECONDS - (now - recent[0]))
            raise HTTPException(status_code=429, detail=f"Too many failed attempts - try again in {wait // 60 + 1} min.",
                                headers={"Retry-After": str(wait)})
    ok = (hmac.compare_digest(username.encode(), ADMIN_USERNAME.encode())
          & hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode()))
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
    if ADMIN_API_TOKEN and x_admin_token and hmac.compare_digest(x_admin_token, ADMIN_API_TOKEN):
        return "api-token"
    raise HTTPException(status_code=401, detail="Admin login required", headers={"WWW-Authenticate": "Bearer"})
