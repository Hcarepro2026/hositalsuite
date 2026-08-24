"""Places a patient actually visits — not the whole hospital organogram.

The public pickers (queue, book, feedback, complaint) used to dump every
department: Laundry, Internal Audit, Store, ICT. A patient cannot join
those queues. If a list is shown at all, it is the clinical / patient
services plus Fast Track (which is a real department, first in the list).
"""
from __future__ import annotations

from .models import Department, db

FAST_TRACK_NAME = "Fast Track"

# Hide back-office / support names even if they also contain a clinical word.
_DENY = (
    "laundry",
    "internal audit",
    "audit unit",
    "store unit",
    "procurement",
    "finance",
    "accounts",
    "planning, research",
    "public affairs",
    "ict",
    "engineering",
    "maintenance",
    "environmental health",
    "catering",
    "security",
    "mortuary",
    "administration",
    "human resource",
    "health information",
    "hims",
    "nursing services",
)

# Names a patient can reasonably pick.
_ALLOW = (
    "fast track",
    "accident",
    "emergency",
    "a&e",
    "family medicine",
    "outpatient",
    "gopd",
    "internal medicine",
    "surgery",
    "theatre",
    "theater",
    "obstetric",
    "gynaec",
    "gynec",
    "antenatal",
    "labour",
    "paediat",
    "pediatr",
    "dental",
    "ophthal",
    "eye clinic",
    "ear, nose",
    "orthop",
    "physio",
    "mental health",
    "psychiatr",
    "laborat",
    "radiolog",
    "imaging",
    "pharmacy",
    "public health",
    "immunis",
    "nutrition",
    "dietetic",
    "triage",
)

_ALLOW_EXACT = frozenset({
    "ent", "eye", "lab", "opd", "anc", "a&e", "gopd", "fast track",
})


def is_fast_track_dept(dept: Department | None) -> bool:
    if dept is None:
        return False
    return (dept.name or "").strip().lower() == FAST_TRACK_NAME.lower()


def is_patient_place(name: str | None) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return False
    if any(bad in n for bad in _DENY):
        return False
    if n in _ALLOW_EXACT:
        return True
    return any(ok in n for ok in _ALLOW)


def ensure_fast_track(org_id: int) -> Department:
    """Create the Fast Track department for this hospital if it is missing."""
    existing = (db.session.query(Department)
                .filter(Department.org_id == org_id,
                        Department.name.ilike(FAST_TRACK_NAME))
                .first())
    if existing:
        if not existing.active:
            existing.active = True
        return existing
    row = Department(org_id=org_id, name=FAST_TRACK_NAME, active=True)
    db.session.add(row)
    db.session.flush()
    return row


def public_departments(org_id: int) -> list[Department]:
    """Short list for patient pickers. Fast Track is always first."""
    ensure_fast_track(org_id)
    rows = (db.session.query(Department)
            .filter_by(org_id=org_id, active=True)
            .order_by(Department.name)
            .all())
    places = [d for d in rows if is_patient_place(d.name)]
    gold = [d for d in places if is_fast_track_dept(d)]
    rest = [d for d in places if not is_fast_track_dept(d)]
    return gold + rest
