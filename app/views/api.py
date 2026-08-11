"""JSON APIs: WhatsApp webhook, USSD complaint intake, health, offline sync."""
from __future__ import annotations

import hashlib
import hmac
import json

from flask import Blueprint, current_app, jsonify, request

from .. import services, whatsapp
from ..audit import audit
from ..models import Complaint, ComplaintStatusHistory, Department, Organization, db, now_naive
from ..security import csrf_exempt, rate_limit
from .. import scoring

bp = Blueprint("api", __name__, url_prefix="/api/v1")


@bp.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify(status="ok" if db_ok else "degraded", database=db_ok,
                   whatsapp_mode=whatsapp.mode())


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
    db.session.add(ComplaintStatusHistory(complaint_id=c.id, from_status=None, to_status="NEW",
                                          note="Submitted via USSD"))
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
    return jsonify(ref=c.ref, status="NEW",
                   message=f"Your complaint has been received. Reference: {c.ref}")
