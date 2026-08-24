"""Queue management (spec §6): digital tickets, staff control, privacy-safe screens."""
from __future__ import annotations

import re
import secrets

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)
from flask_login import current_user

from .. import sms as sms_engine
from ..audit import audit
from ..models import Appointment, Department, QueueTicket, db, now_naive
from ..security import rate_limit, require_login

bp = Blueprint("queue", __name__)

PHONE_RE = re.compile(r"^\+?\d{7,15}$")


def _default_org():
    """Tenant for this request (see services.current_org)."""
    from ..services import current_org
    return current_org()


def _dept_letter(dept: Department) -> str:
    return re.sub(r"[^A-Z]", "", dept.name.upper())[:1] or "Q"


def next_ticket(org_id: int, dept: Department, day) -> QueueTicket:
    count = (db.session.query(QueueTicket)
             .filter_by(org_id=org_id, department_id=dept.id, queue_date=day).count())
    return count + 1


def avg_service_minutes(org_id: int, department_id: int) -> float | None:
    """Average time from joining to being served (last 15 completed tickets)."""
    done = (db.session.query(QueueTicket)
            .filter_by(org_id=org_id, department_id=department_id, status="DONE")
            .filter(QueueTicket.served_at.isnot(None))
            .order_by(QueueTicket.served_at.desc()).limit(15).all())
    spans = [(t.served_at - t.created_at).total_seconds() / 60 for t in done if t.served_at]
    if len(spans) < 3:
        return None
    return sum(spans) / len(spans)


# ================================================================ PUBLIC
def announce_queue_depth(org_id: int, dept: Department) -> None:
    """Tell the department how many patients are now waiting.

    Goes to BOTH the individual staff of that department (their own phone) and
    the shared station screen, which is what the founder asked for.
    """
    from .. import announce
    from ..models import QueueTicket as QT
    waiting = (db.session.query(QT)
               .filter(QT.org_id == org_id, QT.department_id == dept.id,
                       QT.queue_date == now_naive().date(),
                       QT.status == "WAITING").count())
    if waiting <= 0:
        return
    kind = "dispensary_waiting" if "pharm" in (dept.name or "").lower() else "queue_waiting"
    place = dept.name
    # personal devices: staff assigned to that department
    for role in ("HOD", "ADMIN_MANAGER"):
        announce.to_role(org_id, role, kind, department_id=dept.id,
                         count=waiting, place=place,
                         entity_type="department", entity_id=dept.id)
    # shared station screen for the area
    announce.to_station(org_id, kind, department_id=dept.id,
                        name=dept.name, count=waiting, place=place)


@bp.get("/queue/join")
@rate_limit(limit=30, window=60.0)
def join_page():
    org = _default_org()
    if not org:
        abort(503)
    from ..patient_places import public_departments
    depts = public_departments(org.id)
    db.session.commit()
    pre = request.args.get("dept", type=int)
    loc = (request.args.get("loc") or "").strip().upper()
    return render_template("queue_join.html", org=org, depts=depts, pre=pre, loc=loc)


@bp.post("/queue/join")
@rate_limit(limit=10, window=120.0)
def join_submit():
    org = _default_org()
    if not org:
        abort(503)
    now = now_naive()
    dept = db.session.get(Department, request.form.get("department_id", type=int) or 0)
    name = (request.form.get("patient_name") or "").strip()
    phone = (request.form.get("phone") or "").strip().replace(" ", "")
    if not dept or dept.org_id != org.id or len(name) < 2:
        flash("Please choose a department and enter your name.", "error")
        return redirect(url_for("queue.join_page"))
    if phone and not PHONE_RE.match(phone):
        flash("Please enter a valid phone number or leave it empty.", "error")
        return redirect(url_for("queue.join_page"))

    from ..patient_places import is_fast_track_dept
    is_fast = bool(request.form.get("is_fast_track")) or is_fast_track_dept(dept)
    fast_reason = (request.form.get("fast_track_reason") or "").strip().upper()[:40] or None
    # MUST consent for Fast Track — premium service
    if is_fast:
        if not request.form.get("fast_track_consent"):
            flash("To join Fast Track, you must tick the box that says you understand it is a premium service and you agree to pay a little more for quick service.", "error")
            return redirect(url_for("queue.join_page"))
    n = next_ticket(org.id, dept, now.date())
    t = QueueTicket(
        org_id=org.id,
        code=f"{_dept_letter(dept)}-{n:03d}",
        access_key=secrets.token_urlsafe(12),
        department_id=dept.id,
        queue_date=now.date(),
        patient_name=name[:120],
        phone=phone or None,
        status="WAITING",
        source="qr" if request.form.get("loc") else "link",
        is_fast_track=is_fast,
        fast_track_reason=fast_reason if is_fast else None,
    )
    db.session.add(t)
    db.session.flush()
    from .. import referrals as refeng
    refeng.stamp_queue(org.id)
    audit("QUEUE_JOINED", "queue_ticket", t.id, {"code": t.code}, org_id=org.id)

    # Announce to the department: staff hear how many are now waiting.
    # Previously nothing was raised here at all, so no announcement could
    # ever be spoken however well the voice engine worked.
    try:
        announce_queue_depth(org.id, dept)
    except Exception:                                    # noqa: BLE001
        current_app.logger.exception("queue announcement failed")

    db.session.commit()
    return redirect(url_for("queue.ticket_page", key=t.access_key))


@bp.get("/queue/ticket")
def ticket_page():
    key = request.args.get("key", "")
    t = db.session.query(QueueTicket).filter_by(access_key=key).first()
    if not t:
        return render_template("error.html", code=404, message="Queue ticket not found."), 404
    waiting = (db.session.query(QueueTicket)
               .filter_by(org_id=t.org_id, department_id=t.department_id,
                          queue_date=t.queue_date, status="WAITING")
               .filter(QueueTicket.id < t.id).count()) if t.status == "WAITING" else 0
    avg = avg_service_minutes(t.org_id, t.department_id)
    est = int(waiting * avg) if (avg and t.status == "WAITING") else None
    now_serving = (db.session.query(QueueTicket)
                   .filter_by(org_id=t.org_id, department_id=t.department_id,
                              queue_date=t.queue_date, status="CALLED")
                   .order_by(QueueTicket.called_at.desc()).first())

    # --- Link to reception intake + visit journey (TV ↔ patient page) ---
    intake = None
    visit = None
    segments = []
    onward = []
    total_m = 0
    journey_total = None
    try:
        from ..models import ReceptionIntake, PatientVisit, JourneySegment, VisitOnward
        from .. import tracking as tracking_engine
        # intake linked from ticket or by phone/name today
        if getattr(t, 'intake_id', None):
            intake = db.session.get(ReceptionIntake, t.intake_id)
        if not intake and t.phone:
            # try find today's intake by phone
            from ..models import now_naive as _now
            start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
            intake = (db.session.query(ReceptionIntake)
                      .filter(ReceptionIntake.org_id == t.org_id,
                              ReceptionIntake.phone == t.phone,
                              ReceptionIntake.created_at >= start)
                      .order_by(ReceptionIntake.created_at.desc()).first())
        if intake and intake.visit_id:
            visit = db.session.get(PatientVisit, intake.visit_id)
        if intake and not visit and intake.patient_id:
            # latest visit for this patient today
            from ..models import now_naive as _now
            start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
            visit = (db.session.query(PatientVisit)
                     .filter(PatientVisit.org_id == t.org_id,
                             PatientVisit.patient_id == intake.patient_id,
                             PatientVisit.started_at >= start)
                     .order_by(PatientVisit.started_at.desc()).first())
        if visit:
            segments = (db.session.query(JourneySegment)
                        .filter(JourneySegment.visit_id == visit.id)
                        .order_by(JourneySegment.entered_at.asc()).all())
            onward = (db.session.query(VisitOnward)
                      .filter(VisitOnward.visit_id == visit.id)
                      .order_by(VisitOnward.sent_at.asc()).all())
            # door to door
            if segments:
                from datetime import datetime as _dt
                first = segments[0].entered_at
                last = segments[-1].ended_at or _dt.utcnow()
                try:
                    total_m = max(0, int((last - first).total_seconds() // 60))
                except Exception:
                    total_m = 0
            try:
                est_j = tracking_engine.estimate_remaining_journey(t.org_id, visit)
                journey_total = est_j.get('total')
            except Exception:
                journey_total = None
    except Exception:
        # never crash patient page
        intake = intake
        segments = []
        onward = []
        total_m = 0

    return render_template("queue_ticket.html", t=t, ahead=waiting, est=est,
                           now_serving=now_serving, intake=intake, visit=visit,
                           segments=segments, onward=onward, total_m=total_m,
                           journey_total=journey_total)


@bp.get("/queue/screen")
def screen():
    """Privacy-safe display: ticket numbers only — never names (§6)."""
    org = _default_org()
    dept_id = request.args.get("dept", type=int)
    dept = db.session.get(Department, dept_id) if dept_id else None
    today = now_naive().date()
    now_serving = None
    upcoming = []
    if dept:
        now_serving = (db.session.query(QueueTicket)
                       .filter_by(org_id=org.id, department_id=dept.id, queue_date=today,
                                  status="CALLED").order_by(QueueTicket.called_at.desc()).first())
        upcoming = (db.session.query(QueueTicket)
                    .filter_by(org_id=org.id, department_id=dept.id, queue_date=today,
                               status="WAITING").order_by(QueueTicket.id).limit(6).all())
    depts = (db.session.query(Department)
             .filter_by(org_id=org.id, active=True).order_by(Department.name).all())
    resp = render_template("queue_screen.html", org=org, dept=dept, depts=depts,
                           now_serving=now_serving, upcoming=upcoming)
    return resp


# ================================================================ STAFF
@bp.get("/queue")
@require_login
def staff_queue():
    today = now_naive().date()
    dept_id = request.args.get("dept", type=int)
    q = db.session.query(QueueTicket).filter_by(org_id=current_user.org_id, queue_date=today)
    if dept_id:
        q = q.filter(QueueTicket.department_id == dept_id)
    # Priority lane first — fast-track patients seen first at every desk
    waiting = q.filter(QueueTicket.status == "WAITING").order_by(QueueTicket.is_fast_track.desc(), QueueTicket.id).all()
    called = q.filter(QueueTicket.status == "CALLED").order_by(QueueTicket.called_at.desc()).all()
    done_count = q.filter(QueueTicket.status.in_(("DONE", "NO_SHOW"))).count()
    depts = db.session.query(Department).filter_by(org_id=current_user.org_id, active=True).all()
    return render_template("queue_staff.html", waiting=waiting, called=called,
                           done_count=done_count, depts=depts, dept_id=dept_id, today=today)


@bp.post("/queue/<int:tid>/call-next")
@require_login
def call_next(tid: int):
    """Staff control: call the next waiting ticket (progression)."""
    dept_id = request.form.get("department_id", type=int)
    t = None
    if tid:
        t = db.session.get(QueueTicket, tid)
        if not t or t.org_id != current_user.org_id:
            abort(404)
        if t.status != "WAITING":
            flash("That ticket is no longer waiting.", "error")
            return redirect(url_for("queue.staff_queue", dept=dept_id))
    else:
        t = (db.session.query(QueueTicket)
             .filter_by(org_id=current_user.org_id, department_id=dept_id,
                        queue_date=now_naive().date(), status="WAITING")
             .order_by(QueueTicket.id).first())
        if not t:
            flash("No patients waiting in this queue.", "info")
            return redirect(url_for("queue.staff_queue", dept=dept_id))
    t.status = "CALLED"
    t.called_at = now_naive()
    audit("QUEUE_CALLED", "queue_ticket", t.id, {"code": t.code})
    # patient notification (SMS where configured — never exposes clinical detail)
    if t.phone:
        sms_engine.queue_sms(t.org_id, t.phone,
                             f"You are next in the {t.department.name} queue. Ticket {t.code}. "
                             f"Please proceed now.", kind="alert",
                             entity_type="queue_ticket", entity_id=t.id)
        from ..tasks import dispatch_delivery
        dispatch_delivery()   # §39 — async delivery
    db.session.commit()
    flash(f"Called {t.code}.", "success")
    return redirect(url_for("queue.staff_queue", dept=t.department_id))


@bp.post("/queue/<int:tid>/finish")
@require_login
def finish(tid: int):
    t = db.session.get(QueueTicket, tid)
    if not t or t.org_id != current_user.org_id:
        abort(404)
    outcome = request.form.get("outcome", "done")
    if outcome == "no_show":
        t.status = "NO_SHOW"
    else:
        t.status = "DONE"
        t.served_at = now_naive()
    audit("QUEUE_FINISHED", "queue_ticket", t.id, {"code": t.code, "outcome": t.status})
    db.session.commit()
    return redirect(url_for("queue.staff_queue", dept=t.department_id))


@bp.post("/queue/<int:tid>/to-reception")
@require_login
def to_reception(tid: int):
    """Convert a QR queue ticket into a Reception intake — unifies the two queues.

    WHY THIS EXISTS (founder question #3)
    -------------------------------------
    QueueTicket (patient self-joins via /queue/join QR) and PatientVisit
    (Reception → HIMS → Triage → Doctor → Onward) were two separate worlds.
    A patient could have a ticket AND a visit, staff had two lists, and the
    patient screen showed only half the journey.

    Best approach: keep both entry points (QR is valuable), but link them.
    When staff tap \"Send to Reception\", we create a ReceptionIntake from the
    ticket, link them, and voice-announce so Reception knows someone is coming.
    The ticket is marked DONE, the journey continues as one.
    """
    from .. import announce, reception as reception_engine
    from ..models import ReceptionIntake

    t = db.session.get(QueueTicket, tid)
    if not t or t.org_id != current_user.org_id:
        abort(404)
    if t.status != "WAITING" and t.status != "CALLED":
        flash("That ticket is no longer waiting.", "error")
        return redirect(url_for("queue.staff_queue", dept=t.department_id))

    # Split name into surname/first for intake (best effort)
    parts = (t.patient_name or "").strip().split()
    surname = parts[-1] if parts else "—"
    first = " ".join(parts[:-1]) if len(parts) > 1 else (parts[0] if parts else "Patient")

    # Create intake — preserve fast-track
    intake = ReceptionIntake(
        org_id=t.org_id,
        ref=reception_engine.next_ref(t.org_id),
        surname=surname[:80],
        first_name=first[:80],
        phone=t.phone,
        stage="RECEPTION",
        created_by=current_user.id,
        is_fast_track=bool(getattr(t, "is_fast_track", False)),
        fast_track_reason=getattr(t, "fast_track_reason", None),
    )
    db.session.add(intake)
    db.session.flush()

    # Link ticket → intake → journey
    t.intake_id = intake.id
    t.status = "DONE"
    t.served_at = now_naive()

    # Tracking + voice
    try:
        from .. import tracking

        tracking.safely(tracking.enter, t.org_id, "RECEPTION", intake_id=intake.id, staff_id=current_user.id)
        spoken = announce.speech_name(t.patient_name or "patient")
        announce.to_station(t.org_id, "reception_arrival", patient=spoken, detail=f"from queue {t.code}")
    except Exception:
        pass

    audit("QUEUE_TO_RECEPTION", "queue_ticket", t.id, {"code": t.code, "intake_ref": intake.ref})
    db.session.commit()
    flash(f"{t.patient_name or 'Patient'} ({t.code}) sent to Reception as {intake.ref}.", "success")
    return redirect(url_for("queue.staff_queue", dept=t.department_id))


@bp.post("/bookings/<int:aid>/checkin-queue")
@require_login
def booking_checkin_queue(aid: int):
    """Check a booking in and give the patient a queue ticket — gates on Fast Track payment upfront."""
    from .. import services
    apt = db.session.get(Appointment, aid)
    if not apt or apt.org_id != current_user.org_id:
        abort(404)
    if apt.status != "BOOKED":
        flash("Only a booked appointment can be checked in.", "error")
        return redirect(url_for("bookings.staff_list"))
    # Payment gate: if Fast Track booking requires payment upfront, block until PAID or WAIVED
    requires_pay = bool(services.get_setting(apt.org_id, "fast_track_booking_requires_payment"))
    if apt.is_fast_track and requires_pay:
        if apt.fast_track_payment_status not in ("PAID", "WAIVED"):
            flash(f"⭐ Payment required before check-in for {apt.patient_name} — Fast Track amount {apt.fast_track_amount or ''}. Mark as PAID first.", "error")
            return redirect(url_for("bookings.staff_list"))
    now = now_naive()
    apt.status = "ARRIVED"
    apt.arrived_at = now
    n = next_ticket(apt.org_id, apt.department, apt.appointment_date)
    # Fast Track Booking linked to Reception — preserve gold flag
    ft = bool(getattr(apt, 'is_fast_track', False))
    ft_reason = getattr(apt, 'fast_track_reason', None) or "PREMIUM"
    t = QueueTicket(org_id=apt.org_id, code=f"{_dept_letter(apt.department)}-{n:03d}",
                    access_key=secrets.token_urlsafe(12), department_id=apt.department_id,
                    queue_date=apt.appointment_date, patient_name=apt.patient_name,
                    phone=apt.phone, status="WAITING", source="booking", appointment_id=apt.id,
                    is_fast_track=ft, fast_track_reason=ft_reason if ft else None)
    db.session.add(t)
    db.session.flush()
    audit("BOOKING_ARRIVED", "appointment", apt.id, {"ref": apt.ref, "queue": t.code, "fast_track": ft, "paid": apt.fast_track_payment_status})
    db.session.commit()
    flash(f"⭐ {apt.patient_name} checked in — queue ticket {t.code} gold lane.", "success")
    return redirect(url_for("queue.staff_queue", dept=apt.department_id))
