"""JSON APIs: WhatsApp webhook, USSD complaint intake, health, offline sync."""
from __future__ import annotations

import hashlib
import hmac

from flask import Blueprint, current_app, jsonify, request

from .. import services, whatsapp
from ..audit import audit
from ..models import Complaint, ComplaintStatusHistory, Department, Organization, db, now_naive
from ..security import csrf_exempt, rate_limit
from .. import scoring

bp = Blueprint("api", __name__, url_prefix="/api/v1")


@bp.get("/health")
def health():
    """Liveness + readiness. Used by Render's health check and by the founder.

    Reports the things that actually break in production: the database, whether
    the background scheduler is still alive (it runs reminders, SLA escalation
    and backups — silent death means missed escalations), and when the last
    backup ran.
    """
    try:
        db.session.execute(db.text("SELECT 1"))
        db_ok = True
    except Exception:                                 # noqa: BLE001
        db.session.rollback()
        db_ok = False

    scheduler_ok = None
    try:
        from ..scheduler import ensure_running, is_alive
        scheduler_ok = is_alive()
        if scheduler_ok is False:
            # Self-heal: a dead scheduler means SLA escalations and duty
            # reminders have silently stopped. Restart it on the spot.
            ensure_running(current_app._get_current_object())
            scheduler_ok = is_alive()
    except Exception:                                 # noqa: BLE001
        scheduler_ok = None

    last_backup = None
    try:
        from ..backup import list_backups
        rows = list_backups(limit=1)
        if rows:
            last_backup = rows[0].created_at.isoformat()
    except Exception:                                 # noqa: BLE001
        db.session.rollback()

    healthy = db_ok and (scheduler_ok is not False)
    payload = {
        "status": "ok" if healthy else "degraded",
        "database": db_ok,
        "scheduler": scheduler_ok,
        "last_backup": last_backup,
        "storage": current_app.config.get("STORAGE_BACKEND", "db"),
        "whatsapp_mode": whatsapp.mode(),
    }
    # ALWAYS HTTP 200 — this is a LIVENESS probe, and it is the URL the host
    # uses to decide whether a deploy succeeded. Returning 503 while the
    # database is down makes the platform kill a perfectly good container,
    # turning a recoverable database wobble into a total site outage (exactly
    # what happened on 2026-08-15). Read the "status" field to see health;
    # use /api/v1/ready when you specifically need a readiness check.
    return jsonify(payload), 200


@bp.get("/ready")
def ready():
    """Strict readiness probe: 503 unless the database is actually usable.

    Deliberately NOT the platform health check — use this for monitoring
    dashboards and alerting, where you want to be paged for a degraded state.
    """
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:                                 # noqa: BLE001
        db.session.rollback()
        return jsonify(ready=False, reason="database unreachable"), 503

    # SCHEMA DRIFT CHECK.
    # A reachable database is not the same as a USABLE one. /hims/ once
    # returned 500 for every visitor because a migration had been edited after
    # it was applied, so the live table was missing a column the app read.
    # Connectivity looked perfect throughout. This compares what the app
    # expects against what the database actually has, so the next drift is
    # visible from outside instead of being discovered by a patient.
    try:
        from sqlalchemy import inspect as _inspect
        insp = _inspect(db.engine)
        present = set(insp.get_table_names())
        missing = []
        for tname, table in db.metadata.tables.items():
            if tname not in present:
                missing.append(tname)
                continue
            cols = {c["name"] for c in insp.get_columns(tname)}
            missing.extend(f"{tname}.{c.name}" for c in table.columns
                           if c.name not in cols)
        if missing:
            return jsonify(ready=False, reason="schema drift",
                           missing=sorted(missing)[:20]), 503
    except Exception as exc:                          # noqa: BLE001
        db.session.rollback()
        return jsonify(ready=False, reason=f"schema check failed: {exc}"[:200]), 503

    return jsonify(ready=True), 200


# ================================================================ live alerts (§19/§37)
# Admin/quality alerts.
ALERT_TEMPLATES = {
    "complaint_escalated": "emergency",
    "critical_score": "emergency",
    "inspection_overdue": "urgent",
    "ca_overdue": "urgent",
    "complaint_sla_warning": "standard",
}


def _speakable() -> dict:
    """Admin alerts PLUS patient-flow announcements.

    Previously only the five admin events above could ever be spoken, so a
    nurse waiting on patient announcements heard nothing at all — the engine
    worked, but nothing was ever routed into it.
    """
    from ..announce import PATIENT_ALERTS
    out = dict(ALERT_TEMPLATES)
    for key, (urgency, _subject) in PATIENT_ALERTS.items():
        out[key] = urgency
    return out


@bp.get("/alerts/prefs")
def alerts_prefs():
    from flask_login import current_user
    if not current_user.is_authenticated:
        return jsonify(error="unauthenticated"), 401
    from ..models import UserPref
    return jsonify(UserPref.bundle(current_user.id))


@bp.get("/alerts/poll")
def alerts_poll():
    """New alert-level notifications since ?after=<id> — drives toasts, browser
    notifications and voice announcements (polling fallback per §22/§40)."""
    from flask_login import current_user
    if not current_user.is_authenticated:
        return jsonify(error="unauthenticated"), 401
    after = request.args.get("after", type=int) or 0
    from ..models import AppNotification, UserPref
    speakable = _speakable()
    rows = (db.session.query(AppNotification)
            .filter(AppNotification.user_id == current_user.id,
                    AppNotification.channel == "inapp",
                    AppNotification.id > after,
                    AppNotification.template_key.in_(tuple(speakable)))
            .order_by(AppNotification.id).limit(10).all())
    prefs = UserPref.bundle(current_user.id)
    return jsonify({
        "prefs": prefs,
        "alerts": [{"id": r.id, "subject": r.subject, "body": r.body,
                    # `speech` is what gets SPOKEN. Patient announcements are
                    # already written to be heard; admin alerts fall back to
                    # their on-screen text.
                    "speech": r.body,
                    "urgency": speakable.get(r.template_key, "standard"),
                    "at": r.created_at.strftime("%H:%M")} for r in rows],
        "last_id": rows[-1].id if rows else after,
    })


@bp.get("/alerts/station")
@rate_limit(limit=120, window=60.0)
def alerts_station():
    """Shared station screen feed (dispensary tablet, nurses' desk).

    No login: a ward tablet is not signed in as any individual. It is scoped to
    one department and only ever returns announcements — never patient names
    from other areas, never clinical detail.
    """
    from ..announce import PATIENT_ALERTS
    from ..models import AppNotification
    from ..services import current_org
    org = current_org()
    if not org:
        return jsonify(alerts=[], last_id=0)
    after = request.args.get("after", type=int) or 0
    dept_id = request.args.get("dept", type=int)
    q = (db.session.query(AppNotification)
         .filter(AppNotification.org_id == org.id,
                 AppNotification.channel == "station",
                 AppNotification.id > after,
                 AppNotification.template_key.in_(tuple(PATIENT_ALERTS))))
    if dept_id:
        q = q.filter(AppNotification.entity_id == dept_id)
    rows = q.order_by(AppNotification.id).limit(10).all()
    return jsonify({
        "alerts": [{"id": r.id, "subject": r.subject, "body": r.body,
                    "speech": r.body,
                    "urgency": PATIENT_ALERTS.get(r.template_key, ("standard",))[0],
                    "at": r.created_at.strftime("%H:%M")} for r in rows],
        "last_id": rows[-1].id if rows else after,
    })


# ================================================================ WhatsApp webhook
@csrf_exempt("api.whatsapp_webhook")
@bp.get("/whatsapp/webhook")
def whatsapp_verify():
    """Meta subscription verification handshake."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token", "")
    challenge = request.args.get("hub.challenge", "")
    if mode == "subscribe" and token == current_app.config.get("WHATSAPP_VERIFY_TOKEN", "") \
            and current_app.config.get("WHATSAPP_VERIFY_TOKEN"):
        return challenge, 200
    return "forbidden", 403


@csrf_exempt("api.whatsapp_webhook_post")
@bp.post("/whatsapp/webhook")
def whatsapp_webhook():
    """Receive delivery statuses + inbound messages from the Cloud API."""
    secret = current_app.config.get("WHATSAPP_APP_SECRET", "")
    if secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), request.get_data(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return "invalid signature", 403
    data = request.get_json(silent=True) or {}
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for status in value.get("statuses", []):
                whatsapp.apply_webhook_status(status.get("id", ""), status.get("status", ""))
    return "ok", 200


# ================================================================ USSD / gateway intake
@csrf_exempt("api.ussd_queue")
@bp.post("/ussd/queue")
@rate_limit(limit=30, window=60.0)
def ussd_queue():
    """USSD intake: join the queue (spec §6 USSD/SMS fallback)."""
    import secrets as _secrets
    cfg_secret = current_app.config.get("USSD_SHARED_SECRET", "")
    data = request.get_json(silent=True) or {}
    if not cfg_secret or data.get("secret") != cfg_secret:
        return jsonify(error="unauthorized"), 401
    org = db.session.query(Organization).filter_by(code=data.get("hospital_code", "")).first()
    if not org:
        org = db.session.query(Organization).order_by(Organization.id).first()
    dept = (db.session.query(Department)
            .filter_by(org_id=org.id, active=True)
            .filter(Department.name.ilike(f"%{data.get('department', '')}%")).first())
    name = (data.get("name") or "").strip()
    if not dept or len(name) < 2:
        return jsonify(error="missing department or name"), 422
    from ..models import QueueTicket
    from .queue import next_ticket, _dept_letter
    now = now_naive()
    n = next_ticket(org.id, dept, now.date())
    t = QueueTicket(org_id=org.id, code=f"{_dept_letter(dept)}-{n:03d}",
                    access_key=_secrets.token_urlsafe(12), department_id=dept.id,
                    queue_date=now.date(), patient_name=name[:120],
                    phone=(data.get("phone") or "").strip() or None,
                    status="WAITING", source="ussd")
    db.session.add(t)
    db.session.flush()
    audit("QUEUE_JOINED", "queue_ticket", t.id, {"code": t.code, "source": "ussd"}, org_id=org.id)
    db.session.commit()
    return jsonify(ticket=t.code,
                   message=f"You are in the {dept.name} queue. Your number is {t.code}.")


@csrf_exempt("api.ussd_booking")
@bp.post("/ussd/booking")
@rate_limit(limit=30, window=60.0)
def ussd_booking():
    """USSD aggregator intake for bookings (spec §5 USSD-ready)."""
    from datetime import date as _date, timedelta
    cfg_secret = current_app.config.get("USSD_SHARED_SECRET", "")
    data = request.get_json(silent=True) or {}
    if not cfg_secret or data.get("secret") != cfg_secret:
        return jsonify(error="unauthorized"), 401
    org = db.session.query(Organization).filter_by(code=data.get("hospital_code", "")).first()
    if not org:
        org = db.session.query(Organization).order_by(Organization.id).first()
    dept = (db.session.query(Department)
            .filter_by(org_id=org.id, active=True)
            .filter(Department.name.ilike(f"%{data.get('department', '')}%")).first())
    phone = (data.get("phone") or "").strip()
    name = (data.get("name") or "").strip()
    raw_date = (data.get("date") or "").strip()
    slot = (data.get("time") or "").strip()
    if not dept or not name or len(phone) < 7:
        return jsonify(error="missing department, name or phone"), 422
    try:
        day = _date.fromisoformat(raw_date)
    except ValueError:
        return jsonify(error="invalid date"), 422
    now = now_naive()
    window = int(services.get_setting(org.id, "booking_window_days") or 30)
    slots = services.get_setting(org.id, "booking_slots") or []
    if day < now.date() or day > now.date() + timedelta(days=window) or slot not in slots:
        return jsonify(error="date/time not available"), 422
    if services.slot_is_full(org.id, dept.id, day, slot):
        return jsonify(error="slot full"), 422
    from ..models import Appointment
    apt = Appointment(org_id=org.id, ref=services.next_appointment_ref(org, now),
                      department_id=dept.id, appointment_date=day, appointment_time=slot,
                      patient_name=name[:120], phone=phone, status="BOOKED", source="ussd")
    db.session.add(apt)
    db.session.flush()
    from .. import referrals as refeng
    refeng.stamp_booking(org.id, apt, code=data.get("referral_code") or "")
    audit("BOOKING_CREATED", "appointment", apt.id, {"ref": apt.ref, "source": "ussd"}, org_id=org.id)
    db.session.commit()
    return jsonify(ref=apt.ref, status="BOOKED",
                   message=f"Booking confirmed: {day} at {slot}. Reference: {apt.ref}")


@csrf_exempt("api.ussd_complaint")
@bp.post("/ussd/complaint")
@rate_limit(limit=30, window=60.0)
def ussd_complaint():
    """Intake for a Nigerian USSD aggregator.

    Expected JSON: {secret, hospital_code, department, category, description, phone}
    The aggregator collects the fields over USSD sessions and POSTs here.
    """
    cfg_secret = current_app.config.get("USSD_SHARED_SECRET", "")
    data = request.get_json(silent=True) or {}
    if not cfg_secret or data.get("secret") != cfg_secret:
        return jsonify(error="unauthorized"), 401
    org = db.session.query(Organization).filter_by(code=data.get("hospital_code", "")).first()
    if not org:
        org = db.session.query(Organization).order_by(Organization.id).first()
    dept = (db.session.query(Department)
            .filter_by(org_id=org.id, active=True)
            .filter(Department.name.ilike(f"%{data.get('department', '')}%")).first())
    phone = (data.get("phone") or "").strip()
    description = (data.get("description") or "").strip()
    if not dept or len(description) < 5 or len(phone) < 7:
        return jsonify(error="missing department, description or phone"), 422

    from .complaints import PHONE_RE
    if not PHONE_RE.match(phone.replace(" ", "")):
        return jsonify(error="invalid phone"), 422

    now = now_naive()
    sla_hours = int(services.get_setting(org.id, "sla_hours") or 24)
    c = Complaint(org_id=org.id, ref=services.next_complaint_ref(org, now),
                  department_id=dept.id, category=(data.get("category") or "General").strip(),
                  description=description, phone=phone, source="ussd", status="NEW",
                  sla_hours=sla_hours, sla_deadline_at=scoring.sla_deadline(now, sla_hours))
    db.session.add(c)
    db.session.flush()
    from .. import notifications as _notes
    ack = _notes.patient_update_text("received", org.name, c.ref)
    db.session.add(ComplaintStatusHistory(complaint_id=c.id, from_status=None, to_status="NEW",
                                          note="Submitted via USSD", patient_message=ack))
    audit("COMPLAINT_SUBMITTED", "complaint", c.id, {"ref": c.ref, "source": "ussd"}, org_id=org.id)

    from .. import notifications
    ctx = {"ref": c.ref, "dept": dept.name, "category": c.category, "sla": sla_hours,
           "hospital": org.name}
    duty = services.on_duty(org.id, now.date())
    if duty:
        notifications.notify(org.id, duty, "complaint_new_admin", ctx, channels=["inapp"],
                             entity_type="complaint", entity_id=c.id)
    hod = services.route_hod(dept)
    if hod:
        notifications.notify(org.id, hod, "complaint_new_hod", ctx, channels=["inapp"],
                             entity_type="complaint", entity_id=c.id)
    db.session.commit()
    notifications.notify_complaint_patient(org, c, "received")
    return jsonify(ref=c.ref, status="NEW",
                   message=f"Your complaint has been received. Reference: {c.ref}")
