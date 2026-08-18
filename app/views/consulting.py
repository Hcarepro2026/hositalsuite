"""Stage C — the consulting room. Stage D — the onward desks."""
from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user

from .. import consulting, tracking, triage
from ..audit import audit
from ..models import (CLINIC_LABELS, CLINICS, CONSULTING_ROOMS,
                      ONWARD_DESTINATIONS, ONWARD_LABELS, DoctorSession,
                      Patient, PatientVisit, VisitOnward, db, now_naive)
from ..security import require_role

bp = Blueprint("consulting", __name__)

# An onward destination and a journey stage are deliberately different things:
# BILLING at the front door is not the same measurement as BILLING after the
# consultation, and a manager needs to tell them apart.
_ONWARD_STAGE = {
    "LABORATORY": "LABORATORY", "PHARMACY": "PHARMACY",
    "BILLING": "BILLING_OUT", "MEGALEX": "MEGALEX",
    "LAHSMA": "LAHSMA", "EMERGENCY": "EMERGENCY",
}

CLINICAL = ("SUPER_ADMIN", "HEAD_ADMIN_HR", "ADMIN_MANAGER", "APEX_NURSE",
            "HOD", "MD_CEO", "DMD", "DCST")
# The onward desks (lab, pharmacy, billing, pay point) are staffed by the same
# front-of-house roles as Reception in this hospital.
DESKS = ("SUPER_ADMIN", "HEAD_ADMIN_HR", "ADMIN_MANAGER", "APEX_NURSE", "HOD")


def _visit(vid: int) -> PatientVisit:
    v = db.session.get(PatientVisit, vid)
    if v is None or v.org_id != current_user.org_id:
        from flask import abort
        abort(404)
    return v


# ================================================================ Stage C
@bp.get("/consulting-room")
@require_role(*CLINICAL)
def room():
    """The doctor's own call room queue: call in, then finish and route on."""
    org_id = current_user.org_id
    day = now_naive().date()
    session = (db.session.query(DoctorSession)
               .filter_by(org_id=org_id, doctor_id=current_user.id,
                          duty_date=day, ended_at=None).first())
    queue = consulting.doctor_queue(org_id, current_user.id)
    patients = {p.id: p for p in db.session.query(Patient)
                .filter(Patient.id.in_([v.patient_id for v in queue] or [0])).all()}
    rows = [{"visit": v, "patient": patients.get(v.patient_id),
             "waited": consulting.wait_minutes(v),
             # Unassigned patients waiting in this doctor's clinic — anyone
             # free may take them. Marked so the doctor knows the difference.
             "unclaimed": v.doctor_id is None} for v in queue]
    return render_template(
        "consulting/room.html", session=session, rows=rows,
        current=consulting.in_consultation(org_id, current_user.id),
        patients=patients, clinics=CLINICS, rooms=CONSULTING_ROOMS,
        clinic_labels=CLINIC_LABELS, destinations=ONWARD_DESTINATIONS,
        available=triage.is_available(org_id, current_user.id))


@bp.post("/consulting-room/<int:vid>/call-in")
@require_role(*CLINICAL)
def call_in(vid: int):
    visit = _visit(vid)
    err = consulting.call_in(visit, current_user.id)
    if err:
        flash(err, "error")
        return redirect(url_for("consulting.room"))
    patient = db.session.get(Patient, visit.patient_id)
    tracking.safely(tracking.enter, visit.org_id, "CONSULTATION", visit_id=visit.id,
                   patient_id=visit.patient_id,
                   department_id=visit.department_id,
                   staff_id=current_user.id)
    consulting.announce_called_in(visit, patient)
    audit("PATIENT_CALLED_IN", "patient_visit", visit.id,
          {"room": visit.consulting_room})
    db.session.commit()
    flash(f"{patient.full_name} has been called in to "
          f"{visit.consulting_room or 'your room'}.", "success")
    return redirect(url_for("consulting.room"))


@bp.post("/consulting-room/<int:vid>/finish")
@require_role(*CLINICAL)
def finish(vid: int):
    visit = _visit(vid)
    patient = db.session.get(Patient, visit.patient_id)
    destinations = request.form.getlist("destination")
    err, steps = consulting.finish(visit, current_user.id, destinations,
                                   note=request.form.get("note", ""))
    if err:
        flash(err, "error")
        return redirect(url_for("consulting.room"))

    if steps:
        # One open segment per desk: each is measured separately, so "how long
        # does the pharmacy take?" is answerable even when the same patient is
        # also waiting on the laboratory.
        tracking.safely(tracking.leave, visit.org_id, visit_id=visit.id)
        for step in steps:
            tracking.safely(tracking.enter, visit.org_id, _ONWARD_STAGE.get(step.destination, "PHARMACY"),
                           visit_id=visit.id, patient_id=visit.patient_id,
                           staff_id=current_user.id, close_previous=False)
    else:
        tracking.safely(tracking.close_journey, visit.org_id, visit_id=visit.id)
    consulting.announce_onward(visit, patient, steps)
    audit("CONSULTATION_FINISHED", "patient_visit", visit.id,
          {"sent_to": [s.destination for s in steps] or ["home"]})
    db.session.commit()

    if steps:
        where = ", ".join(ONWARD_LABELS.get(s.destination, s.destination).split(" — ")[0]
                          for s in steps)
        flash(f"{patient.full_name} sent to {where}.", "success")
    else:
        flash(f"{patient.full_name} is finished for today. Visit closed.", "success")
    return redirect(url_for("consulting.room"))


# ================================================================ Stage D
@bp.get("/onward")
@require_role(*DESKS)
def onward_board():
    """Every desk in one board: who has been sent to you, and how long ago."""
    org_id = current_user.org_id
    counts = consulting.pending_counts(org_id)
    boards = []
    for code, label in ONWARD_DESTINATIONS:
        steps = consulting.pending_for(org_id, code)
        visits = {v.id: v for v in db.session.query(PatientVisit)
                  .filter(PatientVisit.id.in_([s.visit_id for s in steps] or [0])).all()}
        patients = {p.id: p for p in db.session.query(Patient)
                    .filter(Patient.id.in_([v.patient_id for v in visits.values()] or [0])).all()}
        boards.append({
            "code": code, "label": label, "count": counts.get(code, 0),
            "rows": [{"step": s, "visit": visits.get(s.visit_id),
                      "patient": patients.get(visits[s.visit_id].patient_id)
                      if s.visit_id in visits else None,
                      "waited": max(0, int((now_naive() - s.sent_at).total_seconds() // 60))}
                     for s in steps],
        })
    return render_template("consulting/onward.html", boards=boards,
                           total=sum(counts.values()))


@bp.post("/onward/<int:step_id>/done")
@require_role(*DESKS)
def onward_done(step_id: int):
    step = db.session.get(VisitOnward, step_id)
    if step is None or step.org_id != current_user.org_id:
        from flask import abort
        abort(404)
    visit = db.session.get(PatientVisit, step.visit_id)
    patient = db.session.get(Patient, visit.patient_id) if visit else None

    tracking.safely(tracking.leave, step.org_id, visit_id=step.visit_id,
                   stage=_ONWARD_STAGE.get(step.destination))
    closed = consulting.complete_step(step, current_user.id)
    if closed:
        tracking.safely(tracking.close_journey, step.org_id, visit_id=step.visit_id)
    if closed and patient is not None:
        # Everything is finished — tell them they can go home.
        consulting.announce_onward(visit, patient, [])
    audit("ONWARD_STEP_COMPLETED", "visit_onward", step.id,
          {"destination": step.destination, "closed_visit": closed})
    db.session.commit()

    name = patient.full_name if patient else "Patient"
    flash(f"{name} done at {step.label.split(' — ')[0]}."
          + (" Visit closed — they are finished for today." if closed else ""),
          "success")
    return redirect(url_for("consulting.onward_board"))
