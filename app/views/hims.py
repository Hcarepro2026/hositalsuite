"""HIMS Register desk — Stage A of the patient flow.

Two jobs, exactly as the founder described them:

  i.  open a folder for a new / first-visit patient
  ii. search for the folder of a returning patient

Everything is at ``/hims``. The desk clerk lands on a search box, because
searching first is what stops duplicate folders being created.
"""
from __future__ import annotations

from flask import (Blueprint, Response, abort, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user

from .. import announce, hims
from ..audit import audit
from ..models import (ASSISTANCE_LABELS, ASSISTANCE_NEEDS, CATEGORY_LABELS,
                      PATIENT_CATEGORIES, PATIENT_LANGS, PAYER_LABELS,
                      PAYER_TYPES, SEXES, VISIT_TYPES, Department, Patient,
                      PatientVisit, db, now_naive)
from ..navigation import require_permission
from ..security import require_role

bp = Blueprint("hims", __name__, url_prefix="/hims")

# The HIMS desk itself, plus management sight. HIMS clerks are HODs of the
# HIMS department in this hospital's structure, so HOD is included.
DESK = ("SUPER_ADMIN", "HEAD_ADMIN_HR", "ADMIN_MANAGER", "HOD")
VIEWERS = DESK + ("MD_CEO", "DMD", "DCST", "APEX_NURSE")


def _org():
    from ..services import current_org
    return current_org()


def _form_context(**extra):
    ctx = dict(sexes=SEXES, payers=PAYER_TYPES, categories=PATIENT_CATEGORIES,
               assistance_needs=ASSISTANCE_NEEDS, assistance_labels=ASSISTANCE_LABELS,
               langs=PATIENT_LANGS,
               visit_types=VISIT_TYPES,
               depts=db.session.query(Department)
               .filter_by(org_id=current_user.org_id, active=True)
               .order_by(Department.name).all())
    ctx.update(extra)
    return ctx


def _announce_arrival(patient, visit) -> None:
    """Say it out loud. This is the whole point of the app.

    Three separate announcements, because they need different people to act:
      * the patient is registered and waiting  -> the station screen
      * they need a wheelchair / a seat / help -> URGENT, so somebody goes now
      * they are a returning patient           -> greet them by name
    """
    org_id = patient.org_id
    dept = visit.department.name if visit and visit.department else "Triage"

    announce.to_station(org_id, "patient_registered",
                        patient=announce.speech_name(patient.full_name),
                        place=dept, department_id=visit.department_id if visit else None)

    if patient.care_flags:
        # Somebody who cannot stand should not be left standing.
        announce.to_station(org_id, "assistance_needed",
                            patient=announce.speech_name(patient.full_name),
                            place="the reception desk",
                            detail="; ".join(patient.care_flags),
                            department_id=visit.department_id if visit else None)

    if patient.is_returning and visit and visit.visit_type != "NEW":
        announce.to_station(org_id, "returning_patient",
                            patient=announce.speech_name(patient.full_name),
                            place="reception",
                            department_id=visit.department_id if visit else None)


def _announce_reception_depth(org_id: int) -> None:
    """Tell the desk how many people are now waiting to be seen."""
    waiting = len([v for v in hims.today_visits(org_id, status="REGISTERED")])
    if waiting >= 1:
        announce.to_station(org_id, "reception_waiting", count=waiting,
                            place="the reception desk")


# ================================================================ desk / search
@bp.get("/")
@require_role(*VIEWERS)
@require_permission("hims")
def desk():
    """The HIMS desk: search first, register second.

    FIX 2026-08-21: HIMS is the most appropriate to open the folder after
    payment. Previously only Reception showed PAID patients waiting for folder,
    so if Reception and HIMS were different people, HIMS never saw them and
    patients got stuck. Now HIMS desk shows PAID intakes directly.
    """
    term = (request.args.get("q") or "").strip()
    results = hims.search(current_user.org_id, term) if term else []

    # PAID intakes waiting for folder — this is the main queue for HIMS
    # after the Reception -> Billing -> Paypoint walk.
    from .. import reception
    from ..models import ReceptionIntake

    from .. import branches as br
    paid_q = (
        db.session.query(ReceptionIntake)
        .filter(
            ReceptionIntake.org_id == current_user.org_id,
            ReceptionIntake.stage == "PAID",
        )
    )
    paid_q = br.apply_branch_filter(paid_q, ReceptionIntake.branch_id)
    paid_waiting = (
        paid_q.order_by(ReceptionIntake.paid_at.asc().nullsfirst(),
                        ReceptionIntake.created_at.asc())
        .limit(100)
        .all()
    )

    return render_template(
        "hims/desk.html",
        term=term,
        results=results,
        searched=bool(term),
        stats=hims.stats(current_user.org_id),
        visits=hims.today_visits(current_user.org_id)[:15],
        paid_waiting=paid_waiting,
        payer_labels=PAYER_LABELS,
        category_labels=CATEGORY_LABELS,
    )


# ================================================================ open folder FROM reception flow (PAID -> REGISTERED)
# Who is most appropriate to push to HIMS? HIMS desk itself, after Paypoint.
# Previously only Reception had the button, so HIMS never saw PAID patients.
@bp.post("/intake/<int:intake_id>/open-folder")
@require_role(*DESK)
@require_permission("hims")
def open_folder_from_intake(intake_id: int):
    """HIMS turns a PAID intake into a real patient folder.

    This is the correct handover: Paypoint marks PAID, HIMS opens folder.
    Reception's copy is kept for small hospitals where one clerk does everything,
    but this is the primary path.
    """
    from .. import reception as reception_engine
    from ..models import ReceptionIntake
    from ..services import current_org
    from .. import tracking as tracking_engine

    row = db.session.get(ReceptionIntake, intake_id)
    if row is None or row.org_id != current_user.org_id:
        abort(404)
    if row.stage != "PAID":
        flash("That patient has not paid yet. Payment is recorded before the folder is opened.", "error")
        return redirect(url_for("hims.desk"))
    if row.patient_id:
        flash("A folder has already been opened for that patient.", "error")
        return redirect(url_for("hims.folder", pid=row.patient_id))

    org = current_org()
    if org is None:
        abort(503)

    values, errors = hims.validate(reception_engine.folder_values(row), org_id=current_user.org_id)
    if errors:
        flash("The folder could not be opened: " + " ".join(errors), "error")
        return redirect(url_for("hims.desk"))

    # Returning patient? Reuse folder
    existing = hims.possible_duplicates(
        current_user.org_id, values["surname"], values["first_name"], values.get("phone")
    )
    patient = existing[0] if existing else None

    if patient is not None:
        for field in (
            "phone",
            "address",
            "occupation",
            "payer_type",
            "payer_number",
            "payer_name",
            "preferred_lang",
            "assistance",
            "care_note",
            "nok_name",
            "nok_phone",
            "nok_relationship",
        ):
            new_value = values.get(field)
            if new_value:
                setattr(patient, field, new_value)
        db.session.flush()
    else:
        patient = Patient(
            org_id=current_user.org_id,
            hospital_number=hims.next_hospital_number(org),
            created_by=current_user.id,
            consent_at=now_naive(),
            branch_id=getattr(current_user, "branch_id", None)
            or getattr(row, "branch_id", None),
            **values,
        )
        db.session.add(patient)
        try:
            db.session.flush()
        except Exception:
            db.session.rollback()
            patient = Patient(
                org_id=current_user.org_id,
                hospital_number=hims.next_hospital_number(org),
                created_by=current_user.id,
                consent_at=now_naive(),
                branch_id=getattr(current_user, "branch_id", None)
                or getattr(row, "branch_id", None),
                **values,
            )
            db.session.add(patient)
            db.session.flush()

    visit = hims.open_visit(patient, user_id=current_user.id, reason="", visit_type="NEW")
    row.patient_id = patient.id
    row.visit_id = visit.id
    row.stage = "REGISTERED"
    row.registered_at = now_naive()

    tracking_engine.safely(
        tracking_engine.enter,
        current_user.org_id,
        "HIMS",
        intake_id=row.id,
        visit_id=visit.id,
        patient_id=patient.id,
        staff_id=current_user.id,
    )
    tracking_engine.safely(
        tracking_engine.enter,
        current_user.org_id,
        "TRIAGE",
        visit_id=visit.id,
        patient_id=patient.id,
        staff_id=current_user.id,
    )

    _announce_arrival(patient, visit)
    _announce_reception_depth(current_user.org_id)
    audit(
        "HIMS_FOLDER_OPENED_FROM_INTAKE",
        "reception_intake",
        row.id,
        {"ref": row.ref, "patient": patient.hospital_number},
    )
    db.session.commit()

    flash(
        f"Folder opened for {patient.full_name} — {patient.hospital_number}. Sent to Triage.",
        "success",
    )
    return redirect(url_for("hims.folder", pid=patient.id))


# ================================================================ open a folder
@bp.get("/register")
@require_role(*DESK)
@require_permission("hims")
def register_form():
    """Blank folder form. Any search term already typed is carried across."""
    prefill = {}
    term = (request.args.get("q") or "").strip()
    if term:
        # If they searched a phone number, put it in the phone box; if they
        # searched a name, split it into surname + first name.
        if hims._digits(term) and len(hims._digits(term)) >= 7:
            prefill["phone"] = hims._digits(term)
        else:
            parts = term.split()
            prefill["surname"] = parts[0] if parts else ""
            prefill["first_name"] = " ".join(parts[1:]) if len(parts) > 1 else ""
    org = _org()
    return render_template("hims/register.html", **_form_context(
        form=prefill, errors=[], duplicates=[],
        next_number=hims.next_hospital_number(org) if org else "—"))


@bp.post("/register")
@require_role(*DESK)
@require_permission("hims")
def register_save():
    """Create the folder — after checking for an existing one."""
    org = _org()
    if not org:
        abort(503)
    form = request.form.to_dict()
    values, errors = hims.validate(form, org_id=current_user.org_id)

    # SEARCH BEFORE CREATE. Show likely duplicates and make the clerk confirm.
    dupes = []
    if not errors and form.get("confirm_new") != "1":
        dupes = hims.possible_duplicates(current_user.org_id, values["surname"],
                                         values["first_name"], values["phone"])
    if errors or dupes:
        return render_template("hims/register.html", **_form_context(
            form=form, errors=errors, duplicates=dupes,
            next_number=hims.next_hospital_number(org))), (400 if errors else 200)

    patient = Patient(org_id=current_user.org_id,
                      hospital_number=hims.next_hospital_number(org),
                      created_by=current_user.id, consent_at=now_naive(),
                      branch_id=getattr(current_user, "branch_id", None),
                      **values)
    db.session.add(patient)
    try:
        db.session.flush()
    except Exception:                                              # noqa: BLE001
        # Two clerks registered in the same instant: take the next free number.
        db.session.rollback()
        patient = Patient(org_id=current_user.org_id,
                          hospital_number=hims.next_hospital_number(org),
                          created_by=current_user.id, consent_at=now_naive(),
                          branch_id=getattr(current_user, "branch_id", None),
                          **values)
        db.session.add(patient)
        db.session.flush()

    visit = None
    if form.get("start_visit") == "1":
        visit = hims.open_visit(patient, user_id=current_user.id,
                                reason=form.get("reason", ""), visit_type="NEW",
                                department_id=request.form.get("department_id", type=int))
    if visit:
        _announce_arrival(patient, visit)
        _announce_reception_depth(current_user.org_id)
    audit("PATIENT_FOLDER_OPENED", "patient", patient.id,
          {"number": patient.hospital_number, "name": patient.full_name})
    db.session.commit()

    flash(f"Folder opened for {patient.full_name} — hospital number "
          f"{patient.hospital_number}." + (" Visit started." if visit else ""), "success")
    return redirect(url_for("hims.folder", pid=patient.id))


# ================================================================ view a folder
@bp.get("/folder/<int:pid>")
@require_role(*VIEWERS)
@require_permission("hims")
def folder(pid: int):
    p = db.session.get(Patient, pid)
    if not p or p.org_id != current_user.org_id:
        abort(404)
    open_visit = next((v for v in p.visits
                       if v.status not in ("CLOSED", "CANCELLED")
                       and v.started_at
                       and v.started_at.date() == now_naive().date()), None)
    return render_template("hims/folder.html", p=p, visits=p.visits[:25],
                           payer_labels=PAYER_LABELS, category_labels=CATEGORY_LABELS,
                           assistance_labels=ASSISTANCE_LABELS,
                           depts=db.session.query(Department)
                           .filter_by(org_id=current_user.org_id, active=True)
                           .order_by(Department.name).all(),
                           visit_types=VISIT_TYPES,
                           open_visit=open_visit,
                           can_edit=current_user.role in DESK)


@bp.get("/folder/<int:pid>/edit")
@require_role(*DESK)
@require_permission("hims")
def edit_form(pid: int):
    p = db.session.get(Patient, pid)
    if not p or p.org_id != current_user.org_id:
        abort(404)
    form = {c.name: getattr(p, c.name) for c in Patient.__table__.columns}
    form["date_of_birth"] = p.date_of_birth.isoformat() if p.date_of_birth else ""
    return render_template("hims/register.html", **_form_context(
        form=form, errors=[], duplicates=[], patient=p,
        next_number=p.hospital_number))


@bp.post("/folder/<int:pid>/edit")
@require_role(*DESK)
@require_permission("hims")
def edit_save(pid: int):
    p = db.session.get(Patient, pid)
    if not p or p.org_id != current_user.org_id:
        abort(404)
    form = request.form.to_dict()
    values, errors = hims.validate(form, org_id=current_user.org_id, patient_id=p.id)
    if errors:
        return render_template("hims/register.html", **_form_context(
            form=form, errors=errors, duplicates=[], patient=p,
            next_number=p.hospital_number)), 400
    before = {"name": p.full_name, "phone": p.phone, "payer": p.payer_type}
    for k, val in values.items():
        setattr(p, k, val)
    audit("PATIENT_FOLDER_UPDATED", "patient", p.id,
          {"number": p.hospital_number, "before": before,
           "after": {"name": p.full_name, "phone": p.phone, "payer": p.payer_type}})
    db.session.commit()
    flash("Folder updated.", "success")
    return redirect(url_for("hims.folder", pid=p.id))


# ================================================================ visits
@bp.post("/folder/<int:pid>/visit")
@require_role(*DESK)
@require_permission("hims")
def start_visit(pid: int):
    """Returning patient found — start today's attendance."""
    p = db.session.get(Patient, pid)
    if not p or p.org_id != current_user.org_id:
        abort(404)
    # One person in the building = one open visit. Live site used to flash a
    # red error and leave the clerk stranded. Reception already reuses the
    # visit; HIMS must do the same so the patient still reaches Triage.
    open_already = next((v for v in p.visits
                         if v.status not in ("CLOSED", "CANCELLED")
                         and v.started_at
                         and v.started_at.date() == now_naive().date()), None)
    if open_already:
        extra = (request.form.get("reason") or "").strip()
        if extra and not open_already.reason:
            open_already.reason = extra[:300]
        audit("PATIENT_VISIT_REUSED", "visit", open_already.id,
              {"patient": p.hospital_number, "visit": open_already.visit_no})
        db.session.commit()
        flash(f"{p.full_name} already has today's visit open "
              f"({open_already.visit_no}). Using that one — they are still "
              "in the flow. Close it only when they have left.", "info")
        return redirect(url_for("hims.folder", pid=p.id))
    visit = hims.open_visit(p, user_id=current_user.id,
                            reason=request.form.get("reason", ""),
                            visit_type=request.form.get("visit_type") or None,
                            department_id=request.form.get("department_id", type=int))
    db.session.flush()
    _announce_arrival(p, visit)
    _announce_reception_depth(current_user.org_id)
    audit("PATIENT_VISIT_STARTED", "visit", None,
          {"patient": p.hospital_number, "visit": visit.visit_no})
    db.session.commit()
    flash(f"Visit {visit.visit_no} started for {p.full_name}. "
          "They are now waiting for Triage.", "success")
    return redirect(url_for("hims.folder", pid=p.id))


@bp.post("/visit/<int:vid>/close")
@require_role(*DESK)
@require_permission("hims")
def close_visit(vid: int):
    v = db.session.get(PatientVisit, vid)
    if not v or v.org_id != current_user.org_id:
        abort(404)
    v.status = "CLOSED"
    v.closed_at = now_naive()
    audit("PATIENT_VISIT_CLOSED", "visit", v.id, {"visit": v.visit_no})
    db.session.commit()
    flash(f"Visit {v.visit_no} closed.", "success")
    return redirect(url_for("hims.folder", pid=v.patient_id))


@bp.post("/folder/<int:pid>/retire")
@require_role("SUPER_ADMIN", "HEAD_ADMIN_HR")
@require_permission("hims")
def retire_folder(pid: int):
    """Hide a folder (duplicate, or opened in error). Never deletes history."""
    p = db.session.get(Patient, pid)
    if not p or p.org_id != current_user.org_id:
        abort(404)
    p.active = False
    audit("PATIENT_FOLDER_RETIRED", "patient", p.id,
          {"number": p.hospital_number, "reason": request.form.get("reason", "")[:200]})
    db.session.commit()
    flash(f"Folder {p.hospital_number} retired. It no longer appears in searches, "
          "but its history is kept.", "success")
    return redirect(url_for("hims.desk"))


# ================================================================ export
@bp.get("/export")
@require_role("SUPER_ADMIN", "HEAD_ADMIN_HR", "MD_CEO")
@require_permission("hims")
def export():
    import csv
    import io
    rows = (db.session.query(Patient)
            .filter_by(org_id=current_user.org_id, active=True)
            .order_by(Patient.hospital_number).all())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Hospital Number", "Surname", "First Name", "Other Names", "Sex",
                "Age", "Phone", "Address", "LGA", "Next of Kin", "NOK Phone",
                "Payment", "Scheme Number", "Category", "Language",
                "Assistance needed", "Opened", "Last Visit"])
    for p in rows:
        w.writerow([p.hospital_number, p.surname, p.first_name, p.other_names or "",
                    p.sex, p.age if p.age is not None else "", p.phone or "",
                    p.address or "", p.lga or "", p.nok_name or "", p.nok_phone or "",
                    p.payer_label, p.payer_number or "", p.category_label,
                    p.lang_label,
                    "; ".join(ASSISTANCE_LABELS.get(a, a) for a in p.assistance_list),
                    p.created_at.date() if p.created_at else "",
                    p.last_visit_at.date() if p.last_visit_at else "never"])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename=patient-register-{now_naive().date()}.csv"})
