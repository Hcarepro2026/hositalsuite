"""Reception desk — the front door of the patient flow.

The receptionist takes the details ONCE, finds out what help the person needs,
records their insurance, then walks them: Billing -> Paying Point -> HIMS ->
Triage. Every hand-off is announced out loud by the browser, free of charge.
"""
from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user

from .. import hims, reception
from ..audit import audit
from ..models import (ASSISTANCE_NEEDS, INTAKE_STAGES, PATIENT_LANGS,
                      PAYER_LABELS, PAYER_TYPES, Patient, ReceptionIntake,
                      SEXES, db, now_naive)
from ..security import require_role

bp = Blueprint("reception", __name__, url_prefix="/reception")

# Who works the front of house. Billing and the paying point are staffed by the
# same front-desk roles in this hospital, so they share the screen and each
# action is audit-logged with the name of whoever pressed it.
DESK = ("SUPER_ADMIN", "HEAD_ADMIN_HR", "ADMIN_MANAGER", "HOD")
VIEWERS = DESK + ("MD_CEO", "DMD", "DCST", "APEX_NURSE")

NOK_RELATIONSHIPS = ("Husband", "Wife", "Father", "Mother", "Son", "Daughter",
                     "Brother", "Sister", "Uncle", "Aunt", "Cousin", "Friend",
                     "Neighbour", "Guardian", "Employer", "Other")


def _form_context(**extra):
    ctx = dict(sexes=SEXES, payers=PAYER_TYPES, langs=PATIENT_LANGS,
               assistance_needs=ASSISTANCE_NEEDS, relationships=NOK_RELATIONSHIPS)
    ctx.update(extra)
    return ctx


# ================================================================ the desk
@bp.get("/")
@require_role(*VIEWERS)
def desk():
    """Who is waiting, and where they are in the walk."""
    org_id = current_user.org_id
    return render_template(
        "reception/desk.html",
        waiting=reception.waiting(org_id),
        counts=reception.counts_by_stage(org_id),
        registered_today=reception.today_registered(org_id),
        stages=INTAKE_STAGES, payer_labels=PAYER_LABELS)


# ================================================================ new patient
@bp.get("/new")
@require_role(*DESK)
def new_form():
    return render_template("reception/new.html", form={}, errors=[],
                           **_form_context())


@bp.post("/new")
@require_role(*DESK)
def new_save():
    values, errors = reception.clean_form(request.form)
    if errors:
        return render_template("reception/new.html", form=request.form,
                               errors=errors, **_form_context()), 400

    intake = reception.create_intake(current_user.org_id, values, current_user.id)
    reception.announce_arrival(intake)
    audit("RECEPTION_INTAKE_CREATED", "reception_intake", intake.id,
          {"ref": intake.ref, "name": intake.full_name})
    db.session.commit()
    flash(f"{intake.full_name} taken in ({intake.ref}). "
          f"Now send them to Billing.", "success")
    return redirect(url_for("reception.desk"))


# ================================================================ the walk
def _get(intake_id: int) -> ReceptionIntake:
    row = db.session.get(ReceptionIntake, intake_id)
    if row is None or row.org_id != current_user.org_id:
        from flask import abort
        abort(404)
    return row


@bp.post("/<int:intake_id>/to-billing")
@require_role(*DESK)
def to_billing(intake_id: int):
    intake = _get(intake_id)
    reception.advance(intake, "BILLING", ref=(request.form.get("bill_ref") or ""))
    reception.announce_stage(intake)
    audit("RECEPTION_SENT_TO_BILLING", "reception_intake", intake.id,
          {"ref": intake.ref})
    db.session.commit()
    flash(f"{intake.full_name} sent to the Billing Unit.", "success")
    return redirect(url_for("reception.desk"))


@bp.post("/<int:intake_id>/to-payment")
@require_role(*DESK)
def to_payment(intake_id: int):
    intake = _get(intake_id)
    reception.advance(intake, "PAYMENT", ref=(request.form.get("bill_ref") or ""))
    reception.announce_stage(intake)
    audit("RECEPTION_SENT_TO_PAYMENT", "reception_intake", intake.id,
          {"ref": intake.ref})
    db.session.commit()
    flash(f"{intake.full_name} sent to the Megalex Paying Point.", "success")
    return redirect(url_for("reception.desk"))


@bp.post("/<int:intake_id>/paid")
@require_role(*DESK)
def mark_paid(intake_id: int):
    intake = _get(intake_id)
    reception.advance(intake, "PAID", ref=(request.form.get("payment_ref") or ""))
    reception.announce_stage(intake)
    audit("RECEPTION_PAYMENT_RECORDED", "reception_intake", intake.id,
          {"ref": intake.ref, "receipt": intake.payment_ref})
    db.session.commit()
    flash(f"Payment recorded for {intake.full_name}. HIMS can now open the folder.",
          "success")
    return redirect(url_for("reception.desk"))


@bp.post("/<int:intake_id>/cancel")
@require_role(*DESK)
def cancel(intake_id: int):
    intake = _get(intake_id)
    intake.stage = "CANCELLED"
    audit("RECEPTION_INTAKE_CANCELLED", "reception_intake", intake.id,
          {"ref": intake.ref})
    db.session.commit()
    flash(f"{intake.full_name} marked as left without completing.", "success")
    return redirect(url_for("reception.desk"))


# ================================================================ hand to HIMS
@bp.post("/<int:intake_id>/open-folder")
@require_role(*DESK)
def open_folder(intake_id: int):
    """HIMS turns a PAID intake into a real patient folder.

    The details were captured at Reception, so nothing is re-typed and the
    patient is not asked the same questions twice. Folder creation itself is
    delegated to `hims` so there is exactly one definition of a valid folder.
    """
    intake = _get(intake_id)
    if intake.stage != "PAID":
        flash("That patient has not paid yet. Payment is recorded before the "
              "folder is opened.", "error")
        return redirect(url_for("reception.desk"))
    if intake.patient_id:
        flash("A folder has already been opened for that patient.", "error")
        return redirect(url_for("hims.folder", pid=intake.patient_id))

    from ..services import current_org
    org = current_org()
    if org is None:
        from flask import abort
        abort(503)

    # Run the Reception details through HIMS's own validator, so a folder made
    # this way is held to exactly the same standard as one typed at the HIMS
    # desk. If Reception ever collects something HIMS rejects, we say so
    # plainly instead of writing a half-valid folder.
    values, errors = hims.validate(reception.folder_values(intake),
                                   org_id=current_user.org_id)
    if errors:
        flash("The folder could not be opened: " + " ".join(errors), "error")
        return redirect(url_for("reception.desk"))

    patient = Patient(org_id=current_user.org_id,
                      hospital_number=hims.next_hospital_number(org),
                      created_by=current_user.id, consent_at=now_naive(), **values)
    db.session.add(patient)
    try:
        db.session.flush()
    except Exception:                                              # noqa: BLE001
        # Two clerks opening a folder in the same instant: take the next number.
        db.session.rollback()
        patient = Patient(org_id=current_user.org_id,
                          hospital_number=hims.next_hospital_number(org),
                          created_by=current_user.id, consent_at=now_naive(), **values)
        db.session.add(patient)
        db.session.flush()

    visit = hims.open_visit(patient, user_id=current_user.id, visit_type="NEW")
    intake.patient_id = patient.id
    intake.visit_id = visit.id
    reception.advance(intake, "REGISTERED")
    reception.announce_stage(intake)
    audit("PATIENT_FOLDER_OPENED", "patient", patient.id,
          {"intake": intake.ref, "number": patient.hospital_number,
           "name": patient.full_name, "via": "reception"})
    db.session.commit()
    flash(f"Folder {patient.hospital_number} opened for {patient.full_name}. "
          f"Sent to Triage.", "success")
    return redirect(url_for("hims.folder", pid=patient.id))
