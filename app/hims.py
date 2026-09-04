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

from .models import (ASSISTANCE_CODES, CATEGORY_CODES, MARITAL_STATUSES,
                     PATIENT_LANG_LABELS,
                     PAYER_CODES, Patient, PatientVisit, db, new_code, now_naive)
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


def _lev(a: str, b: str) -> int:
    """Edit distance — tolerates 1-2 letter misspellings in HIMS search."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins = prev[j] + 1
            dele = cur[j-1] + 1
            sub = prev[j-1] + (0 if ca == cb else 1)
            cur.append(min(ins, dele, sub))
        prev = cur
    return prev[-1]


def _fuzzy_surname_matches(org_id: int, term: str, limit: int = 10) -> list:
    """Fallback: when exact LIKE finds nothing, look for close spellings.

    Real HIMS desks get "Abatan" typed as "Abathan" or "Ogunleye" as
    "Ogunlewe". A 1-2 letter edit distance catches those without needing
    PostgreSQL pg_trgm (not available on Render free).

    FIX 2026-09-04 (perf/privacy): old version loaded 500 full Patient rows
    (all columns, including PII like address, nok_phone) into Python memory
    per failed search, then ran Levenshtein per field in Python. At scale that
    is a privacy and egress risk (424 GB Supabase overage). New version:
      - pulls only needed columns (id, surname, first_name, hospital_number)
        as lightweight tuples, never full PII rows;
      - pre-filters by first 2 letters / length to cut candidate set from 500
        to ~50-100;
      - fetches full Patient objects only for the ~10 actual matches.
    """
    term_l = term.lower().strip()[:40]
    if len(term_l) < 3:
        return []
    from . import branches as br
    # Lightweight candidate fetch — no PII beyond names/number.
    # Include last_visit_at for recency ordering; branch filtering included.
    try:
        base_q = db.session.query(
            Patient.id, Patient.surname, Patient.first_name,
            Patient.hospital_number, Patient.last_visit_at
        ).filter(Patient.org_id == org_id, Patient.active.is_(True))
        base_q = br.apply_branch_filter(base_q, Patient.branch_id)
        # Narrow to plausible candidates: same first letter or first 2 chars.
        # This cuts typical scan from 500 to <100 without losing true typos
        # (edit distance 2 rarely changes first 2 letters).
        prefix = term_l[:2]
        # Use LIKE on surname prefix — indexed via ix_patient_org_surname
        candidates = (base_q.filter(
            or_(
                func.lower(Patient.surname).like(f"{prefix}%"),
                func.lower(Patient.first_name).like(f"{prefix}%"),
            )
        ).order_by(Patient.last_visit_at.desc().nullslast()).limit(200).all())
        # If prefix filter finds too few, broaden to length-similar set (still limited)
        if len(candidates) < 10:
            extra = (base_q.filter(
                func.length(Patient.surname).between(len(term_l)-2, len(term_l)+2)
            ).order_by(Patient.last_visit_at.desc().nullslast()).limit(100).all())
            # merge, deduplicate by id
            seen_ids = {c[0] for c in candidates}
            for e in extra:
                if e[0] not in seen_ids:
                    candidates.append(e)
                    seen_ids.add(e[0])
                    if len(candidates) >= 200:
                        break
    except Exception:
        # Fallback: small raw fetch without prefix filtering
        try:
            candidates = (db.session.query(
                Patient.id, Patient.surname, Patient.first_name,
                Patient.hospital_number, Patient.last_visit_at
            ).filter(Patient.org_id == org_id, Patient.active.is_(True))
            .order_by(Patient.last_visit_at.desc().nullslast()).limit(200).all())
        except Exception:
            return []
    scored_ids = []
    seen_ids = set()
    for pid, surname, first_name, hospital_number, _last in candidates:
        found = False
        for field in (surname, first_name, hospital_number):
            if not field:
                continue
            fl = field.lower()
            if abs(len(fl) - len(term_l)) > 2:
                # length filter already, but keep for safety
                continue
            if _lev(term_l, fl) <= 2 or _lev(term_l, fl[:len(term_l)]) <= 1:
                found = True
                break
            for part in fl.split():
                if _lev(term_l, part) <= 2:
                    found = True
                    break
            if found:
                break
        if found and pid not in seen_ids:
            scored_ids.append(pid)
            seen_ids.add(pid)
            if len(scored_ids) >= limit:
                break
    if not scored_ids:
        return []
    # Fetch full rows ONLY for the handful of matches — preserves caller contract
    # but avoids pulling 500 full PII rows per failed search.
    try:
        rows = db.session.query(Patient).filter(Patient.id.in_(scored_ids)).all()
        # Preserve scored order
        by_id = {r.id: r for r in rows}
        return [by_id[i] for i in scored_ids if i in by_id]
    except Exception:
        return []



def search(org_id: int, term: str, limit: int = MAX_SEARCH_RESULTS) -> list[Patient]:
    """Find a returning patient's folder.

    Clerks search by whatever the patient gives them: the folder number, a
    phone number, a surname, a first name, or all of it in one box. We accept
    every one of those rather than making them choose a field first.
    """
    term = (term or "").strip()
    if not term:
        return []
    from . import branches as br
    q = db.session.query(Patient).filter(Patient.org_id == org_id,
                                         Patient.active.is_(True))
    q = br.apply_branch_filter(q, Patient.branch_id)
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
    results = (q.filter(or_(*conds))
            .order_by(Patient.last_visit_at.desc().nullslast(), Patient.surname)
            .limit(limit).all())
    # If nothing found, try fuzzy matching for misspellings
    if not results and len(term) >= 3:
        try:
            results = _fuzzy_surname_matches(org_id, term, limit=limit)
        except Exception:
            results = []
    return results


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
    not be blocked by an unknown occupation.
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

    v["occupation"] = (form.get("occupation") or "").strip()[:80]

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
    # Language and assistance — how to look after them, not what is wrong with
    # them. This app is not a medical record.
    # G1 FIX: separate explicit consent for disability/assistance data (NDPA sensitive)
    lang = (form.get("preferred_lang") or "en").strip().lower()[:4]
    v["preferred_lang"] = lang if lang in PATIENT_LANG_LABELS else "en"
    picked = form.getlist("assistance") if hasattr(form, "getlist") else \
        [a for a in (form.get("assistance") or "").split(",") if a]
    assistance_str = ",".join(a for a in picked if a in ASSISTANCE_CODES)[:200]
    v["assistance"] = assistance_str
    # If assistance needs provided, require explicit consent checkbox
    assistance_consent = form.get("assistance_consent") or form.get("assistance_consent_at")
    if assistance_str and not assistance_consent:
        errors.append("Assistance needs (wheelchair, hearing, etc.) are sensitive — please tick the separate consent box for disability assistance data.")
    v["assistance_consent_at"] = now_naive() if assistance_consent else None
    # General consent timestamp for patient data (NDPA)
    v["consent_at"] = now_naive()
    v["care_note"] = (form.get("care_note") or "").strip()[:200]
    v["notes"] = (form.get("notes") or "").strip()[:2000]

    # Demographic details from the hospital's paper admission form, carried
    # through from Reception so nothing the patient already answered is lost.
    marital = (form.get("marital_status") or "").strip()[:16]
    v["marital_status"] = marital if marital in MARITAL_STATUSES else None
    v["religion"] = (form.get("religion") or "").strip()[:40] or None
    v["state_of_origin"] = (form.get("state_of_origin") or "").strip()[:60] or None
    v["town"] = (form.get("town") or "").strip()[:80] or None
    v["tribe"] = (form.get("tribe") or "").strip()[:60] or None
    v["ethnic_group"] = (form.get("ethnic_group") or "").strip()[:60] or None

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
               visit_type: str | None = None, department_id: int | None = None,
               is_fast_track: bool = False, fast_track_reason: str | None = None) -> PatientVisit:
    """Start an attendance for a folder and stamp the folder as seen today."""
    if not visit_type:
        visit_type = "NEW" if not patient.last_visit_at else "FOLLOW_UP"
    # Auto-detect fast-track from patient age / assistance if not passed explicitly
    if not is_fast_track:
        try:
            age = patient.age
            if age is not None and age >= 60:
                is_fast_track = True
                fast_track_reason = fast_track_reason or "ELDERLY"
            elif age is not None and age <= 5:
                is_fast_track = True
                fast_track_reason = fast_track_reason or "CHILD"
            elif patient.assistance and "WHEELCHAIR" in patient.assistance:
                is_fast_track = True
                fast_track_reason = fast_track_reason or "WHEELCHAIR"
            elif patient.assistance and "PREGNANT" in patient.assistance:
                is_fast_track = True
                fast_track_reason = fast_track_reason or "PREGNANT"
        except Exception:
            pass
    branch_id = getattr(patient, "branch_id", None)
    if not branch_id:
        try:
            from flask_login import current_user
            branch_id = getattr(current_user, "branch_id", None)
        except Exception:
            branch_id = None
    visit = PatientVisit(
        org_id=patient.org_id, patient_id=patient.id,
        visit_no=next_visit_no(patient.org_id), visit_type=visit_type,
        status="REGISTERED", reason=(reason or "").strip()[:300],
        payer_type=patient.payer_type, department_id=department_id,
        registered_by=user_id, branch_id=branch_id,
        is_fast_track=bool(is_fast_track),
        fast_track_reason=(fast_track_reason or None))
    db.session.add(visit)
    patient.last_visit_at = now_naive()
    return visit


def today_visits(org_id: int, status: str | None = None) -> list[PatientVisit]:
    start = datetime.combine(now_naive().date(), datetime.min.time())
    from . import branches as br
    q = (db.session.query(PatientVisit)
         .filter(PatientVisit.org_id == org_id, PatientVisit.started_at >= start))
    q = br.apply_branch_filter(q, PatientVisit.branch_id)
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
