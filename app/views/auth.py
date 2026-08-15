"""Authentication views."""
from __future__ import annotations

import secrets
from datetime import timedelta

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from ..audit import audit
from ..models import LoginAttempt, PasswordReset, User, db, now_naive
from ..security import (client_ip, password_strength_errors, rate_limit,
                        require_login)

bp = Blueprint("auth", __name__)

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5

# pages reachable while a password change is pending
ALLOWED_WHEN_PENDING = ("auth.change_password", "auth.change_password_post",
                        "auth.logout", "static")


@bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("login.html", next=request.args.get("next", ""))


def _lock_row(username: str) -> LoginAttempt:
    row = db.session.query(LoginAttempt).filter_by(username=username).first()
    if row is None:
        row = LoginAttempt(username=username, failures=0)
        db.session.add(row)
        db.session.flush()
    return row


def _lockout_remaining(row: LoginAttempt) -> int:
    """Minutes left on an active lockout, else 0."""
    if row.locked_until and row.locked_until > now_naive():
        return max(1, int((row.locked_until - now_naive()).total_seconds() // 60) + 1)
    return 0


@bp.post("/login")
@rate_limit(limit=8, window=60.0, key_extra="login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    nxt = request.form.get("next") or ""

    max_fail = current_app.config.get("LOGIN_MAX_FAILURES", 10)
    lock_mins = current_app.config.get("LOGIN_LOCKOUT_MINUTES", 15)

    # Account-scoped brute-force gate. The per-IP limiter cannot help when every
    # request arrives from the same proxy, so failures are also counted per user.
    lock = _lock_row(username) if username else None
    if lock is not None:
        left = _lockout_remaining(lock)
        if left:
            audit("LOGIN_LOCKED_OUT", detail={"username": username})
            db.session.commit()
            flash(f"Too many failed attempts. Try again in {left} minute(s), "
                  "or use 'Forgot password'.", "error")
            return render_template("login.html", next=nxt, username=username), 429

    user = db.session.query(User).filter_by(username=username).first()
    if not user or not user.check_password(password):
        if lock is not None:
            lock.failures = (lock.failures or 0) + 1
            lock.last_failure_at = now_naive()
            lock.last_ip = client_ip()
            if lock.failures >= max_fail:
                lock.locked_until = now_naive() + timedelta(minutes=lock_mins)
                lock.failures = 0
                audit("ACCOUNT_LOCKED", "user", user.id if user else None,
                      {"username": username, "minutes": lock_mins})
        audit("LOGIN_FAILED", detail={"username": username})
        db.session.commit()
        flash("Invalid username or password.", "error")
        return render_template("login.html", next=nxt, username=username), 401
    if lock is not None:
        lock.failures = 0
        lock.locked_until = None
    if not user.active:
        flash("This account is deactivated. Contact your system administrator.", "error")
        return render_template("login.html", next=nxt, username=username), 403
    if not getattr(user, "approved", True):
        # Bulk-uploaded accounts exist but must be approved by an administrator
        # before they can be used. The password was correct, so say so plainly.
        audit("LOGIN_UNAPPROVED", "user", user.id, {"username": username})
        db.session.commit()
        flash("Your account is waiting for administrator approval. "
              "Please ask your hospital administrator to approve it.", "error")
        return render_template("login.html", next=nxt, username=username), 403
    login_user(user, remember=False)
    session.permanent = True
    user.last_login_at = now_naive()
    db.session.commit()
    audit("LOGIN", "user", user.id, {"username": user.username}, user=user, org_id=user.org_id)
    if user.must_change_password:
        flash("This is a temporary password. Please choose your own password now.", "info")
        return redirect(url_for("auth.change_password"))
    if nxt and nxt.startswith("/"):
        return redirect(nxt)
    return redirect(url_for("main.dashboard"))


@bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        audit("LOGOUT", "user", current_user.id, user=current_user, org_id=current_user.org_id)
    logout_user()
    return redirect(url_for("auth.login"))


# ------------------------------------------------------------------ forced password change
@bp.get("/change-password")
@require_login
def change_password():
    return render_template("change_password.html")


@bp.post("/change-password")
@require_login
def change_password_post():
    current_pw = request.form.get("current_password") or ""
    new_pw = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""
    if not current_user.check_password(current_pw):
        flash("Your current password is incorrect.", "error")
        return render_template("change_password.html"), 401
    if new_pw != confirm:
        flash("The new passwords do not match.", "error")
        return render_template("change_password.html"), 422
    errs = password_strength_errors(new_pw)
    if errs:
        for e in errs:
            flash(e, "error")
        return render_template("change_password.html"), 422
    if new_pw == current_pw:
        flash("The new password must be different from the old one.", "error")
        return render_template("change_password.html"), 422
    current_user.set_password(new_pw)
    current_user.must_change_password = False
    audit("PASSWORD_CHANGED", "user", current_user.id, {"self": True})
    db.session.commit()
    flash("Password updated successfully.", "success")
    return redirect(url_for("main.dashboard"))


def enforce_pending_password_change():
    """Before-request guard: users with a temporary password can only reach
    the change-password page and logout."""
    if not current_user.is_authenticated:
        return None
    if not current_user.must_change_password:
        return None
    if request.endpoint in ALLOWED_WHEN_PENDING:
        return None
    return redirect(url_for("auth.change_password"))


# ================================================================ self-service password reset
def _find_active_user(identifier: str):
    ident = (identifier or "").strip()
    if not ident:
        return None
    q = db.session.query(User).filter_by(active=True)
    u = q.filter(User.username == ident.lower()).first()
    if u:
        return u
    digits = ident.replace(" ", "").replace("-", "").replace("+", "")
    return db.session.query(User).filter_by(active=True).filter(
        User.phone.like(f"%{digits[-9:]}%") if len(digits) >= 9 else User.phone == ident).first()


@bp.get("/forgot-password")
def forgot_password():
    return render_template("forgot_password.html")


@bp.post("/forgot-password")
@rate_limit(limit=5, window=300.0, key_extra="forgot")
def forgot_password_post():
    identifier = request.form.get("identifier") or ""
    user = _find_active_user(identifier)
    # Generic message regardless — never reveal whether an account exists.
    flash("If that username or phone number exists and is active, a 6-digit reset "
          "code has been sent to the registered phone (or email). It expires in "
          f"{OTP_TTL_MINUTES} minutes.", "info")
    if user is None:
        return redirect(url_for("auth.forgot_password"))

    otp = f"{secrets.randbelow(1000000):06d}"
    # invalidate previous unused codes for this user
    db.session.query(PasswordReset).filter_by(user_id=user.id, used_at=None).update(
        {"used_at": now_naive()})
    db.session.add(PasswordReset(user_id=user.id, otp_hash=generate_password_hash(otp),
                                 channel="sms",
                                 expires_at=now_naive() + timedelta(minutes=OTP_TTL_MINUTES)))
    db.session.commit()

    body = f"{OTP_TTL_MINUTES}-min password reset code: {otp}. If you did not request this, ignore it."
    delivered = False
    if user.phone:
        from .. import sms as sms_engine
        from ..tasks import dispatch_delivery
        from flask import current_app
        sms_engine.queue_sms(user.org_id, user.phone, body, kind="alert",
                             entity_type="password_reset", entity_id=user.id)
        dispatch_delivery()
        if current_app.config.get("SMS_MODE", "sandbox") == "sandbox":
            print(f"[DEV] password-reset OTP for {user.username}: {otp}")
        delivered = True
    if not delivered and user.email:
        from ..notifications import _send_email
        err = _send_email(user, "Password reset code", body)
        delivered = err is None
    if not delivered:
        # no channel available — dev/demo fallback only; production must have SMS/email
        print(f"[DEV] no delivery channel; password-reset OTP for {user.username}: {otp}")
    audit("PASSWORD_RESET_REQUESTED", "user", user.id, {"channel": "sms" if user.phone else "email"})
    db.session.commit()
    return redirect(url_for("auth.reset_password"))


@bp.get("/reset-password")
def reset_password():
    return render_template("reset_password.html")


@bp.post("/reset-password")
@rate_limit(limit=8, window=300.0, key_extra="reset")
def reset_password_post():
    identifier = request.form.get("identifier") or ""
    otp = (request.form.get("otp") or "").strip()
    new_pw = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""

    user = _find_active_user(identifier)
    row = None
    if user:
        row = (db.session.query(PasswordReset)
               .filter_by(user_id=user.id, used_at=None)
               .order_by(PasswordReset.id.desc()).first())

    def fail(msg):
        flash(msg, "error")
        return render_template("reset_password.html"), 401

    if not user or not row:
        return fail("Invalid request. Start again from 'Forgot password'.")
    if row.expires_at < now_naive():
        return fail("That code has expired. Request a new one.")
    if row.attempts >= OTP_MAX_ATTEMPTS:
        return fail("Too many attempts. Request a new code.")
    row.attempts += 1
    if not check_password_hash(row.otp_hash, otp):
        db.session.commit()
        return fail("Incorrect code. Check the 6 digits and try again.")

    if new_pw != confirm:
        db.session.commit()
        return fail("The new passwords do not match.")
    errs = password_strength_errors(new_pw)
    if errs:
        db.session.commit()
        for e in errs:
            flash(e, "error")
        return render_template("reset_password.html"), 422

    row.used_at = now_naive()
    user.set_password(new_pw)
    user.must_change_password = False
    audit("PASSWORD_RESET_COMPLETED", "user", user.id, {"self_service": True})
    db.session.commit()
    flash("Password updated. Sign in with your new password.", "success")
    return redirect(url_for("auth.login"))
