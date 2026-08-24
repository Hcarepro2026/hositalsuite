"""Staff clock-in / clock-out. Phone first, plain English."""
from __future__ import annotations

from datetime import datetime

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required

from .. import attendance as engine
from ..audit import audit
from ..models import Branch, User, db, now_naive
from ..navigation import permissions_for, require_permission
from ..security import save_upload

bp = Blueprint("attendance", __name__)


def _coords(src=None):
    src = src if src is not None else request.form
    lat = engine.parse_coord(src.get("lat"), kind="lat")
    lng = engine.parse_coord(src.get("lng"), kind="lng")
    try:
        acc = int(float(src.get("accuracy") or 0)) or None
    except (TypeError, ValueError):
        acc = None
    return lat, lng, acc


def _mocked(src=None) -> bool:
    src = src if src is not None else request.form
    return engine.as_bool(src.get("mocked"))


def _client_at(src=None):
    src = src if src is not None else request.form
    return engine.parse_when(src.get("client_at") or src.get("punched_at"))


@bp.get("/attendance")
@login_required
def desk():
    site = engine.site_for(current_user)
    fence = engine.fence_for(current_user.org_id, site)
    open_row = engine.open_row(current_user.org_id, current_user.id)
    can = permissions_for(current_user)
    today = engine.today_board(current_user.org_id) if can.get("attendance_admin") else []
    helpers = engine.helpable_staff(current_user)
    open_ids = set()
    if helpers:
        open_ids = {r.user_id for r in engine.today_board(current_user.org_id)
                    if r.is_open}
    return render_template(
        "attendance.html",
        fence=fence, site=site, open_row=open_row,
        can_admin=can.get("attendance_admin"),
        today=today, now=now_naive(),
        can_help=bool(helpers),
        help_staff=[u for u in helpers if u.id != current_user.id and u.id not in open_ids],
        help_reasons=engine.HELP_REASONS,
    )


@bp.post("/attendance/in")
@login_required
def punch_in():
    lat, lng, acc = _coords()
    device = (request.headers.get("User-Agent") or "")[:200]
    row, verdict = engine.clock_in(
        current_user, lat=lat, lng=lng, accuracy_m=acc, device_info=device,
        mocked=_mocked(), client_at=_client_at())
    if not verdict.get("ok"):
        flash(verdict["reason"], "error")
        return redirect(url_for("attendance.desk"))
    audit("ATTENDANCE_IN", "staff_attendance", row.id if row else None,
          {"inside": verdict.get("inside"), "distance_m": verdict.get("distance_m"),
           "mode": (row.mode if row else None),
           "flagged": bool(row.flagged) if row else False})
    db.session.commit()
    flash(verdict["reason"] if verdict.get("already") else "You are signed in. Welcome.",
          "info" if verdict.get("already") else "success")
    return redirect(url_for("attendance.desk"))


@bp.post("/attendance/out")
@login_required
def punch_out():
    lat, lng, acc = _coords()
    row, verdict = engine.clock_out(
        current_user, lat=lat, lng=lng, accuracy_m=acc,
        mocked=_mocked(), client_at=_client_at())
    if not verdict.get("ok") or row is None:
        flash(verdict.get("reason") or "You are not signed in.", "error")
        return redirect(url_for("attendance.desk"))
    audit("ATTENDANCE_OUT", "staff_attendance", row.id, {})
    db.session.commit()
    flash("You are signed out. Thank you.", "success")
    return redirect(url_for("attendance.desk"))


@bp.post("/attendance/sync")
@login_required
def sync():
    """Replay punches that sat on the phone while there was no internet."""
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") or []
    results = []
    for item in items[:20]:
        kind = (item.get("kind") or "").lower()
        body = item.get("payload") or item
        lat = engine.parse_coord(body.get("lat"), kind="lat")
        lng = engine.parse_coord(body.get("lng"), kind="lng")
        try:
            acc = int(float(body.get("accuracy") or 0)) or None
        except (TypeError, ValueError):
            acc = None
        mocked = engine.as_bool(body.get("mocked"))
        client_at = engine.parse_when(body.get("client_at") or item.get("at"))
        device = (request.headers.get("User-Agent") or "")[:200]
        if kind == "out":
            row, verdict = engine.clock_out(
                current_user, lat=lat, lng=lng, accuracy_m=acc,
                mocked=mocked, client_at=client_at)
        else:
            row, verdict = engine.clock_in(
                current_user, lat=lat, lng=lng, accuracy_m=acc,
                device_info=device, mocked=mocked, client_at=client_at)
        results.append({"ok": bool(verdict.get("ok")),
                        "reason": verdict.get("reason"),
                        "already": verdict.get("already")})
        if verdict.get("ok") and row is not None:
            audit("ATTENDANCE_SYNC", "staff_attendance", row.id,
                  {"kind": kind or "in", "offline": True})
    db.session.commit()
    return jsonify({"ok": True, "results": results})


@bp.get("/attendance/today")
@login_required
@require_permission("attendance_admin")
def today():
    day = now_naive().date()
    raw = (request.args.get("date") or "").strip()
    if raw:
        try:
            day = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            day = now_naive().date()
    branch_id = request.args.get("branch_id", type=int)
    if branch_id:
        b = db.session.get(Branch, branch_id)
        if not b or b.org_id != current_user.org_id:
            abort(404)
    rows = engine.today_board(current_user.org_id, day=day, branch_id=branch_id)
    sites = (db.session.query(Branch)
             .filter_by(org_id=current_user.org_id, active=True)
             .order_by(Branch.is_main.desc(), Branch.name).all())
    open_ids = {r.user_id for r in rows if r.is_open}
    staff = engine.helpable_staff(current_user)
    in_now = sum(1 for r in rows if r.is_open)
    return render_template(
        "attendance_today.html", rows=rows, day=day, sites=sites,
        branch_id=branch_id, in_now=in_now, total=len(rows),
        staff=staff, open_ids=open_ids,
        help_reasons=engine.HELP_REASONS,
        help_labels=engine.HELP_LABELS,
    )


@bp.post("/attendance/override")
@login_required
def override():
    """HOD / supervisor / admin signs someone in. Photo + fixed reason required."""
    uid = request.form.get("user_id", type=int)
    code = (request.form.get("help_reason") or "").strip()
    extra = (request.form.get("reason") or "").strip()[:120]
    target = db.session.get(User, uid) if uid else None
    next_url = request.form.get("next") or url_for("attendance.desk")
    if next_url.startswith("/attendance/today"):
        dest = url_for("attendance.today")
    else:
        dest = url_for("attendance.desk")
    if not target or target.org_id != current_user.org_id or not target.active:
        flash("Pick a member of staff.", "error")
        return redirect(dest)
    if not engine.can_help(current_user, target):
        flash("You may only help staff in your own department.", "error")
        return redirect(dest)
    if code not in engine.HELP_CODES:
        flash("Pick a reason from the list. Free text alone is not enough.", "error")
        return redirect(dest)
    photo = request.files.get("evidence")
    if not photo or not photo.filename:
        flash("Take a photo of the person at the gate. No photo, no help.", "error")
        return redirect(dest)
    path, err = save_upload(photo, "attendance", org_id=current_user.org_id)
    if err:
        flash(err, "error")
        return redirect(dest)
    label = engine.HELP_LABELS[code]
    reason = f"{label}" + (f" — {extra}" if extra else "")
    row, verdict = engine.clock_in(
        target, override_reason=reason, override_by=current_user,
        help_reason=code, evidence_path=path)
    if not verdict.get("ok"):
        flash(verdict["reason"], "error")
        return redirect(dest)
    audit("ATTENDANCE_OVERRIDE", "staff_attendance", row.id if row else None,
          {"for": target.username, "reason": reason, "help_reason": code,
           "by": current_user.username})
    db.session.commit()
    flash(f"{target.name} is signed in. Photo and reason kept on the record.", "success")
    return redirect(dest)


@bp.get("/attendance/week")
@login_required
@require_permission("attendance_admin")
def week():
    raw = (request.args.get("date") or "").strip()
    day = now_naive().date()
    if raw:
        try:
            day = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            day = now_naive().date()
    start, end = engine.week_bounds(day)
    report = engine.weekly_report(current_user.org_id, start, end)
    return render_template("attendance_week.html", report=report, day=day)
