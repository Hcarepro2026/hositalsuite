"""Authentication views."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from ..audit import audit
from ..models import User, db, now_naive
from ..security import rate_limit

bp = Blueprint("auth", __name__)


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
    if nxt and nxt.startswith("/"):
        return redirect(nxt)
    return redirect(url_for("main.dashboard"))


@bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        audit("LOGOUT", "user", current_user.id, user=current_user, org_id=current_user.org_id)
    logout_user()
    return redirect(url_for("auth.login"))
