"""TV display — public monitors showing live queue + doctor calls with Nigerian voices."""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user

from ..models import TvScreen, db
from .. import tv as tv_engine
from ..security import require_role

bp = Blueprint("tv", __name__)

SUPER = ("SUPER_ADMIN",)


def _resolve_org():
    """Org for public TV: from screen code or from logged-in user or default org."""
    from ..services import current_org
    from flask_login import current_user

    # If logged in, use user's org
    try:
        if current_user and current_user.is_authenticated:
            return current_user.org_id
    except Exception:
        pass
    # Otherwise use default org (public portal tenant)
    org = current_org()
    if org:
        return org.id
    # Fallback: first org
    from ..models import Organization

    first = db.session.query(Organization).order_by(Organization.id).first()
    return first.id if first else None


@bp.get("/tv")
def main_tv():
    """Waiting Area Main TV — shows MORE (founder req). Public, no login, per-tenant via org."""
    org_id = _resolve_org()
    if not org_id:
        abort(503)
    tv_engine.ensure_default_screens(org_id)
    screen = db.session.query(TvScreen).filter_by(org_id=org_id, code="MAIN", active=True).first()
    if not screen:
        screen = db.session.query(TvScreen).filter_by(org_id=org_id, active=True).first()
    feed = tv_engine.tv_feed(org_id, screen)
    rotation = tv_engine.voice_rotation_for_today(org_id, screen.id if screen else None)
    # Friendly attractive design: we pass everything
    return render_template("tv/main.html", feed=feed, screen=screen, rotation=rotation, is_main=True)


@bp.get("/tv/<code>")
def screen_by_code(code: str):
    """Any TV by code: /tv/DENTAL, /tv/OPD, /tv/PHARMACY — public, per-tenant."""
    code = (code or "").strip().upper()[:20]
    org_id = _resolve_org()
    if not org_id:
        abort(503)
    tv_engine.ensure_default_screens(org_id)
    screen = db.session.query(TvScreen).filter_by(org_id=org_id, code=code, active=True).first()
    if not screen:
        abort(404)
    feed = tv_engine.tv_feed(org_id, screen)
    rotation = tv_engine.voice_rotation_for_today(org_id, screen.id)
    # Main waiting area shows more, clinic TV shows filtered
    is_main = screen.screen_type == "WAITING_MAIN"
    template = "tv/main.html" if is_main else "tv/clinic.html"
    return render_template(template, feed=feed, screen=screen, rotation=rotation, is_main=is_main)


@bp.get("/api/tv/feed")
def api_feed():
    """JSON feed for TV auto-refresh — public, per-tenant."""
    org_id = _resolve_org()
    if not org_id:
        return jsonify({"error": "no org"}), 503
    code = (request.args.get("code") or "MAIN").strip().upper()[:20]
    screen = db.session.query(TvScreen).filter_by(org_id=org_id, code=code, active=True).first()
    if not screen:
        screen = db.session.query(TvScreen).filter_by(org_id=org_id, code="MAIN", active=True).first()
    feed = tv_engine.tv_feed(org_id, screen)
    rotation = tv_engine.voice_rotation_for_today(org_id, screen.id if screen else None)

    # Serialize for JSON — only safe fields, no EMR
    def ser_patient(p):
        return {"code": p.hospital_number, "name": p.full_name, "spoken": p.spoken_name} if p else None

    return jsonify(
        {
            "screen": {"code": screen.code, "name": screen.name, "type": screen.screen_type, "clinic": screen.clinic_code} if screen else None,
            "now_serving": feed["now_serving"],
            "next_up": feed["next_up"],
            "stats": feed["stats"],
            "clinic_counts": feed["clinic_counts"],
            "rotation": rotation,
            "timestamp": feed["now"].isoformat(),
        }
    )


# ------------------------------------------------------------------ admin CRUD for TV screens
@bp.get("/admin/tv")
@require_role(*SUPER)
def admin_list():
    org_id = current_user.org_id
    tv_engine.ensure_default_screens(org_id)
    screens = db.session.query(TvScreen).filter_by(org_id=org_id).order_by(TvScreen.code).all()
    from ..models import Department, ServiceClinic

    depts = db.session.query(Department).filter_by(org_id=org_id, active=True).order_by(Department.name).all()
    clinics = db.session.query(ServiceClinic).filter_by(org_id=org_id, active=True).order_by(ServiceClinic.name).all()
    return render_template("admin/tv.html", screens=screens, depts=depts, clinics=clinics)


@bp.post("/admin/tv/create")
@require_role(*SUPER)
def admin_create():
    from flask import flash, redirect, url_for

    code = (request.form.get("code") or "").strip().upper()[:20]
    name = (request.form.get("name") or "").strip()[:120]
    location = (request.form.get("location") or "").strip()[:120]
    screen_type = request.form.get("screen_type") or "WAITING_MAIN"
    clinic_code = (request.form.get("clinic_code") or "").strip().upper()[:20] or None
    dept_id = request.form.get("department_id", type=int)

    if not code or not name:
        flash("Code and name required for TV screen.", "error")
        return redirect(url_for("tv.admin_list"))

    existing = db.session.query(TvScreen).filter_by(org_id=current_user.org_id, code=code).first()
    if existing:
        flash(f"TV code {code} already exists.", "error")
        return redirect(url_for("tv.admin_list"))

    s = TvScreen(
        org_id=current_user.org_id,
        code=code,
        name=name,
        location=location,
        screen_type=screen_type,
        clinic_code=clinic_code,
        department_id=dept_id,
        show_full_name=True,
        show_queue_stats=True,
        voice_enabled=True,
        voice_rotate_daily=True,
        voice_languages="en,yo",
        active=True,
    )
    db.session.add(s)
    db.session.commit()
    flash(f"TV screen {name} ({code}) created. Open /tv/{code} on the TV.", "success")
    return redirect(url_for("tv.admin_list"))


@bp.post("/admin/tv/<int:sid>/edit")
@require_role(*SUPER)
def admin_edit(sid: int):
    from flask import flash, redirect, url_for

    s = db.session.get(TvScreen, sid)
    if not s or s.org_id != current_user.org_id:
        abort(404)
    s.name = (request.form.get("name") or s.name).strip()[:120]
    s.location = (request.form.get("location") or "").strip()[:120]
    s.screen_type = request.form.get("screen_type") or s.screen_type
    s.clinic_code = (request.form.get("clinic_code") or "").strip().upper()[:20] or None
    s.department_id = request.form.get("department_id", type=int)
    s.show_full_name = bool(request.form.get("show_full_name"))
    s.show_queue_stats = bool(request.form.get("show_queue_stats"))
    s.voice_enabled = bool(request.form.get("voice_enabled"))
    s.voice_rotate_daily = bool(request.form.get("voice_rotate_daily"))
    s.voice_languages = (request.form.get("voice_languages") or "en,yo").strip()[:20]
    s.active = bool(request.form.get("active"))
    db.session.commit()
    flash(f"TV {s.name} updated.", "success")
    return redirect(url_for("tv.admin_list"))


@bp.post("/admin/tv/<int:sid>/toggle")
@require_role(*SUPER)
def admin_toggle(sid: int):
    from flask import flash, redirect, url_for

    s = db.session.get(TvScreen, sid)
    if not s or s.org_id != current_user.org_id:
        abort(404)
    s.active = not s.active
    db.session.commit()
    flash(f"TV {s.name} {'activated' if s.active else 'suspended'}.", "success")
    return redirect(url_for("tv.admin_list"))


@bp.post("/admin/tv/<int:sid>/delete")
@require_role(*SUPER)
def admin_delete(sid: int):
    from flask import flash, redirect, url_for

    s = db.session.get(TvScreen, sid)
    if not s or s.org_id != current_user.org_id:
        abort(404)
    if s.code == "MAIN":
        flash("Cannot delete MAIN waiting area TV — suspend instead.", "error")
        return redirect(url_for("tv.admin_list"))
    db.session.delete(s)
    db.session.commit()
    flash(f"TV {s.name} deleted.", "success")
    return redirect(url_for("tv.admin_list"))
