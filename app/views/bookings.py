"""Patient booking (public, no account) + staff booking management — spec §5."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user

from .. import notifications, services, sms as sms_engine
from ..audit import audit
from ..models import (Appointment, Department, Organization, QrLocation, db,
                      now_naive)
from ..security import rate_limit, require_login

bp = Blueprint("bookings", __name__)

PHONE_RE = re.compile(r"^\+?\d{7,15}$")


def _default_org() -> Organization | None:
    return db.session.query(Organization).order_by(Organization.id).first()


# ================================================================ PUBLIC
@bp.get("/book")
@rate_limit(limit=30, window=60.0)
def portal():
    org = _default_org()
    if not org:
        return render_template("error.html", code=503, message="System not configured yet."), 503
    loc_code = (request.args.get("loc") or "").strip().upper()
    qr_loc = db.session.query(QrLocation).filter_by(code=loc_code).first() if loc_code else None
    depts = (db.session.query(Department)
             .filter_by(org_id=org.id, active=True).order_by(Department.name).all())
    today = now_naive().date()
    window = int(services.get_setting(org.id, "booking_window_days") or 30)
    return render_template("booking_portal.html", org=org, depts=depts, qr_loc=qr_loc,
                           min_date=today.isoformat(),
                           max_date=(today + timedelta(days=window)).isoformat(),
                           slots=services.get_setting(org.id, "booking_slots") or [],
                           idem=_new_idem())


def _new_idem() -> str:
    import secrets
    return secrets.token_urlsafe(16)


@bp.post("/book/submit")
@rate_limit(limit=10, window=120.0)
def portal_submit():
    org = _default_org()
    if not org:
        abort(503)
    now = now_naive()

    idem = (request.form.get("idem") or "").strip()[:40]
    # idempotency: a re-submitted form (double-tap / retry) returns the original booking
    if idem:
        dup = db.session.query(Appointment).filter_by(org_id=org.id, idempotency_key=idem).first()
        if dup:
            return redirect(url_for("bookings.portal_thanks", ref=dup.ref))

    dept_id = request.form.get("department_id", type=int)
    raw_date = (request.form.get("appointment_date") or "").strip()
    slot = (request.form.get("appointment_time") or "").strip()
    name = (request.form.get("patient_name") or "").strip()
    phone = (request.form.get("phone") or "").strip().replace(" ", "").replace("-", "")

    dept = db.session.get(Department, dept_id) if dept_id else None
    errors = []
    day = None
    if not dept or dept.org_id != org.id:
        errors.append("Please select a service/department.")
    try:
        day = date.fromisoformat(raw_date)
    except ValueError:
        day = None
        errors.append("Please choose a valid date.")
    if day:
        window = int(services.get_setting(org.id, "booking_window_days") or 30)
        if day < now.date():
            errors.append("The date cannot be in the past.")
        elif day > now.date() + timedelta(days=window):
            errors.append(f"Bookings are open up to {window} days ahead.")
    slots = services.get_setting(org.id, "booking_slots") or []
    if slot not in slots:
        errors.append("Please choose one of the available time slots.")
    elif day == now.date() and datetime.strptime(slot, "%H:%M").time() <= now.time():
        errors.append("That time slot has already passed today — please pick a later slot.")
    if len(name) < 2:
        errors.append("Please enter the patient's full name.")
    if not PHONE_RE.match(phone):
        errors.append("Please enter a valid phone number (e.g. 08012345678).")
    if day and dept and slot in slots and services.slot_is_full(org.id, dept.id, day, slot):
        errors.append("That time slot is full — please choose another time.")

    if errors:
        depts = db.session.query(Department).filter_by(org_id=org.id, active=True).all()
        for e in errors:
            flash(e, "error")
        # preserve the QR location tag on re-render
        loc_code_err = (request.form.get("loc") or "").strip().upper()
        qr_loc_err = db.session.query(QrLocation).filter_by(code=loc_code_err).first() if loc_code_err else None
        return render_template("booking_portal.html", org=org, depts=depts, qr_loc=qr_loc_err,
                               min_date=now.date().isoformat(),
                               max_date=(now.date() + timedelta(days=int(
                                   services.get_setting(org.id, "booking_window_days") or 30))).isoformat(),
                               slots=services.get_setting(org.id, "booking_slots") or [],
                               idem=_new_idem(), form=request.form), 422

    loc_code = (request.form.get("loc") or "").strip().upper()
    qr_loc = db.session.query(QrLocation).filter_by(code=loc_code).first() if loc_code else None

    apt = Appointment(
        org_id=org.id,
        ref=services.next_appointment_ref(org, now),
        idempotency_key=idem or None,
        department_id=dept.id,
        appointment_date=day,
        appointment_time=slot,
        patient_name=name[:120],
        phone=phone,
        status="BOOKED",
        source="qr" if qr_loc else "link",
        qr_location_id=qr_loc.id if qr_loc else None,
    )
    db.session.add(apt)
    db.session.flush()
    audit("BOOKING_CREATED", "appointment", apt.id,
          {"ref": apt.ref, "dept": dept.name, "date": str(day), "slot": slot}, org_id=org.id)

    # confirmation through available channels (§5) — patient SMS first
    confirm_body = (f"{org.name}: Your visit is booked for {day.strftime('%a %d %b')} at {slot} "
                    f"({dept.name}). Ref: {apt.ref}. Please arrive 15 minutes early.")
    if services.get_setting(org.id, "booking_confirmation_sms", True):
        sms_engine.queue_sms(org.id, phone, confirm_body, kind="confirmation",
                             entity_type="appointment", entity_id=apt.id)
        from ..tasks import dispatch_delivery
        dispatch_delivery()   # §39 — async delivery

    # inform the Admin Manager on duty (in-app)
    duty = services.on_duty(org.id, now.date())
    if duty:
        notifications.notify(org.id, duty, "booking_new",
                             {"ref": apt.ref, "dept": dept.name, "hospital": org.name},
                             channels=["inapp"], entity_type="appointment", entity_id=apt.id)
    db.session.commit()
    return redirect(url_for("bookings.portal_thanks", ref=apt.ref))


@bp.get("/book/thanks")
def portal_thanks():
    ref = request.args.get("ref", "")
    apt = db.session.query(Appointment).filter_by(ref=ref).first()
    return render_template("booking_thanks.html", apt=apt, ref=ref)


@bp.get("/book/status")
def portal_status():
    ref = (request.args.get("ref") or "").strip()
    phone = (request.args.get("phone") or "").strip()
    apt, error = None, None
    if ref:
        q = db.session.query(Appointment).filter(Appointment.ref.ilike(ref))
        if phone:
            q = q.filter(Appointment.phone == phone.replace(" ", ""))
        apt = q.first()
        if not apt:
            error = "No booking found for that reference number."
    return render_template("booking_status.html", apt=apt, error=error, ref=ref, phone=phone)


@bp.post("/book/cancel")
@rate_limit(limit=6, window=60.0)
def portal_cancel():
    ref = (request.form.get("ref") or "").strip()
    phone = (request.form.get("phone") or "").strip().replace(" ", "")
    apt = db.session.query(Appointment).filter_by(ref=ref, phone=phone).first()
    if not apt:
        flash("Booking not found — check the reference and phone number.", "error")
        return redirect(url_for("bookings.portal_status", ref=ref, phone=phone))
    if apt.status != "BOOKED":
        flash("Only upcoming bookings can be cancelled.", "error")
        return redirect(url_for("bookings.portal_status", ref=ref, phone=phone))
    apt.status = "CANCELLED"
    apt.cancelled_at = now_naive()
    audit("BOOKING_CANCELLED", "appointment", apt.id, {"ref": apt.ref}, org_id=apt.org_id)
    db.session.commit()
    flash("Your booking has been cancelled.", "success")
    return redirect(url_for("bookings.portal_status", ref=ref, phone=phone))


# ================================================================ STAFF
@bp.get("/bookings")
@require_login
def staff_list():
    q = db.session.query(Appointment).filter(Appointment.org_id == current_user.org_id)
    day = request.args.get("date")
    status = request.args.get("status")
    if day:
        try:
            q = q.filter(Appointment.appointment_date == date.fromisoformat(day))
        except ValueError:
            pass
    else:
        q = q.filter(Appointment.appointment_date >= now_naive().date())
    if status in ("BOOKED", "ARRIVED", "CANCELLED", "NO_SHOW"):
        q = q.filter(Appointment.status == status)
    items = q.order_by(Appointment.appointment_date, Appointment.appointment_time).limit(300).all()
    return render_template("bookings_staff.html", items=items, args=request.args,
                           today=now_naive().date())


# Note: appointment check-in is handled by /bookings/<id>/checkin-queue
# (see app/views/queue.py) which also issues the patient's queue ticket.
