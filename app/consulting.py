"""Stages C and D — the consulting room, and where the patient goes next.

STAGE C — THE CALL ROOM QUEUE
    "The doctors on duty and also ready to work by clicking to consult would
     see patients assigned to them from TRIAGE (the Call Room Queue)"

The doctor sees their own queue, calls the next patient in (which announces
them by name), and marks the consultation finished.

STAGE D — ONWARD ROUTING
    "The Doctor after attending to the patient would now push the patient to
     one, two or three out of the following
     (LAHSMA/Billing/Megalek/Laboratory/Pharmacy/Emergency)"

One, two or three — so destinations are rows, not a single column. Each is
completed independently by the desk that receives the patient, and the visit
closes only when every destination is done.

STILL NOT AN EMR
----------------
This module records WHERE a patient was sent and WHETHER they arrived. It never
records what a test was for, what was prescribed, or any clinical reason.
"Send to Pharmacy" is a direction to a desk, not a prescription. A guard test
fails the build if a clinical column ever appears.
"""
from __future__ import annotations

from datetime import datetime

from . import announce
from .models import (ONWARD_CODES, ONWARD_LABELS, Patient, PatientVisit,
                     VisitOnward, db, now_naive)


# ------------------------------------------------------------------ the queue
def doctor_queue(org_id: int, doctor_id: int) -> list[PatientVisit]:
    """This doctor's call room queue today — longest waiting first."""
    start = datetime.combine(now_naive().date(), datetime.min.time())
    return (db.session.query(PatientVisit)
            .filter(PatientVisit.org_id == org_id,
                    PatientVisit.doctor_id == doctor_id,
                    PatientVisit.started_at >= start,
                    PatientVisit.status.in_(("TRIAGED", "IN_CONSULTATION")))
            .order_by(PatientVisit.triaged_at.asc().nullsfirst())
            .all())


def in_consultation(org_id: int, doctor_id: int) -> PatientVisit | None:
    """The patient currently in the room with this doctor, if any."""
    start = datetime.combine(now_naive().date(), datetime.min.time())
    return (db.session.query(PatientVisit)
            .filter(PatientVisit.org_id == org_id,
                    PatientVisit.doctor_id == doctor_id,
                    PatientVisit.started_at >= start,
                    PatientVisit.status == "IN_CONSULTATION")
            .first())


def wait_minutes(visit: PatientVisit, now: datetime | None = None) -> int:
    """How long since Triage placed them — the wait that matters to a doctor."""
    now = now or now_naive()
    since = visit.triaged_at or visit.started_at or now
    return max(0, int((now - since).total_seconds() // 60))


# ------------------------------------------------------------------ Stage C
def call_in(visit: PatientVisit, doctor_id: int) -> str:
    """Doctor calls the next patient into the room. Returns "" or an error.

    Only ONE patient may be in the room at a time. If the doctor forgot to
    finish the last one, say so plainly rather than quietly having two people
    'in consultation' with the same doctor.
    """
    if visit.doctor_id != doctor_id:
        return "That patient is not on your call room queue."
    if visit.status == "IN_CONSULTATION":
        return "That patient is already in your room."
    if visit.status != "TRIAGED":
        return "That patient is not waiting to be seen."

    busy = in_consultation(visit.org_id, doctor_id)
    if busy is not None and busy.id != visit.id:
        return ("You already have a patient in your room. Finish that "
                "consultation first.")

    visit.status = "IN_CONSULTATION"
    visit.seen_at = now_naive()
    return ""


def finish(visit: PatientVisit, doctor_id: int, destinations: list[str],
           note: str = "") -> tuple[str, list[VisitOnward]]:
    """Doctor finishes and pushes the patient onward. Returns (error, steps).

    With no destinations the visit is simply CLOSED — plenty of patients are
    seen and sent home, and forcing a destination would make the doctor invent
    one. With destinations the visit goes ONWARD and stays open until each is
    completed.
    """
    if visit.doctor_id != doctor_id:
        return "That patient is not on your call room queue.", []
    if visit.status not in ("IN_CONSULTATION", "TRIAGED"):
        return "That consultation has already been finished.", []

    picked = [d for d in dict.fromkeys(destinations or []) if d in ONWARD_CODES]
    now = now_naive()
    steps: list[VisitOnward] = []
    for dest in picked:
        step = VisitOnward(org_id=visit.org_id, visit_id=visit.id,
                           destination=dest, status="PENDING",
                           note=(note or "").strip()[:200] or None,
                           sent_at=now, sent_by=doctor_id)
        db.session.add(step)
        steps.append(step)

    if picked:
        visit.status = "ONWARD"
    else:
        visit.status = "CLOSED"
        visit.closed_at = now
    if visit.seen_at is None:
        visit.seen_at = now
    db.session.flush()
    return "", steps


# ------------------------------------------------------------------ Stage D
def pending_for(org_id: int, destination: str) -> list[VisitOnward]:
    """Everyone the doctors have sent to one desk and who has not been done."""
    return (db.session.query(VisitOnward)
            .filter(VisitOnward.org_id == org_id,
                    VisitOnward.destination == destination,
                    VisitOnward.status == "PENDING")
            .order_by(VisitOnward.sent_at.asc())
            .limit(200).all())


def pending_counts(org_id: int) -> dict[str, int]:
    rows = (db.session.query(VisitOnward.destination,
                             db.func.count(VisitOnward.id))
            .filter(VisitOnward.org_id == org_id,
                    VisitOnward.status == "PENDING")
            .group_by(VisitOnward.destination).all())
    return {dest: n for dest, n in rows}


def complete_step(step: VisitOnward, user_id: int | None = None) -> bool:
    """A desk finishes with the patient. Closes the visit if it was the last.

    Returns True when this completion closed the whole visit.
    """
    if step.status == "DONE":
        return False
    step.status = "DONE"
    step.completed_at = now_naive()
    step.completed_by = user_id

    visit = db.session.get(PatientVisit, step.visit_id)
    if visit is None:
        return False
    outstanding = [s for s in visit.onward_steps if s.status != "DONE"]
    if not outstanding and visit.status == "ONWARD":
        visit.status = "CLOSED"
        visit.closed_at = now_naive()
        return True
    return False


def outstanding_for_visit(visit: PatientVisit) -> list[VisitOnward]:
    return [s for s in visit.onward_steps if s.status != "DONE"]


# ------------------------------------------------------------------ voice
def announce_called_in(visit: PatientVisit, patient: Patient) -> None:
    """Call the patient into the room, by name. This is the moment they wait for."""
    announce.to_station(
        visit.org_id, "consult_call_in",
        patient=announce.speech_name(patient.spoken_name),
        room=visit.consulting_room or "the consulting room")


def announce_onward(visit: PatientVisit, patient: Patient,
                    steps: list[VisitOnward]) -> None:
    """Tell the patient where to go next, and tell each desk to expect them."""
    spoken = announce.speech_name(patient.spoken_name)
    if not steps:
        announce.to_station(visit.org_id, "visit_complete", patient=spoken)
        return

    # One sentence to the patient naming every place, so they hear it once and
    # in order rather than as three separate announcements they must piece
    # together while walking away from the door.
    places = [s.place for s in steps]
    if len(places) == 1:
        where = places[0]
    elif len(places) == 2:
        where = f"{places[0]}, then {places[1]}"
    else:
        where = ", then ".join(places)
    announce.to_station(visit.org_id, "go_onward", patient=spoken, place=where)

    for step in steps:
        if step.destination == "EMERGENCY":
            announce.to_station(visit.org_id, "emergency_arrival",
                                place="Accident and Emergency",
                                detail=f"{spoken} is being sent from the "
                                       f"consulting room now.")
        else:
            announce.to_station(visit.org_id, "desk_expecting",
                                patient=spoken, place=step.place)


def announce_desk_backlog(org_id: int, destination: str) -> None:
    """Tell a desk out loud when patients are stacking up waiting for it."""
    n = len(pending_for(org_id, destination))
    if n >= 3:
        announce.to_station(
            org_id, "queue_waiting", count=n,
            place=ONWARD_LABELS.get(destination, destination).split(" — ")[0])
