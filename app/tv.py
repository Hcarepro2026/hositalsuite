"""TV display engine — live feed for monitors in waiting areas.

WHAT IT DOES
------------
Multiple TVs, but waiting area main TV shows MORE (founder req):
- Queue tickets (code + full name + stats)
- Reception / Billing / PayPoint
- HIMS registered
- Triage waiting + placed
- Doctor call-ins (NOW SERVING)
- Onward desks (Lab, Pharmacy, Wards, etc.)
- LAHSMA clearance

Each TV is a row in tv_screen, per-tenant, admin editable.
Clinic TV filters to its clinic, Department TV to its department,
Main TV shows everything.

NIGERIA NATIVE VOICES - 2 male 2 female recycled daily
-------------------------------------------------------
Browser Speech API voices differ per device. We pick 4 best Nigerian-friendly
voices available:
- Prefer en-NG, yo, ig, ha, then en-GB, en-US
- Try to detect gender from voice name (contains female/male, or known lists)
- Recycle daily: day_of_year % 4 picks which voice speaks today
  Mon = Female1, Tue = Male1, Wed = Female2, Thu = Male2, then repeat
- If no Nigerian voice found, use best English and still rotate

Bilingual: English + Yoruba (founder req). We announce in both:
EN: "Folake Abatan, please go to Room 3, Dental Clinic"
YO: "Folake Abatan, ẹ jọwọ lọ sí Room 3, Dental Clinic"
We use i18n for Yoruba translations of fixed phrases, name stays same.

NO EMR - only names, codes, places, counts.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .models import (
    ConsultingRoom,
    DoctorSession,
    JourneySegment,
    Patient,
    PatientVisit,
    QueueTicket,
    ReceptionIntake,
    ServiceClinic,
    ServiceDestination,
    TvScreen,
    VisitOnward,
    db,
    now_naive,
)


# ------------------------------------------------------------------ helpers
def ensure_default_screens(org_id: int) -> list[TvScreen]:
    """Seed default TVs if none exist. Idempotent."""
    existing = db.session.query(TvScreen).filter_by(org_id=org_id).all()
    if existing:
        return existing
    defaults = [
        TvScreen(
            org_id=org_id,
            code="MAIN",
            name="Waiting Area Main TV",
            location="General Waiting Hall",
            screen_type="WAITING_MAIN",
            show_full_name=True,
            show_queue_stats=True,
            show_reception=True,
            show_triage=True,
            show_consulting=True,
            show_onward=True,
            voice_enabled=True,
            voice_rotate_daily=True,
            voice_languages="en,yo",
            active=True,
        ),
        TvScreen(
            org_id=org_id,
            code="DENTAL",
            name="Dental Clinic TV",
            location="Dental Waiting Area",
            screen_type="CLINIC",
            clinic_code="DENTAL",
            show_full_name=True,
            show_queue_stats=True,
            voice_enabled=True,
            voice_rotate_daily=True,
            voice_languages="en,yo",
            active=True,
        ),
        TvScreen(
            org_id=org_id,
            code="OPD",
            name="OPD TV",
            location="OPD Waiting Area",
            screen_type="CLINIC",
            clinic_code="OPD",
            show_full_name=True,
            show_queue_stats=True,
            voice_enabled=True,
            voice_rotate_daily=True,
            voice_languages="en,yo",
            active=True,
        ),
        TvScreen(
            org_id=org_id,
            code="PHARMACY",
            name="Pharmacy TV",
            location="Pharmacy Waiting Area",
            screen_type="DEPARTMENT",
            show_full_name=True,
            show_queue_stats=False,
            voice_enabled=True,
            voice_rotate_daily=True,
            voice_languages="en,yo",
            active=True,
        ),
    ]
    for s in defaults:
        db.session.add(s)
    db.session.commit()
    return defaults


def _today_start() -> datetime:
    return datetime.combine(now_naive().date(), datetime.min.time())


# ------------------------------------------------------------------ feed
def tv_feed(org_id: int, screen: TvScreen | None = None) -> dict[str, Any]:
    """Build live data for a TV screen. Returns dict for JSON + template."""
    start = _today_start()
    now = now_naive()

    # Determine filters
    clinic_filter = (screen.clinic_code or "").strip().upper() if screen else None
    dept_filter = screen.department_id if screen and screen.department_id else None

    # --- Queue tickets today
    q_q = db.session.query(QueueTicket).filter(
        QueueTicket.org_id == org_id, QueueTicket.queue_date == now.date()
    )
    if dept_filter:
        q_q = q_q.filter(QueueTicket.department_id == dept_filter)
    queue_all = q_q.order_by(QueueTicket.created_at.desc()).limit(100).all()
    queue_waiting = [t for t in queue_all if t.status == "WAITING"]
    queue_called = [t for t in queue_all if t.status == "CALLED"]
    queue_done = [t for t in queue_all if t.status == "DONE"]

    # --- Reception intakes waiting
    r_q = db.session.query(ReceptionIntake).filter(
        ReceptionIntake.org_id == org_id, ReceptionIntake.created_at >= start
    )
    reception_rows = r_q.filter(ReceptionIntake.stage.in_(("RECEPTION", "BILLING", "PAYMENT", "PAID"))).order_by(
        ReceptionIntake.created_at.asc()
    ).limit(50).all()

    # --- Patient visits today
    v_q = db.session.query(PatientVisit).filter(
        PatientVisit.org_id == org_id, PatientVisit.started_at >= start
    )
    if clinic_filter:
        v_q = v_q.filter(db.func.upper(db.func.trim(PatientVisit.clinic)) == clinic_filter)
    visits = v_q.order_by(PatientVisit.started_at.desc()).limit(100).all()
    patient_ids = {v.patient_id for v in visits}
    patients = {p.id: p for p in db.session.query(Patient).filter(Patient.id.in_(patient_ids or [0])).all()}

    triaged = [v for v in visits if v.status == "TRIAGED"]
    in_consult = [v for v in visits if v.status == "IN_CONSULTATION"]
    onward = [v for v in visits if v.status == "ONWARD"]

    # --- Doctor sessions open today
    sessions = (
        db.session.query(DoctorSession)
        .filter(
            DoctorSession.org_id == org_id,
            DoctorSession.duty_date == now.date(),
            DoctorSession.ended_at.is_(None),
            DoctorSession.ready.is_(True),
        )
        .all()
    )
    if clinic_filter:
        sessions = [s for s in sessions if (s.clinic or "").strip().upper() == clinic_filter]

    # --- Onward steps pending
    o_q = db.session.query(VisitOnward).filter(
        VisitOnward.org_id == org_id, VisitOnward.status == "PENDING"
    )
    pending_onward = o_q.order_by(VisitOnward.sent_at.asc()).limit(100).all()
    # Filter onward by clinic if screen is clinic-specific? Onward destination code may match clinic code?
    # For clinic TV, show onward steps where visit clinic matches
    if clinic_filter:
        visit_map = {v.id: v for v in visits}
        pending_onward = [
            step for step in pending_onward if visit_map.get(step.visit_id) and (visit_map[step.visit_id].clinic or "").upper() == clinic_filter
        ]

    # --- Journey segments open (where patient is now)
    open_segments = (
        db.session.query(JourneySegment)
        .filter(JourneySegment.org_id == org_id, JourneySegment.ended_at.is_(None))
        .order_by(JourneySegment.entered_at.desc())
        .limit(100)
        .all()
    )

    # --- Build NOW SERVING: patients IN_CONSULTATION + recently CALLED queue + recently triaged placed
    now_serving = []
    # 1. Patients currently in consultation (most important)
    for v in sorted(in_consult, key=lambda x: x.seen_at or x.triaged_at or x.started_at, reverse=True)[:3]:
        p = patients.get(v.patient_id)
        if not p:
            continue
        now_serving.append(
            {
                "type": "consultation",
                "code": p.hospital_number,
                "name": p.full_name,
                "spoken": p.spoken_name,
                "clinic": v.clinic,
                "room": v.consulting_room,
                "doctor": v.doctor.name if v.doctor else "",
                "since": v.seen_at or v.triaged_at,
                "waited": max(0, int((now - (v.seen_at or v.triaged_at or v.started_at)).total_seconds() // 60)),
            }
        )
    # 2. Recently called queue tickets
    for t in sorted(queue_called, key=lambda x: x.called_at or x.created_at, reverse=True)[:2]:
        now_serving.append(
            {
                "type": "queue_called",
                "code": t.code,
                "name": t.patient_name or "Patient",
                "spoken": t.patient_name or "Patient",
                "clinic": t.department.name if t.department else "",
                "room": t.department.name if t.department else "",
                "doctor": "",
                "since": t.called_at,
                "waited": 0,
            }
        )

    # --- NEXT: triaged waiting + queue waiting
    next_up = []
    for v in sorted(triaged, key=lambda x: x.triaged_at or x.started_at)[:5]:
        p = patients.get(v.patient_id)
        if not p:
            continue
        next_up.append(
            {
                "type": "triaged",
                "code": p.hospital_number,
                "name": p.full_name,
                "spoken": p.spoken_name,
                "clinic": v.clinic,
                "room": v.consulting_room or v.clinic,
                "doctor": v.doctor.name if v.doctor else "",
            }
        )
    for t in sorted(queue_waiting, key=lambda x: x.created_at)[:5]:
        if len(next_up) >= 8:
            break
        next_up.append(
            {
                "type": "queue_waiting",
                "code": t.code,
                "name": t.patient_name or "Patient",
                "spoken": t.patient_name or "Patient",
                "clinic": t.department.name if t.department else "",
                "room": "",
                "doctor": "",
            }
        )

    # --- Stats for waiting area main TV
    stats = {
        "queue_waiting": len(queue_waiting),
        "queue_called": len(queue_called),
        "queue_done": len(queue_done),
        "reception_waiting": len(reception_rows),
        "triaged": len(triaged),
        "in_consultation": len(in_consult),
        "onward_pending": len(pending_onward),
        "doctors_ready": len(sessions),
        "total_today": len(visits) + len(queue_all),
    }

    # --- Per clinic breakdown for main TV
    clinic_counts = {}
    for v in visits:
        key = (v.clinic or "UNKNOWN").upper()
        clinic_counts[key] = clinic_counts.get(key, 0) + 1

    return {
        "screen": screen,
        "now": now,
        "now_serving": now_serving,
        "next_up": next_up,
        "queue_waiting": queue_waiting,
        "queue_called": queue_called,
        "reception": reception_rows,
        "triaged": triaged,
        "in_consultation": in_consult,
        "onward_pending": pending_onward,
        "sessions": sessions,
        "stats": stats,
        "clinic_counts": clinic_counts,
        "patients": patients,
    }


# ------------------------------------------------------------------ voice rotation
def voice_rotation_for_today(org_id: int, screen_id: int | None = None) -> dict:
    """Pick 2 male 2 female Nigerian voices recycled daily.

    Returns dict with day_index, voice_slot, and description.
    Actual voice selection happens in browser (getVoices), but we tell browser
    which slot to use today so all TVs in same hospital speak same voice that day.
    """
    day_of_year = now_naive().timetuple().tm_yday
    # 4 slots: 0=Female1,1=Male1,2=Female2,3=Male2
    slot = day_of_year % 4
    slot_names = ["Female Voice 1 - Ada (Nigerian)", "Male Voice 1 - Emeka (Nigerian)", "Female Voice 2 - Folake (Nigerian)", "Male Voice 2 - Chinedu (Nigerian)"]
    return {
        "day_of_year": day_of_year,
        "slot": slot,
        "slot_name": slot_names[slot],
        "all_slots": slot_names,
        # Yoruba + English enabled
        "languages": ["en-NG", "yo-NG", "en"],
    }
