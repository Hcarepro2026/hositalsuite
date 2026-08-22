"""Aftercare — thank-you SMS after visit closed, no EMR.

WHY
---
Patient finished whole journey today (all desks done). Sending a thank-you
SMS turns data into trust: "We saw you, thank you, rate us". Founder asked
for it as feature 5.

NOT EMR — only time, not diagnosis.

Per-tenant, uses existing SMS queue (Termii/Twilio/sandbox).
"""

from __future__ import annotations

from .models import Patient, PatientVisit, db, now_naive
from . import sms as sms_engine


def _visit_duration_minutes(visit: PatientVisit) -> int | None:
    if not visit.started_at or not visit.closed_at:
        return None
    secs = (visit.closed_at - visit.started_at).total_seconds()
    if secs < 0:
        return None
    return max(1, int(secs // 60))


def thank_you_sms(org_id: int, visit: PatientVisit, patient: Patient | None = None) -> bool:
    """Queue a thank-you SMS when visit just closed. Returns True if queued."""
    try:
        if visit.org_id != org_id:
            return False
        if visit.status != "CLOSED":
            return False
        if not patient:
            patient = db.session.get(Patient, visit.patient_id)
        if not patient or not patient.phone:
            return False
        # Don't spam if already sent for this visit
        from .models import SmsMessage

        existing = (
            db.session.query(SmsMessage)
            .filter(
                SmsMessage.org_id == org_id,
                SmsMessage.entity_type == "patient_visit",
                SmsMessage.entity_id == visit.id,
                SmsMessage.kind == "thank_you",
            )
            .first()
        )
        if existing:
            return False

        mins = _visit_duration_minutes(visit)
        if mins is not None and mins < 240:
            duration_txt = f" Your visit today took about {mins} minutes."
        else:
            duration_txt = ""

        org_name = "the hospital"
        try:
            from .models import Organization

            org = db.session.get(Organization, org_id)
            if org:
                org_name = org.name
        except Exception:
            pass

        feedback_url = "/feedback"
        try:
            from flask import current_app

            base = (current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
            if base:
                feedback_url = f"{base}/feedback"
        except Exception:
            pass

        body_en = f"Thank you for visiting {org_name} today.{duration_txt} We appreciate you. Please rate your experience: {feedback_url}"
        body_yo = f"E seun fun bibẹ wa si {org_name} loni. E jọwọ ẹ fun wa ni imọran: {feedback_url}"
        body = f"{body_en}\n{body_yo}"

        sms_engine.queue_sms(
            org_id,
            patient.phone,
            body[:480],
            kind="thank_you",
            entity_type="patient_visit",
            entity_id=visit.id,
        )
        return True
    except Exception:
        # Never break closing a visit because SMS failed.
        # Do NOT rollback the outer visit-close transaction — that would undo
        # the CLOSED status. Just return False; the outer commit will still
        # close the visit. If a half-added SmsMessage is in the session, expunge.
        try:
            for obj in list(db.session.new):
                if obj.__class__.__name__ == "SmsMessage":
                    db.session.expunge(obj)
        except Exception:
            pass
        return False
