"""Security primitives: CSRF, rate limiting, password policy, safe uploads, RBAC."""
from __future__ import annotations

import functools
import os
import re
import secrets
import time
from collections import defaultdict, deque

from flask import abort, redirect, render_template, request, session, url_for
from flask_login import current_user

from .config import Config

# ------------------------------------------------------------------ CSRF
def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


CSRF_EXEMPT: set[str] = set()  # endpoint names exempt (webhooks / USSD API)


def csrf_exempt(view_name: str):
    """Usage: @csrf_exempt('api.whatsapp_webhook') above the route decorator."""
    CSRF_EXEMPT.add(view_name)

    def deco(fn):
        return fn
    return deco


def csrf_protect():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    if request.endpoint in CSRF_EXEMPT:
        return None
    token = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
    if not token or token != session.get("_csrf"):
        abort(403, description="Invalid or missing CSRF token. Refresh the page and try again.")
    return None


# ------------------------------------------------------------------ RBAC
def require_login(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.path))
        return fn(*a, **kw)
    return wrapper


def require_role(*roles):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.path))
            if current_user.role not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def same_org_or_super(entity_org_id: int):
    """Ensure the current user belongs to the entity's tenant (super admin of same org)."""
    if current_user.org_id != entity_org_id:
        abort(403)


# ------------------------------------------------------------------ rate limiting
class RateLimiter:
    def __init__(self):
        self.hits = defaultdict(deque)

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        # bound memory: drop stale keys occasionally
        if len(self.hits) > 10000:
            for k in [k for k, dq in self.hits.items() if not dq or now - dq[-1] > 600]:
                del self.hits[k]
        dq = self.hits[key]
        while dq and now - dq[0] > window:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True


_limiter = RateLimiter()


def rate_limit(limit: int = 10, window: float = 60.0, key_extra: str = ""):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            key = f"{request.endpoint}|{request.remote_addr}|{key_extra}"
            if not _limiter.allow(key, limit, window):
                return render_template("error.html", code=429,
                                       message="Too many requests. Please wait a moment and try again."), 429
            return fn(*a, **kw)
        return wrapper
    return deco


# ------------------------------------------------------------------ password policy
PASSWORD_MIN_LEN = 8


def password_strength_errors(pw: str) -> list[str]:
    errors = []
    if len(pw) < PASSWORD_MIN_LEN:
        errors.append(f"Password must be at least {PASSWORD_MIN_LEN} characters.")
    if not re.search(r"[A-Za-z]", pw):
        errors.append("Password must contain letters.")
    if not re.search(r"\d", pw):
        errors.append("Password must contain numbers.")
    if not re.search(r"[^A-Za-z0-9]", pw) and len(pw) < 12:
        errors.append("Use a symbol or make the password at least 12 characters.")
    return errors


# ------------------------------------------------------------------ file uploads
ALLOWED_UPLOAD_EXT = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".pdf": "application/pdf",
}
UPLOAD_MAGIC = [
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG", ".png"),
    (b"RIFF", ".webp"),
    (b"%PDF", ".pdf"),
]


def validate_upload(file_storage) -> tuple[str | None, str | None]:
    """Return (safe_filename, error). Validates extension, size and magic bytes."""
    if file_storage is None or not file_storage.filename:
        return None, "No file was provided."
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        return None, "Only JPG, PNG, WEBP or PDF files are allowed."
    data = file_storage.read(Config.MAX_UPLOAD_BYTES + 1)
    if len(data) > Config.MAX_UPLOAD_BYTES:
        return None, "File is too large (maximum 5 MB)."
    if not any(data.startswith(m) for m, _ in UPLOAD_MAGIC):
        return None, "The file content does not match a valid image or PDF."
    safe = f"{int(time.time())}-{secrets.token_hex(6)}{ext}"
    return safe, None


def save_upload(file_storage, subfolder: str) -> tuple[str | None, str | None]:
    """Validate + persist an upload. Returns (relative_path, error)."""
    safe, err = validate_upload(file_storage)
    if err:
        return None, err
    dest_dir = os.path.join(Config.UPLOAD_DIR, subfolder)
    os.makedirs(dest_dir, exist_ok=True)
    file_storage.seek(0)
    file_storage.save(os.path.join(dest_dir, safe))
    return f"{subfolder}/{safe}", None


def resolve_upload_path(rel_path: str) -> str | None:
    if not rel_path:
        return None
    full = os.path.normpath(os.path.join(Config.UPLOAD_DIR, rel_path))
    if not full.startswith(os.path.normpath(Config.UPLOAD_DIR)):
        return None
    return full if os.path.isfile(full) else None


# ------------------------------------------------------------------ hooks
def register_security_hooks(app):
    app.before_request(csrf_protect)

    from .views.auth import enforce_pending_password_change
    app.before_request(enforce_pending_password_change)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(self), geolocation=(self)")
        if request.path.startswith("/static/"):
            resp.headers.setdefault("Cache-Control", "public, max-age=3600")
        else:
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp
