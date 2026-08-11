"""Administrator Control Center — hospital setup, users, structure, settings, logs."""
from __future__ import annotations

import os
import shutil
from datetime import date

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   send_file, url_for)
from flask_login import current_user

from .. import services, whatsapp
from ..audit import audit, verify_chain
from ..config import Config
from ..models import (AppNotification, AuditLog, ComplaintCategory, Department,
                      DutyRoster, Organization, QrLocation, ReportFile, Section,
                      Setting, Unit, User, WhatsAppMessage, db, new_code, now_naive)
from ..security import password_strength_errors, require_role, save_upload

bp = Blueprint("admin", __name__, url_prefix="/admin")

SUPER = ("SUPER_ADMIN",)
SUPER_MD = ("SUPER_ADMIN", "MD_CEO")


# ------------------------------------------------------------------ overview
@bp.get("")
@require_role(*SUPER)
def overview():
    org = db.session.get(Organization, current_user.org_id)
    counts = {
        "users": db.session.query(User).filter_by(org_id=org.id).count(),
        "departments": db.session.query(Department).filter_by(org_id=org.id).count(),
        "roster": db.session.query(DutyRoster).filter_by(org_id=org.id).count(),
        "reports": db.session.query(ReportFile).filter_by(org_id=org.id).count(),
        "wa_failed": db.session.query(WhatsAppMessage).filter_by(org_id=org.id, status="FAILED").count(),
        "wa_queue": db.session.query(WhatsAppMessage).filter_by(org_id=org.id, status="QUEUED").count(),
    }
    backups = []
    if os.path.isdir(Config.BACKUP_DIR):
        backups = sorted((f for f in os.listdir(Config.BACKUP_DIR) if f.endswith(".db")), reverse=True)[:10]
    ok, n = verify_chain(org.id)
    return render_template("admin/overview.html", org=org, counts=counts, backups=backups,
                           chain_ok=ok, chain_rows=n)


# ------------------------------------------------------------------ hospital setup
@bp.get("/hospital")
@require_role(*SUPER)
def hospital():
    org = db.session.get(Organization, current_user.org_id)
    return render_template("admin/hospital.html", org=org)


@bp.post("/hospital")
@require_role(*SUPER)
def hospital_save():
    org = db.session.get(Organization, current_user.org_id)
    name = (request.form.get("name") or "").strip()
    code = (request.form.get("code") or "").strip().upper()
    if name:
        org.name = name
    if code and len(code) <= 12 and code.isalnum():
        org.code = code
    file = request.files.get("logo")
    if file and file.filename:
        path, err = save_upload(file, "logos")
        if not err:
            org.logo_path = os.path.join(Config.UPLOAD_DIR, path)
    audit("HOSPITAL_UPDATED", "organization", org.id, {"name": org.name, "code": org.code})
    db.session.commit()
    flash("Hospital profile updated.", "success")
    return redirect(url_for("admin.hospital"))


# ------------------------------------------------------------------ users & roles
@bp.get("/users")
@require_role(*SUPER)
def users():
    items = (db.session.query(User).filter_by(org_id=current_user.org_id)
             .order_by(User.role, User.name).all())
    return render_template("admin/users.html", items=items)


@bp.post("/users/create")
@require_role(*SUPER)
def user_create():
    username = (request.form.get("username") or "").strip().lower()
    name = (request.form.get("name") or "").strip()
    role = request.form.get("role")
    email = (request.form.get("email") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    password = request.form.get("password") or ""
    if not username or not name or role not in ("SUPER_ADMIN", "MD_CEO", "ADMIN_MANAGER", "HOD"):
        flash("Username, full name and a valid role are required.", "error")
        return redirect(url_for("admin.users"))
    if db.session.query(User).filter_by(username=username).first():
        flash("That username already exists.", "error")
        return redirect(url_for("admin.users"))
    errs = password_strength_errors(password)
    if errs:
        for e in errs:
            flash(e, "error")
        return redirect(url_for("admin.users"))
    u = User(org_id=current_user.org_id, username=username, name=name, role=role,
             email=email or None, phone=phone or None, must_change_password=True)
    u.set_password(password)
    db.session.add(u)
    db.session.flush()
    audit("USER_CREATED", "user", u.id, {"username": username, "role": role})
    db.session.commit()
    flash(f"User {name} ({username}) created.", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:uid>/toggle")
@require_role(*SUPER)
def user_toggle(uid: int):
    u = db.session.get(User, uid)
    if not u or u.org_id != current_user.org_id:
        abort(404)
    if u.id == current_user.id:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("admin.users"))
    u.active = not u.active
    audit("USER_TOGGLED", "user", u.id, {"active": u.active})
    db.session.commit()
    flash(f"User {'activated' if u.active else 'deactivated'}.", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:uid>/reset-password")
@require_role(*SUPER)
def user_reset_password(uid: int):
    u = db.session.get(User, uid)
    if not u or u.org_id != current_user.org_id:
        abort(404)
    pw = request.form.get("password") or ""
    errs = password_strength_errors(pw)
    if errs:
        for e in errs:
            flash(e, "error")
        return redirect(url_for("admin.users"))
    u.set_password(pw)
    u.must_change_password = True
    audit("PASSWORD_RESET", "user", u.id, {"target": u.username})
    db.session.commit()
    flash(f"Password reset for {u.username}. They must change it at next login.", "success")
    return redirect(url_for("admin.users"))


# ------------------------------------------------------------------ departments
@bp.get("/structure")
@require_role(*SUPER)
def structure():
    depts = (db.session.query(Department).filter_by(org_id=current_user.org_id)
             .order_by(Department.name).all())
    hods = db.session.query(User).filter_by(org_id=current_user.org_id, active=True)\
        .filter(User.role.in_(("HOD", "MD_CEO", "SUPER_ADMIN"))).order_by(User.name).all()
    return render_template("admin/structure.html", depts=depts, hods=hods)


@bp.post("/structure/department")
@require_role(*SUPER)
def department_save():
    name = (request.form.get("name") or "").strip()
    hod_id = request.form.get("hod_user_id", type=int)
    dept_id = request.form.get("department_id", type=int)
    if not name:
        flash("Department name is required.", "error")
        return redirect(url_for("admin.structure"))
    if dept_id:
        dept = db.session.get(Department, dept_id)
        if not dept or dept.org_id != current_user.org_id:
            abort(404)
        dept.name = name
        dept.hod_user_id = hod_id or None
        audit("DEPARTMENT_UPDATED", "department", dept.id, {"name": name})
    else:
        exists = db.session.query(Department).filter_by(org_id=current_user.org_id, name=name).first()
        if exists:
            flash("A department with that name already exists.", "error")
            return redirect(url_for("admin.structure"))
        dept = Department(org_id=current_user.org_id, name=name, hod_user_id=hod_id or None)
        db.session.add(dept)
        db.session.flush()
        audit("DEPARTMENT_CREATED", "department", dept.id, {"name": name})
    db.session.commit()
    flash("Department saved.", "success")
    return redirect(url_for("admin.structure"))


@bp.post("/structure/section")
@require_role(*SUPER)
def section_save():
    dept = db.session.get(Department, request.form.get("department_id", type=int) or 0)
    name = (request.form.get("name") or "").strip()
    if not dept or dept.org_id != current_user.org_id or not name:
        flash("Select a department and provide a section name.", "error")
        return redirect(url_for("admin.structure"))
    db.session.add(Section(org_id=current_user.org_id, department_id=dept.id, name=name,
                           hod_user_id=request.form.get("hod_user_id", type=int) or None))
    audit("SECTION_CREATED", "section", None, {"name": name, "dept": dept.name})
    db.session.commit()
    flash("Section added.", "success")
    return redirect(url_for("admin.structure"))


@bp.post("/structure/unit")
@require_role(*SUPER)
def unit_save():
    section = db.session.get(Section, request.form.get("section_id", type=int) or 0)
    name = (request.form.get("name") or "").strip()
    if not section or section.org_id != current_user.org_id or not name:
        flash("Select a section and provide a unit name.", "error")
        return redirect(url_for("admin.structure"))
    db.session.add(Unit(org_id=current_user.org_id, department_id=section.department_id,
                        section_id=section.id, name=name,
                        hod_user_id=request.form.get("hod_user_id", type=int) or None))
    audit("UNIT_CREATED", "unit", None, {"name": name})
    db.session.commit()
    flash("Unit added.", "success")
    return redirect(url_for("admin.structure"))


@bp.post("/structure/department/<int:did>/toggle")
@require_role(*SUPER)
def department_toggle(did: int):
    d = db.session.get(Department, did)
    if not d or d.org_id != current_user.org_id:
        abort(404)
    d.active = not d.active
    audit("DEPARTMENT_TOGGLED", "department", d.id, {"active": d.active})
    db.session.commit()
    return redirect(url_for("admin.structure"))


# ------------------------------------------------------------------ settings
@bp.get("/settings")
@require_role(*SUPER)
def settings():
    org_id = current_user.org_id
    cats = db.session.query(ComplaintCategory).filter_by(org_id=org_id).order_by(ComplaintCategory.name).all()
    locs = db.session.query(QrLocation).filter_by(org_id=org_id).order_by(QrLocation.name).all()
    return render_template("admin/settings.html", s=services.org_settings_bundle(org_id),
                           categories=cats, locations=locs, settings_mode=whatsapp.mode())


@bp.post("/settings")
@require_role(*SUPER)
def settings_save():
    org_id = current_user.org_id
    f = request.form
    try:
        sla = max(1, min(336, int(f.get("sla_hours") or 24)))
    except ValueError:
        sla = 24
    services.set_setting(org_id, "sla_hours", sla)
    services.set_setting(org_id, "reminder_day_before_time", f.get("reminder_day_before_time") or "18:00")
    services.set_setting(org_id, "reminder_duty_day_time", f.get("reminder_duty_day_time") or "07:00")
    services.set_setting(org_id, "inspection_deadline_time", f.get("inspection_deadline_time") or "18:00")
    services.set_setting(org_id, "overdue_notify_time", f.get("overdue_notify_time") or "19:00")
    gps = f.get("gps_mode")
    services.set_setting(org_id, "gps_mode", gps if gps in ("mandatory", "optional", "disabled") else "optional")
    services.set_setting(org_id, "whatsapp_md_number", (f.get("whatsapp_md_number") or "").strip())
    try:
        services.set_setting(org_id, "multiple_two_threshold", max(1, int(f.get("multiple_two_threshold") or 2)))
        services.set_setting(org_id, "recurring_window", max(3, int(f.get("recurring_window") or 10)))
        services.set_setting(org_id, "recurring_threshold", max(2, int(f.get("recurring_threshold") or 3)))
        services.set_setting(org_id, "retention_days", max(30, int(f.get("retention_days") or 2190)))
    except ValueError:
        pass
    channels = f.getlist("reminder_channels")
    services.set_setting(org_id, "reminder_channels",
                         [c for c in channels if c in ("inapp", "email", "whatsapp", "sms")] or ["inapp"])
    # booking settings
    try:
        services.set_setting(org_id, "booking_window_days", max(1, int(f.get("booking_window_days") or 30)))
        services.set_setting(org_id, "booking_capacity_per_slot", max(1, int(f.get("booking_capacity_per_slot") or 20)))
    except ValueError:
        pass
    raw_slots = [x.strip() for x in (f.get("booking_slots") or "").split(",") if x.strip()]
    import re as _re
    valid_slots = [x for x in raw_slots if _re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", x)]
    if valid_slots:
        services.set_setting(org_id, "booking_slots", valid_slots)
    services.set_setting(org_id, "booking_confirmation_sms", bool(f.get("booking_confirmation_sms")))
    audit("SETTINGS_UPDATED", "settings", org_id,
          {"sla_hours": sla, "gps_mode": services.get_setting(org_id, "gps_mode")})
    db.session.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("admin.settings"))


@bp.post("/settings/categories")
@require_role(*SUPER)
def category_add():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Category name required.", "error")
        return redirect(url_for("admin.settings"))
    exists = db.session.query(ComplaintCategory).filter_by(org_id=current_user.org_id, name=name).first()
    if exists:
        exists.active = True
    else:
        db.session.add(ComplaintCategory(org_id=current_user.org_id, name=name))
    audit("CATEGORY_ADDED", "category", None, {"name": name})
    db.session.commit()
    flash("Complaint category added.", "success")
    return redirect(url_for("admin.settings"))


@bp.post("/settings/locations")
@require_role(*SUPER)
def location_add():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Location name required.", "error")
        return redirect(url_for("admin.settings"))
    exists = db.session.query(QrLocation).filter_by(org_id=current_user.org_id, name=name).first()
    if not exists:
        db.session.add(QrLocation(org_id=current_user.org_id, name=name, code=new_code(6)))
        audit("QR_LOCATION_ADDED", "qr_location", None, {"name": name})
    db.session.commit()
    flash("QR location added.", "success")
    return redirect(url_for("admin.settings"))


# ------------------------------------------------------------------ WhatsApp / notifications
@bp.get("/notifications")
@require_role(*SUPER_MD)
def notification_logs():
    wa = (db.session.query(WhatsAppMessage).filter_by(org_id=current_user.org_id)
          .order_by(WhatsAppMessage.created_at.desc()).limit(100).all())
    app = (db.session.query(AppNotification).filter_by(org_id=current_user.org_id)
           .order_by(AppNotification.created_at.desc()).limit(200).all())
    from ..models import SmsMessage
    sms_rows = (db.session.query(SmsMessage).filter_by(org_id=current_user.org_id)
                .order_by(SmsMessage.created_at.desc()).limit(100).all())
    from flask import current_app as _ca
    return render_template("admin/notifications.html", wa=wa, app=app, sms=sms_rows,
                           mode=whatsapp.mode(), sms_mode=_ca.config.get("SMS_MODE", "sandbox"),
                           md_number=services.get_setting(current_user.org_id, "whatsapp_md_number"))


@bp.post("/notifications/whatsapp/<int:mid>/retry")
@require_role(*SUPER_MD)
def whatsapp_retry(mid: int):
    m = db.session.get(WhatsAppMessage, mid)
    if not m or m.org_id != current_user.org_id:
        abort(404)
    m.status = "QUEUED"
    m.attempts = 0
    db.session.commit()
    whatsapp.send_message(m)
    audit("WHATSAPP_RETRY", "whatsapp", m.id, {"status": m.status})
    db.session.commit()
    flash(f"WhatsApp message retried — status: {m.status}" +
          (f" ({m.last_error})" if m.last_error else ""), "success" if m.status in ("SENT", "DELIVERED") else "error")
    return redirect(url_for("admin.notification_logs"))


@bp.post("/notifications/whatsapp/test")
@require_role(*SUPER)
def whatsapp_test():
    number = (request.form.get("number") or "").strip()
    if not number:
        flash("Enter a destination number (E.164, e.g. 2348012345678).", "error")
        return redirect(url_for("admin.notification_logs"))
    m = whatsapp.queue_message(current_user.org_id, number,
                               "Test message from Hospital Admin Manager Suite.", kind="alert")
    whatsapp.send_message(m)
    audit("WHATSAPP_TEST", "whatsapp", m.id, {"to": number, "status": m.status})
    db.session.commit()
    flash(f"Test message {m.status.lower()}." + (f" Error: {m.last_error}" if m.last_error else ""),
          "success" if m.status in ("SENT", "DELIVERED") else "error")
    return redirect(url_for("admin.notification_logs"))


# ------------------------------------------------------------------ QR poster pack (§43A)
POSTER_SERVICES = {
    "complaint": {
        "title": "Make a Complaint",
        "subtitle": "Your voice matters — we listen and act",
        "steps": ["Point your phone camera at the QR code",
                  "Choose the department and describe the problem (typing or speaking)",
                  "Get your reference number instantly — management is notified immediately"],
        "path": "/complaint",
    },
    "booking": {
        "title": "Book a Hospital Visit",
        "subtitle": "Skip the uncertainty — reserve your slot in 1 minute",
        "steps": ["Scan the QR code with your phone camera",
                  "Pick the service, date and time that suits you",
                  "Save your booking reference — see it at reception on arrival"],
        "path": "/book",
    },
    "queue": {
        "title": "Join the Queue",
        "subtitle": "Get your number and track your position",
        "steps": ["Scan the QR code with your phone camera",
                  "Enter your name to receive a queue number",
                  "Watch your position live — you'll get an SMS when it's your turn"],
        "path": "/queue/join",
    },
    "feedback": {
        "title": "Rate Your Experience",
        "subtitle": "1 minute of feedback makes care better for everyone",
        "steps": ["Scan the QR code after your visit",
                  "Tap a star rating — add a comment by typing or speaking",
                  "Low ratings reach management immediately; high ratings help us improve"],
        "path": "/feedback",
    },
}


@bp.get("/posters")
@require_role(*SUPER)
def posters():
    locs = db.session.query(QrLocation).filter_by(org_id=current_user.org_id).order_by(QrLocation.name).all()
    return render_template("admin/posters.html", locs=locs, services=POSTER_SERVICES,
                           base=Config.PUBLIC_BASE_URL)


@bp.get("/posters/download")
@require_role(*SUPER)
def posters_download():
    org = db.session.get(Organization, current_user.org_id)
    from ..config import Config as _Cfg
    wanted = [s for s in (request.args.get("services") or "").split(",") if s in POSTER_SERVICES] \
        or list(POSTER_SERVICES.keys())
    locs = db.session.query(QrLocation).filter_by(org_id=org.id).order_by(QrLocation.name).all()
    posters = []
    base = _Cfg.PUBLIC_BASE_URL.rstrip("/")
    for svc_key in wanted:
        svc = POSTER_SERVICES[svc_key]
        if svc_key in ("complaint", "booking") and locs:
            for loc in locs:
                posters.append({
                    "title": svc["title"],
                    "subtitle": f"{svc['subtitle']}  ·  📍 {loc.name}",
                    "url": f"{base}{svc['path']}?loc={loc.code}",
                    "steps": svc["steps"],
                })
        else:
            posters.append({"title": svc["title"], "subtitle": svc["subtitle"],
                            "url": f"{base}{svc['path']}", "steps": svc["steps"]})
    from .. import pdfgen
    path = os.path.join(Config.REPORT_DIR, f"qr-posters-{new_code(4)}.pdf")
    pdfgen.build_poster_pdf(org, posters, path)
    rf = ReportFile(org_id=org.id, kind="posters", title=f"QR Poster Pack ({len(posters)} posters)",
                    path=path, verify_code=new_code(10), created_by_id=current_user.id)
    db.session.add(rf)
    audit("POSTERS_GENERATED", "report", None, {"count": len(posters), "services": wanted})
    db.session.commit()
    return send_file(path, as_attachment=True, download_name="QR-Poster-Pack.pdf",
                     mimetype="application/pdf")


# ------------------------------------------------------------------ audit log
@bp.get("/audit")
@require_role(*SUPER_MD)
def audit_log():
    q = db.session.query(AuditLog).filter_by(org_id=current_user.org_id)
    action = request.args.get("action")
    if action:
        q = q.filter(AuditLog.action.ilike(f"%{action}%"))
    items = q.order_by(AuditLog.id.desc()).limit(300).all()
    ok, n = verify_chain(current_user.org_id)
    return render_template("admin/audit.html", items=items, chain_ok=ok, chain_rows=n,
                           action=action or "")


# ------------------------------------------------------------------ backups
@bp.post("/backup")
@require_role(*SUPER)
def backup_now():
    uri = db.engine.url
    if str(uri).startswith("sqlite"):
        from ..scheduler import job_nightly_backup
        from flask import current_app
        job_nightly_backup(current_app)
        audit("BACKUP_MANUAL", "system", None, {})
        db.session.commit()
        flash("Database backup created in the backups folder.", "success")
    else:
        flash("For PostgreSQL deployments, run pg_dump via your ops pipeline.", "info")
    return redirect(url_for("admin.overview"))


@bp.get("/backup/download/<name>")
@require_role(*SUPER)
def backup_download(name: str):
    safe = os.path.basename(name)
    full = os.path.join(Config.BACKUP_DIR, safe)
    if not safe.endswith(".db") or not os.path.isfile(full):
        abort(404)
    return send_file(full, as_attachment=True)


# ------------------------------------------------------------------ system health
@bp.get("/health")
@require_role(*SUPER)
def health():
    info = {
        "database": "connected" if db.session.execute(db.text("SELECT 1")).scalar() == 1 else "error",
        "whatsapp_mode": whatsapp.mode(),
        "backup_dir": Config.BACKUP_DIR,
        "disk": None,
    }
    try:
        usage = shutil.disk_usage(os.path.dirname(Config.BACKUP_DIR))
        info["disk"] = f"{usage.free / 1e9:.1f} GB free of {usage.total / 1e9:.1f} GB"
    except OSError:
        pass
    return render_template("admin/health.html", info=info)
