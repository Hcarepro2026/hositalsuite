"""HIMS — Health Information Management System: the patient folder desk.

Stage A of the patient flow the founder described:

    "HIMS - Register
       i.  open folder for new/first visit patient
       ii. Search for the folder of returning patient"

WHY THIS MATTERS MORE THAN IT LOOKS
-----------------------------------
Before this, the suite had no patient. A booking held a name string; a queue
ticket held another name string; nothing joined them. Mrs Abatan booking twice
was two unrelated rows. Nothing could answer "has she been here before?", carry
her LAHSMA number to Billing, or give a doctor a record to open.

Everything downstream — Triage, the consulting room queue, onward routing to
LAHSMA / Billing / Megalex / Laboratory / Pharmacy — needs one thing first: a
folder with a number on it. That is what this module makes.

DESIGN RULES
------------
* SEARCH BEFORE CREATE. Opening a duplicate folder for someone who already has
  one is the classic HIMS failure: two folders, half the history in each. The
  register form therefore checks for likely duplicates and shows them BEFORE
  saving, rather than after.
* NEVER INVENT A BIRTHDAY. Many patients do not know their date of birth. We
  accept a stated age instead and record it honestly as an age.
* THE HOSPITAL NUMBER IS THE HOSPITAL'S. It is generated per tenant as
  ``IJD/2026/00001`` from the organisation code, and it is unique within that
  hospital only.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from sqlalchemy import func, or_

from .models import (CATEGORY_CODES, GENOTYPES, PAYER_CODES, Patient,
                     PatientVisit, db, new_code, now_naive)
from .security import clean_phone, valid_phone

MAX_SEARCH_RESULTS = 50


# ------------------------------------------------------------------ numbering
def _org_prefix(org) -> str:
    """Short letters for the folder number, from the hospital's own code."""
    raw = re.sub(r"[^A-Z]", "", (getattr(org, "code", "") or "").upper())
    if not raw:
        raw = re.sub(r"[^A-Z]", "", (getattr(org, "name", "") or "").upper())
    return (raw[:3] or "HOS")


def next_hospital_number(org) -> str:
    """Generate the next folder number for this hospital, e.g. ``IJD/2026/00042``.

    Counts only THIS year's folders for this tenant, then retries on collision.
    Two clerks registering at the same moment cannot be given the same number:
    the database unique constraint is the real guarantee, and this loop simply
    finds the next free one.
    """
    prefix = _org_prefix(org)
    year = now_naive().year
    stem = f"{prefix}/{year}/"
    last = (db.session.query(Patient.hospital_number)
            .filter(Patient.org_id == org.id, Patient.hospital_number.like(f"{stem}%"))
            .order_by(Patient.hospital_number.desc()).first())
    seq = 0
    if last and last[0]:
        tail = last[0].rsplit("/", 1)[-1]
        if tail.isdigit():
            seq = int(tail)
    for bump in range(1, 200):
        candidate = f"{stem}{seq + bump:05d}"
        exists = (db.session.query(Patient.id)
                  .filter_by(org_id=org.id, hospital_number=candidate).first())
        if not exists:
            return candidate
    # Astronomically unlikely; fall back to something guaranteed unique.
    return f"{stem}{new_code(6)}"


def next_visit_no(org_id: int) -> str:
    today = now_naive().date()
    stem = f"V{today:%Y%m%d}-"
    n = (db.session.query(func.count(PatientVisit.id))
         .filter(PatientVisit.org_id == org_id,
                 PatientVisit.visit_no.like(f"{stem}%")).scalar() or 0)
    for bump in range(1, 500):
        candidate = f"{stem}{n + bump:04d}"
        if not db.session.query(PatientVisit.id).filter_by(
                org_id=org_id, visit_no=candidate).first():
            return candidate
    return f"{stem}{new_code(4)}"


# ------------------------------------------------------------------ search
def _digits(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def search(org_id: int, term: str, limit: int = MAX_SEARCH_RESULTS) -> list[Patient]:
    """Find a returning patient's folder.

    Clerks search by whatever the patient gives them: the folder number, a
    phone number, a surname, a first name, or all of it in one box. We accept
    every one of those rather than making them choose a field first.
    """
    term = (term or "").strip()
    if not term:
        return []
    q = db.session.query(Patient).filter(Patient.org_id == org_id,
                                         Patient.active.is_(True))
    digits = _digits(term)
    like = f"%{term.lower()}%"
    conds = [
        func.lower(Patient.hospital_number).like(like),
        func.lower(Patient.surname).like(like),
        func.lower(Patient.first_name).like(like),
        func.lower(Patient.other_names).like(like),
    ]
    if len(digits) >= 4:
        conds.append(Patient.phone.like(f"%{digits}%"))
        conds.append(Patient.phone_alt.like(f"%{digits}%"))
        conds.append(Patient.nok_phone.like(f"%{digits}%"))
    # "abatan lekan" — try it as surname + first name too
    parts = [p for p in re.split(r"[\s,]+", term.lower()) if p]
    if len(parts) >= 2:
        conds.append(db.and_(func.lower(Patient.surname).like(f"%{parts[0]}%"),
                             func.lower(Patient.first_name).like(f"%{parts[1]}%")))
        conds.append(db.and_(func.lower(Patient.surname).like(f"%{parts[1]}%"),
                             func.lower(Patient.first_name).like(f"%{parts[0]}%")))
    return (q.filter(or_(*conds))
            .order_by(Patient.last_visit_at.desc().nullslast(), Patient.surname)
            .limit(limit).all())


def possible_duplicates(org_id: int, surname: str, first_name: str,
                        phone: str = "", exclude_id: int | None = None) -> list[Patient]:
    """Folders that might already belong to this person.

    Called BEFORE a new folder is created. Two folders for one patient means
    half the history in each, which is the worst thing a HIMS desk can do.
    """
    surname = (surname or "").strip().lower()
    first_name = (first_name or "").strip().lower()
    digits = _digits(phone)
    if not surname and not digits:
        return []
    conds = []
    if surname and first_name:
        conds.append(db.and_(func.lower(Patient.surname) == surname,
                             func.lower(Patient.first_name) == first_name))
    if len(digits) >= 7:
        conds.append(Patient.phone.like(f"%{digits[-10:]}%"))
    if not conds:
        return []
    q = (db.session.query(Patient)
         .filter(Patient.org_id == org_id, Patient.active.is_(True), or_(*conds)))
    if exclude_id:
        q = q.filter(Patient.id != exclude_id)
    return q.order_by(Patient.created_at.desc()).limit(10).all()


# ------------------------------------------------------------------ validation
def parse_dob(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def validate(form: dict, *, org_id: int, patient_id: int | None = None) -> tuple[dict, list[str]]:
    """Check a folder form. Returns (cleaned values, list of plain-English errors).

    Deliberately strict about the four things that make a folder useful — who
    they are, their sex, how old they are, and somebody reachable in an
    emergency — and relaxed about everything else, because a busy desk should
    not be blocked by an unknown religion.
    """
    errors: list[str] = []
    v: dict = {}

    # Surnames are stored UPPERCASE, the way they are written on a paper folder.
    # Displaying "ABATAN" while exporting "Abatan" made the register and the
    # downloaded file disagree about the same patient.
    v["surname"] = (form.get("surname") or "").strip()[:80].upper()
    v["first_name"] = (form.get("first_name") or "").strip()[:80]
    v["other_names"] = (form.get("other_names") or "").strip()[:80]
    if not v["surname"]:
        errors.append("Surname is required.")
    if not v["first_name"]:
        errors.append("First name is required.")

    v["sex"] = (form.get("sex") or "").strip().upper()[:1]
    if v["sex"] not in ("F", "M"):
        errors.append("Please choose the patient's sex.")

    # Age: a real birthday if we have one, otherwise an honest stated age.
    dob = parse_dob(form.get("date_of_birth", ""))
    age_raw = (form.get("age_years") or "").strip()
    v["date_of_birth"] = dob
    v["age_years"] = None
    if form.get("date_of_birth") and not dob:
        errors.append("Could not read the date of birth. Use 1985-04-23 or 23/04/1985.")
    if dob:
        if dob > now_naive().date():
            errors.append("The date of birth is in the future.")
        elif (now_naive().date() - dob).days > 365 * 130:
            errors.append("That date of birth would make the patient over 130 years old.")
    elif age_raw:
        if not age_raw.isdigit() or not (0 <= int(age_raw) <= 130):
            errors.append("Age must be a whole number between 0 and 130.")
        else:
            v["age_years"] = int(age_raw)
    else:
        errors.append("Enter either a date of birth or the patient's age. "
                      "If the patient does not know their birthday, just enter the age.")

    v["marital_status"] = (form.get("marital_status") or "").strip()[:16]
    v["occupation"] = (form.get("occupation") or "").strip()[:80]
    v["religion"] = (form.get("religion") or "").strip()[:40]

    # Contact
    v["phone"] = clean_phone(form.get("phone", ""))
    if form.get("phone", "").strip() and not valid_phone(v["phone"]):
        errors.append("Enter a valid phone number, e.g. 08012345678.")
        v["phone"] = ""
    v["phone_alt"] = clean_phone(form.get("phone_alt", ""))
    if form.get("phone_alt", "").strip() and not valid_phone(v["phone_alt"]):
        errors.append("The second phone number is not valid.")
        v["phone_alt"] = ""
    v["address"] = (form.get("address") or "").strip()[:300]
    v["lga"] = (form.get("lga") or "").strip()[:80]
    v["state"] = (form.get("state") or "").strip()[:80]

    # Next of kin — somebody must be reachable in an emergency.
    v["nok_name"] = (form.get("nok_name") or "").strip()[:120]
    v["nok_relationship"] = (form.get("nok_relationship") or "").strip()[:40]
    v["nok_phone"] = clean_phone(form.get("nok_phone", ""))
    v["nok_address"] = (form.get("nok_address") or "").strip()[:300]
    if not v["nok_name"]:
        errors.append("Next of kin name is required — somebody must be reachable "
                      "in an emergency.")
    if not v["nok_phone"]:
        errors.append("Next of kin phone number is required.")
    elif not valid_phone(v["nok_phone"]):
        errors.append("The next of kin phone number is not valid.")

    # Payment route
    v["payer_type"] = (form.get("payer_type") or "SELF").strip().upper()
    if v["payer_type"] not in PAYER_CODES:
        v["payer_type"] = "SELF"
    v["payer_number"] = (form.get("payer_number") or "").strip()[:60]
    v["payer_name"] = (form.get("payer_name") or "").strip()[:120]
    if v["payer_type"] in ("LAHSMA", "NHIS", "HMO") and not v["payer_number"]:
        errors.append(f"A {v['payer_type']} patient needs their scheme/enrolment number, "
                      "otherwise Billing cannot claim.")

    # Clinical basics
    v["category"] = (form.get("category") or "GENERAL").strip().upper()
    if v["category"] not in CATEGORY_CODES:
        v["category"] = "GENERAL"
    v["blood_group"] = (form.get("blood_group") or "").strip().upper()[:4]
    v["genotype"] = (form.get("genotype") or "").strip().upper()[:4]
    if v["genotype"] and v["genotype"] not in GENOTYPES:
        errors.append(f"Genotype must be one of {', '.join(GENOTYPES)}.")
        v["genotype"] = ""
    v["allergies"] = (form.get("allergies") or "").strip()[:300]
    v["chronic_conditions"] = (form.get("chronic_conditions") or "").strip()[:300]
    v["notes"] = (form.get("notes") or "").strip()[:2000]

    # An under-12 is a child and an over-65 elderly, whatever the clerk picked —
    # Triage depends on this being right.
    age = v["age_years"] if v["age_years"] is not None else (
        (now_naive().date() - dob).days // 365 if dob else None)
    if age is not None and v["category"] == "GENERAL":
        if age < 12:
            v["category"] = "CHILD"
        elif age >= 65:
            v["category"] = "ELDERLY"

    return v, errors


# ------------------------------------------------------------------ visits
def open_visit(patient: Patient, *, user_id: int, reason: str = "",
               visit_type: str | None = None, department_id: int | None = None) -> PatientVisit:
    """Start an attendance for a folder and stamp the folder as seen today."""
    if not visit_type:
        visit_type = "NEW" if not patient.last_visit_at else "FOLLOW_UP"
    visit = PatientVisit(
        org_id=patient.org_id, patient_id=patient.id,
        visit_no=next_visit_no(patient.org_id), visit_type=visit_type,
        status="REGISTERED", reason=(reason or "").strip()[:300],
        payer_type=patient.payer_type, department_id=department_id,
        registered_by=user_id)
    db.session.add(visit)
    patient.last_visit_at = now_naive()
    return visit


def today_visits(org_id: int, status: str | None = None) -> list[PatientVisit]:
    start = datetime.combine(now_naive().date(), datetime.min.time())
    q = (db.session.query(PatientVisit)
         .filter(PatientVisit.org_id == org_id, PatientVisit.started_at >= start))
    if status:
        q = q.filter(PatientVisit.status == status)
    return q.order_by(PatientVisit.started_at.desc()).all()


def stats(org_id: int) -> dict:
    start = datetime.combine(now_naive().date(), datetime.min.time())
    return {
        "folders": db.session.query(func.count(Patient.id))
                     .filter(Patient.org_id == org_id, Patient.active.is_(True)).scalar() or 0,
        "new_today": db.session.query(func.count(Patient.id))
                       .filter(Patient.org_id == org_id,
                               Patient.created_at >= start).scalar() or 0,
        "visits_today": db.session.query(func.count(PatientVisit.id))
                          .filter(PatientVisit.org_id == org_id,
                                  PatientVisit.started_at >= start).scalar() or 0,
        "waiting_triage": db.session.query(func.count(PatientVisit.id))
                            .filter(PatientVisit.org_id == org_id,
                                    PatientVisit.started_at >= start,
                                    PatientVisit.status == "REGISTERED").scalar() or 0,
    }
