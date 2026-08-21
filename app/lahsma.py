"""LAHSMA desk — simple clearance tracking, no serious insurance work.

THE FOUNDER'S CLARIFICATION (21 Aug 2026)
----------------------------------------
\"LAHSMA desk should be limited to seeing patient together with policy numbers
and attend to them with basic minimum by issuing clearance. just like billing
issues Bill to patients (just patient flow tracking) no serious work because
LAHSMA has their web application for patient and policy management.\"

So this desk does NOT adjudicate claims, does NOT store money, does NOT copy
insurance numbers for audit. It simply shows:

  * Who the doctor sent to LAHSMA (VisitOnward destination=LAHSMA, status=PENDING)
  * Their policy number (from Patient.payer_number)
  * A button: \"Clearance issued\" -> marks DONE

It is flow tracking, exactly like Billing issuing a bill.

TWO SOURCES OF PATIENTS
-----------------------
1. Post-consultation: doctor pushes to LAHSMA (VisitOnward) — the main use.
2. Reception walk: patient with payer_type LAHSMA/NHIS/HMO who has paid and
   has a folder — optionally visible for awareness, but primary is #1.

For now, this module only handles #1, because #2 is already covered by HIMS
showing payer info. If founder wants #2 later, we can add a second tab.

NOT AN EMR, NOT A CLAIMS ENGINE
-------------------------------
No diagnosis, no amount, no decision reason. Just \"clearance issued\".
Guard test ensures no money columns appear here.
"""

from __future__ import annotations

from .models import Patient, PatientVisit, VisitOnward, db, now_naive


def pending(org_id: int) -> list[dict]:
    """Patients waiting at LAHSMA desk, oldest first.

    Returns list of dicts: {step, visit, patient, waited_minutes}
    """
    steps = (
        db.session.query(VisitOnward)
        .filter(
            VisitOnward.org_id == org_id,
            VisitOnward.destination == "LAHSMA",
            VisitOnward.status == "PENDING",
        )
        .order_by(VisitOnward.sent_at.asc())
        .limit(200)
        .all()
    )
    if not steps:
        return []

    visit_ids = [s.visit_id for s in steps]
    visits = {
        v.id: v
        for v in db.session.query(PatientVisit)
        .filter(PatientVisit.id.in_(visit_ids))
        .all()
    }
    patient_ids = [v.patient_id for v in visits.values()]
    patients = {
        p.id: p
        for p in db.session.query(Patient)
        .filter(Patient.id.in_(patient_ids or [0]))
        .all()
    }

    now = now_naive()
    out = []
    for s in steps:
        v = visits.get(s.visit_id)
        p = patients.get(v.patient_id) if v else None
        waited = max(0, int((now - s.sent_at).total_seconds() // 60))
        out.append(
            {
                "step": s,
                "visit": v,
                "patient": p,
                "waited": waited,
            }
        )
    return out


def pending_count(org_id: int) -> int:
    return (
        db.session.query(db.func.count(VisitOnward.id))
        .filter(
            VisitOnward.org_id == org_id,
            VisitOnward.destination == "LAHSMA",
            VisitOnward.status == "PENDING",
        )
        .scalar()
        or 0
    )


def issue_clearance(step: VisitOnward, user_id: int | None = None) -> bool:
    """Mark clearance as issued. Returns True if visit closed."""
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
