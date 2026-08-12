"""Authentication views."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from ..audit import audit
from ..models import User, db, now_naive
from ..security import password_strength_errors, rate_limit, require_login

bp = Blueprint("auth", __name__)

# pages reachable while a password change is pending
ALLOWED_WHEN_PENDING = ("auth.change_password", "auth.change_password_post",
                        "auth.logout", "static")


@bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("login.html", next=request.args.get("next", ""))


@bp.post("/login")
@rate_limit(limit=8, window=60.0, key_extra="login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    nxt = request.form.get("next") or ""
    user = db.session.query(User).filter_by(username=username).first()
    if not user or not user.check_password(password):
        audit("LOGIN_FAILED", detail={"username": username})
        flash("Invalid username or password.", "error")
        return render_template("login.html", next=nxt, username=username), 401
    if not user.active:
        flash("This account is deactivated. Contact your system administrator.", "error")
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
