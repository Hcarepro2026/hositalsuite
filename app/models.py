"""Database models — multi-tenant (every record carries org_id)."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

# Roles, in seniority order. Labels are what staff actually see in the UI.
ROLES = ("SUPER_ADMIN", "MD_CEO", "DMD", "DCST", "APEX_NURSE", "HEAD_ADMIN_HR",
         "ADMIN_MANAGER", "HOD")

ROLE_LABELS = {
    "SUPER_ADMIN":   "Super Administrator",
    "MD_CEO":        "MD / CEO",
    "DMD":           "DMD — Deputy Medical Director",
    "DCST":          "DCST — Director of Clinical Services & Training",
    "APEX_NURSE":    "APEX Nurse — Head of Nursing Services",
    "HEAD_ADMIN_HR": "Head of Admin & HR",
    "ADMIN_MANAGER": "Admin Manager",
    "HOD":           "HOD — Head of Department",
}

# Roles with hospital-wide management sight (dashboards, reports, escalation targets).
MANAGEMENT_ROLES = ("SUPER_ADMIN", "MD_CEO", "DMD", "DCST", "APEX_NURSE", "HEAD_ADMIN_HR")


def role_label(code: str) -> str:
    return ROLE_LABELS.get(code, code)

INSPECTION_STATUSES = ("DRAFT", "SUBMITTED", "AMENDED", "SUPERSEDED")
COMPLAINT_STATUSES = ("NEW", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "CLOSED", "ESCALATED")
CA_STATUSES = ("OPEN", "IN_PROGRESS", "COMPLETED", "OVERDUE", "VERIFIED")


# ---------------------------------------------------------------- helpers
def new_code(n: int = 10) -> str:
    return secrets.token_hex(n)[:n].upper()


def now_naive() -> datetime:
    """Current time as naive local (deployment timezone) datetime."""
    from flask import current_app
    try:
        tz = current_app.config["TIMEZONE"]
    except Exception:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Africa/Lagos")
    return datetime.now(tz).replace(tzinfo=None)


# ---------------------------------------------------------------- tenants
class StoredFile(db.Model):
    """Durable binary storage (see app/storage.py).

    Cheap hosts wipe the container disk on every restart, so uploads, generated
    PDFs and the hospital logo live here instead of on the filesystem.
    """
    __tablename__ = "stored_file"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(300), unique=True, nullable=False, index=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), index=True)
    folder = db.Column(db.String(40), index=True)
    filename = db.Column(db.String(200))
    content_type = db.Column(db.String(80))
    size = db.Column(db.Integer, default=0)
    sha256 = db.Column(db.String(64))
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, default=now_naive, index=True)


class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(12), unique=True, nullable=False)       # e.g. HOSP
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(40), unique=True, index=True)   # public-portal tenant key
    logo_path = db.Column(db.String(300))
    email = db.Column(db.String(160))
    phone = db.Column(db.String(32))
    phone_alt = db.Column(db.String(32))
    address = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=now_naive)


# ---------------------------------------------------------------- users
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160))
    phone = db.Column(db.String(32))            # E.164, used for WhatsApp/SMS
    role = db.Column(db.String(20), nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    must_change_password = db.Column(db.Boolean, default=False)
    # Which department this member of staff belongs to (bulk uploads, rosters,
    # and "who works where" reporting all need this).
    # use_alter: user->department and department->user reference each other, so
    # the FK is added after both tables exist rather than creating a cycle.
    department_id = db.Column(
        db.Integer,
        db.ForeignKey("department.id", use_alter=True, name="fk_user_department"),
        index=True)
    # Account approval: bulk-uploaded/self-registered accounts start unapproved
    # and cannot sign in until an administrator approves them.
    approved = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now_naive)
    last_login_at = db.Column(db.DateTime)

    org = db.relationship("Organization", backref="users")
    department = db.relationship("Department", foreign_keys=[department_id])

    @property
    def is_super(self): return self.role == "SUPER_ADMIN"
    @property
    def is_md(self): return self.role == "MD_CEO"
    @property
    def is_am(self): return self.role == "ADMIN_MANAGER"
    @property
    def is_hod(self): return self.role == "HOD"

    @property
    def is_management(self):
        """Executive sight: MD/CEO, DMD, DCST, APEX Nurse, Head of Admin & HR.

        These roles see the hospital-wide dashboard and are valid escalation
        targets, without being able to administer the system itself.
        """
        return self.role in MANAGEMENT_ROLES

    @property
    def role_name(self):
        return role_label(self.role)

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw, method="scrypt")

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    def get_id(self):  # flask-login
        return str(self.id)


# ---------------------------------------------------------------- structure
class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    hod_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    # HOD contact recorded ON the department, so a department can have a named
    # head who is not (yet) a system user — and so the phone survives even if
    # the linked staff account is changed or deactivated.
    hod_name = db.Column(db.String(120))
    hod_phone = db.Column(db.String(32))
    active = db.Column(db.Boolean, default=True, nullable=False)
    # roster design for this department: two 12h shifts/day, or one 24h shift/day
    roster_mode = db.Column(db.String(10), default="two_12h")      # two_12h | 24h
    roster_staff_per_shift = db.Column(db.Integer, default=1)      # 1 or 2 on duty per shift
    sections = db.relationship("Section", backref="department", lazy="select",
                               cascade="all, delete-orphan", order_by="Section.name")
    hod = db.relationship("User", foreign_keys=[hod_user_id])
    __table_args__ = (db.UniqueConstraint("org_id", "name", name="uq_dept_org_name"),)


class Section(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    hod_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    units = db.relationship("Unit", backref="section", lazy="select",
                            cascade="all, delete-orphan", order_by="Unit.name")
    hod = db.relationship("User", foreign_keys=[hod_user_id])


class Unit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), nullable=False, index=True)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    hod_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    hod = db.relationship("User", foreign_keys=[hod_user_id])


# ---------------------------------------------------------------- roster
class DutyRoster(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    duty_date = db.Column(db.Date, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    source = db.Column(db.String(16), default="manual")   # manual | import
    note = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=now_naive)
    user = db.relationship("User", foreign_keys=[user_id], backref="duties")
    __table_args__ = (db.UniqueConstraint("org_id", "duty_date", name="uq_roster_org_date"),)


# ---------------------------------------------------------------- inspections
class Inspection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    ref = db.Column(db.String(40), unique=True, nullable=False)
    verify_code = db.Column(db.String(24), unique=True, nullable=False, index=True)
    inspector_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    duty_date = db.Column(db.Date, nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), nullable=False, index=True)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"))
    unit_id = db.Column(db.Integer, db.ForeignKey("unit.id"))
    status = db.Column(db.String(16), default="DRAFT", nullable=False, index=True)
    started_at = db.Column(db.DateTime, default=now_naive)
    submitted_at = db.Column(db.DateTime)
    total_score = db.Column(db.Integer)
    percent = db.Column(db.Float)
    rating = db.Column(db.String(30))
    critical_count = db.Column(db.Integer, default=0)
    poor_count = db.Column(db.Integer, default=0)
    gps_mode = db.Column(db.String(12))             # mandatory | optional | disabled
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    gps_captured = db.Column(db.Boolean, default=False)
    device_info = db.Column(db.String(300))
    # Admin Manager's overall closing remark for the whole inspection (distinct
    # from the per-criterion explanations). Appears on the PDF sent to MD/CEO.
    final_comment = db.Column(db.Text)
    amendment_of_id = db.Column(db.Integer, db.ForeignKey("inspection.id"))
    pdf_path = db.Column(db.String(300))
    scores = db.relationship("InspectionScore", backref="inspection", cascade="all, delete-orphan",
                             order_by="InspectionScore.criterion_no")
    inspector = db.relationship("User", foreign_keys=[inspector_id])
    department = db.relationship("Department")
    section = db.relationship("Section")
    unit = db.relationship("Unit")


class InspectionScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspection.id"), nullable=False, index=True)
    criterion_no = db.Column(db.Integer, nullable=False)      # 1..5 exactly
    score = db.Column(db.Integer, nullable=False)             # 1..5
    explanation = db.Column(db.Text)                          # mandatory when score <= 2
    evidence_path = db.Column(db.String(300))
    __table_args__ = (db.UniqueConstraint("inspection_id", "criterion_no", name="uq_insp_crit"),)


# ---------------------------------------------------------------- complaints
class ComplaintCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)


class QrLocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)          # Reception, Ward A ...
    code = db.Column(db.String(24), unique=True, nullable=False)


class Complaint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    ref = db.Column(db.String(40), unique=True, nullable=False)
    idempotency_key = db.Column(db.String(40), index=True)   # duplicate-submission guard (§41)
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), nullable=False, index=True)
    category = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(32), nullable=False)
    contact_method = db.Column(db.String(20), default="phone")   # phone | whatsapp | either
    attachment_path = db.Column(db.String(300))
    is_anonymous = db.Column(db.Boolean, default=False, nullable=False)
    consent_at = db.Column(db.DateTime)          # NDPA: when the patient agreed
    anonymized_at = db.Column(db.DateTime)       # retention purge / erasure request
    source = db.Column(db.String(12), default="link")            # qr | link | ussd
    qr_location_id = db.Column(db.Integer, db.ForeignKey("qr_location.id"))
    status = db.Column(db.String(16), default="NEW", nullable=False, index=True)
    submitted_at = db.Column(db.DateTime, default=now_naive, index=True)
    acknowledged_at = db.Column(db.DateTime)
    resolved_at = db.Column(db.DateTime)
    escalated_at = db.Column(db.DateTime)
    sla_hours = db.Column(db.Integer, nullable=False)
    sla_deadline_at = db.Column(db.DateTime, nullable=False, index=True)
    sla_extended_at = db.Column(db.DateTime)
    action_taken = db.Column(db.Text)
    resolution_notes = db.Column(db.Text)
    escalated = db.Column(db.Boolean, default=False, nullable=False)
    department = db.relationship("Department")
    qr_location = db.relationship("QrLocation")
    history = db.relationship("ComplaintStatusHistory", backref="complaint",
                              cascade="all, delete-orphan", order_by="ComplaintStatusHistory.at")

    @property
    def sla_breached(self) -> bool:
        return self.escalated or (self.status not in ("RESOLVED", "CLOSED") and self.sla_deadline_at < now_naive())


class ComplaintStatusHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaint.id"), nullable=False, index=True)
    from_status = db.Column(db.String(16))
    to_status = db.Column(db.String(16), nullable=False)
    note = db.Column(db.Text)
    patient_message = db.Column(db.String(480))   # shown to the patient (status page)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    at = db.Column(db.DateTime, default=now_naive)
    user = db.relationship("User")


# ---------------------------------------------------------------- department rosters
DEPT_SHIFTS = {
    "two_12h": [("DAY", "07:00–19:00"), ("NIGHT", "19:00–07:00")],
    "24h": [("24H", "07:00–07:00 (+1)")],
    # Administrative departments (procurement, audit, finance & accounts, ICT,
    # admin/HR ...) do not run shifts — they work office hours, Monday to Friday.
    "office": [("OFFICE", "08:00–16:00, Mon–Fri")],
    # Three 8-hour tours: the other pattern Nigerian nursing divisions use.
    "three_8h": [("MORNING", "07:00–14:00"), ("AFTERNOON", "14:00–21:00"),
                 ("NIGHT", "21:00–07:00")],
}

ROSTER_MODE_LABELS = {
    "two_12h": "Two 12-hour shifts per day (day / night)",
    "24h": "One 24-hour duty per day",
    "office": "Office hours, Monday to Friday (no shifts)",
    "three_8h": "Three 8-hour shifts per day (morning / afternoon / night)",
}

# Every shift code the system understands, in one flat set — used for validation
# of uploaded files before we know which department a row belongs to.
ALL_SHIFT_CODES = tuple(sorted({s[0] for shifts in DEPT_SHIFTS.values() for s in shifts}))

# Leave is part of the roster, not a separate register: if a nurse is on annual
# leave on Tuesday, the Tuesday roster must SAY so, otherwise someone rosters her.
LEAVE_TYPES = (
    ("ANNUAL", "Annual leave"),
    ("CASUAL", "Casual leave"),
    ("SICK", "Sick leave"),
    ("STUDY", "Study leave"),
    ("MATERNITY", "Maternity leave"),
    ("COMPASSIONATE", "Compassionate leave"),
    ("EXAM", "Examination leave"),
    ("OFF", "Off duty"),
)
LEAVE_CODES = tuple(c for c, _ in LEAVE_TYPES)
LEAVE_LABELS = dict(LEAVE_TYPES)

# Who owns a roster line. ORG = the hospital-wide Admin Manager duty roster.
ROSTER_SCOPES = ("ORG", "DEPARTMENT", "SECTION", "UNIT")
SCOPE_LABELS = {"ORG": "Admin Manager (hospital-wide)", "DEPARTMENT": "Department",
                "SECTION": "Section", "UNIT": "Unit"}

# Placeholder shift code stored on leave rows so the uniqueness constraint works
# on both SQLite and PostgreSQL (NULLs never collide in a UNIQUE index).
LEAVE_SHIFT = "LEAVE"


class DeptRosterEntry(db.Model):
    """LEGACY department roster (two staff columns, department only).

    Superseded by :class:`RosterEntry`, which holds one row per person and can
    also carry sections, units and leave. Kept so that no historical data is
    lost; migrated into RosterEntry once at boot by
    ``app.rosterdata.migrate_legacy_entries``.
    """
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), nullable=False, index=True)
    duty_date = db.Column(db.Date, nullable=False, index=True)
    shift = db.Column(db.String(6), nullable=False)              # DAY | NIGHT | 24H
    staff1_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    staff2_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    source = db.Column(db.String(16), default="manual")
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=now_naive)
    department = db.relationship("Department")
    staff1 = db.relationship("User", foreign_keys=[staff1_user_id])
    staff2 = db.relationship("User", foreign_keys=[staff2_user_id])
    __table_args__ = (db.UniqueConstraint("department_id", "duty_date", "shift",
                                          name="uq_dept_roster_day_shift"),)


class RosterEntry(db.Model):
    """ONE unified roster line: one person, one day, one shift — or one leave day.

    WHY ONE TABLE
    -------------
    The suite used to have two rosters that could not see each other: the
    hospital-wide Admin Manager duty roster (`duty_roster`) and a department
    roster (`dept_roster_entry`) with two fixed staff columns. That design made
    three ordinary things impossible:

      * rostering a SECTION or a UNIT, not just a whole department;
      * putting more than two people on a shift;
      * recording that somebody is on leave, so the roster itself warns you
        before you place them on duty.

    One row per person fixes all three. A ward with nine nurses on nights is
    nine rows, not "staff1 and staff2 and nowhere to put the rest".

    LEAVE
    -----
    A leave row has ``kind='LEAVE'``, a ``leave_type`` and ``shift='LEAVE'``.
    Leave can span days, so a single upload row may expand into one entry per
    calendar day; that keeps every "who is on duty on 14 September" query a
    plain date lookup with no range arithmetic.
    """
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    duty_date = db.Column(db.Date, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    # DUTY (on the roster, working) or LEAVE (on the roster, NOT working)
    kind = db.Column(db.String(8), nullable=False, default="DUTY", index=True)
    shift = db.Column(db.String(12), nullable=False, default="DAY")
    leave_type = db.Column(db.String(16))                       # ANNUAL | SICK | ...

    # Ownership: ORG for the hospital-wide Admin Manager roster, otherwise the
    # department (and optionally the section / unit inside it).
    scope = db.Column(db.String(12), nullable=False, default="DEPARTMENT", index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), index=True)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("unit.id"), index=True)

    note = db.Column(db.String(200))
    source = db.Column(db.String(16), default="manual")         # manual | import | legacy
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=now_naive)

    user = db.relationship("User", foreign_keys=[user_id])
    department = db.relationship("Department")
    section = db.relationship("Section")
    unit = db.relationship("Unit")

    # The same person cannot be placed twice on the same day+shift in the same
    # place. Enforced in the database, not only in Python, so a double-submitted
    # form or two admins uploading the same file cannot create a duplicate.
    __table_args__ = (
        db.UniqueConstraint("org_id", "duty_date", "user_id", "shift", "scope",
                            "department_id", "section_id", "unit_id",
                            name="uq_roster_entry_slot"),
        db.Index("ix_roster_entry_org_date", "org_id", "duty_date"),
    )

    @property
    def place_label(self) -> str:
        if self.scope == "ORG":
            return "Hospital-wide (Admin Manager)"
        bits = [self.department.name if self.department else "—"]
        if self.section:
            bits.append(self.section.name)
        if self.unit:
            bits.append(self.unit.name)
        return " › ".join(bits)

    @property
    def is_leave(self) -> bool:
        return self.kind == "LEAVE"

    @property
    def display_shift(self) -> str:
        if self.is_leave:
            return LEAVE_LABELS.get(self.leave_type or "", "Leave")
        return self.shift


# ---------------------------------------------------------------- bookings
APPOINTMENT_STATUSES = ("BOOKED", "ARRIVED", "CANCELLED", "NO_SHOW")


class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    ref = db.Column(db.String(40), unique=True, nullable=False)
    idempotency_key = db.Column(db.String(40), index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), nullable=False, index=True)
    appointment_date = db.Column(db.Date, nullable=False, index=True)
    appointment_time = db.Column(db.String(5), nullable=False, index=True)   # "HH:MM" slot
    patient_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(32), nullable=False)
    status = db.Column(db.String(12), default="BOOKED", nullable=False, index=True)
    source = db.Column(db.String(12), default="link")       # qr | link | ussd | staff | referral
    qr_location_id = db.Column(db.Integer, db.ForeignKey("qr_location.id"))
    referral_id = db.Column(db.Integer, index=True)         # inbound: which share-link brought this booking
    is_repeat = db.Column(db.Boolean, default=False, nullable=False)  # same phone booked before
    consent_at = db.Column(db.DateTime)
    anonymized_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now_naive)
    arrived_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    department = db.relationship("Department")
    qr_location = db.relationship("QrLocation")


# ---------------------------------------------------------------- patient feedback (§7)
class PatientFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), index=True)
    rating = db.Column(db.Integer, nullable=False, index=True)     # 1..5
    comment = db.Column(db.Text)
    phone = db.Column(db.String(32))
    source = db.Column(db.String(12), default="link")
    status = db.Column(db.String(12), default="NEW", index=True)   # NEW | ROUTED
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaint.id"))
    referral_id = db.Column(db.Integer, index=True)         # inbound: arrived via a share-link
    consent_at = db.Column(db.DateTime)
    anonymized_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now_naive)
    department = db.relationship("Department")
    complaint = db.relationship("Complaint")


# ---------------------------------------------------------------- queue (§6)
QUEUE_STATUSES = ("WAITING", "CALLED", "DONE", "NO_SHOW", "CANCELLED")


class QueueTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    code = db.Column(db.String(20), nullable=False, index=True)   # public display e.g. "E-014"
    access_key = db.Column(db.String(24), unique=True, index=True)  # private status lookup
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), nullable=False, index=True)
    queue_date = db.Column(db.Date, nullable=False, index=True)
    patient_name = db.Column(db.String(120))        # staff-only; never shown on public screens
    phone = db.Column(db.String(32))
    status = db.Column(db.String(12), default="WAITING", nullable=False, index=True)
    source = db.Column(db.String(12), default="link")   # qr | link | booking | ussd
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointment.id"))
    anonymized_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now_naive)
    called_at = db.Column(db.DateTime)
    served_at = db.Column(db.DateTime)
    department = db.relationship("Department")
    appointment = db.relationship("Appointment")


# ---------------------------------------------------------------- referrals (§14)
REFERRAL_KINDS = ("patient", "hospital", "staff")
REFERRAL_SOURCES = ("feedback", "booking", "staff", "poster", "link")
REFERRAL_EVENT_KINDS = ("click", "book", "feedback", "queue")


class Referral(db.Model):
    """A shareable, trackable link/QR. No prizes, no pressure — just attribution."""
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    code = db.Column(db.String(16), unique=True, nullable=False, index=True)
    kind = db.Column(db.String(12), default="patient", nullable=False)   # patient | hospital | staff
    source = db.Column(db.String(12), default="link")                    # feedback | booking | staff | poster | link
    feedback_id = db.Column(db.Integer, db.ForeignKey("patient_feedback.id"))
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointment.id"))
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"))
    referrer_name = db.Column(db.String(120))
    referrer_phone = db.Column(db.String(32))
    note = db.Column(db.String(200))                       # staff label, e.g. "Ward A poster"
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now_naive)
    last_clicked_at = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    department = db.relationship("Department")
    origin_feedback = db.relationship("PatientFeedback", foreign_keys=[feedback_id])


class ReferralEvent(db.Model):
    """One row per click / booking / feedback / queue join attributed to a code."""
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    referral_id = db.Column(db.Integer, db.ForeignKey("referral.id"), nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False, index=True)   # click | book | feedback | queue
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointment.id"))
    feedback_id = db.Column(db.Integer, db.ForeignKey("patient_feedback.id"))
    created_at = db.Column(db.DateTime, default=now_naive, index=True)
    referral = db.relationship("Referral", backref="events")


# ---------------------------------------------------------------- SMS delivery
class SmsMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    to_number = db.Column(db.String(32), nullable=False)
    body = db.Column(db.String(480), nullable=False)
    kind = db.Column(db.String(30), nullable=False)          # confirmation | reminder | alert
    entity_type = db.Column(db.String(20))
    entity_id = db.Column(db.Integer)
    provider = db.Column(db.String(16))                      # sandbox | termii | twilio
    status = db.Column(db.String(12), default="QUEUED", index=True)  # QUEUED|SENT|FAILED
    provider_id = db.Column(db.String(80))
    attempts = db.Column(db.Integer, default=0)
    last_error = db.Column(db.String(400))
    created_at = db.Column(db.DateTime, default=now_naive)
    sent_at = db.Column(db.DateTime)


# ---------------------------------------------------------------- corrective actions
class CorrectiveAction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    source_type = db.Column(db.String(16), nullable=False)     # inspection | complaint
    source_id = db.Column(db.Integer, nullable=False)
    finding = db.Column(db.Text, nullable=False)
    action_required = db.Column(db.Text, nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    deadline = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(16), default="OPEN", nullable=False, index=True)
    completed_at = db.Column(db.DateTime)
    evidence_path = db.Column(db.String(300))
    verified_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    verified_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now_naive)
    owner = db.relationship("User", foreign_keys=[owner_id])
    verified_by = db.relationship("User", foreign_keys=[verified_by_id])


# ---------------------------------------------------------------- notifications
class AppNotification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    channel = db.Column(db.String(12), nullable=False)          # inapp | email | whatsapp | sms
    template_key = db.Column(db.String(60), nullable=False)
    subject = db.Column(db.String(200))
    body = db.Column(db.Text, nullable=False)
    entity_type = db.Column(db.String(20))
    entity_id = db.Column(db.Integer)
    status = db.Column(db.String(12), default="SENT")           # SENT | FAILED | READ
    error = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=now_naive, index=True)


class WhatsAppMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    to_number = db.Column(db.String(32), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    kind = db.Column(db.String(30), nullable=False)             # report | reminder | alert
    body = db.Column(db.Text, nullable=False)
    media_path = db.Column(db.String(300))
    entity_type = db.Column(db.String(20))
    entity_id = db.Column(db.Integer)
    status = db.Column(db.String(12), default="QUEUED", index=True)  # QUEUED|SENDING|SENT|DELIVERED|FAILED
    provider_id = db.Column(db.String(80))
    attempts = db.Column(db.Integer, default=0)
    last_error = db.Column(db.String(400))
    created_at = db.Column(db.DateTime, default=now_naive)
    sent_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)


# ---------------------------------------------------------------- reports & files
class ReportFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    kind = db.Column(db.String(30), nullable=False)             # inspection | daily | weekly | monthly | dept | complaints | escalation | ca | compliance
    title = db.Column(db.String(200), nullable=False)
    entity_type = db.Column(db.String(20))
    entity_id = db.Column(db.Integer)
    path = db.Column(db.String(300), nullable=False)
    verify_code = db.Column(db.String(24), unique=True, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=now_naive)


# ---------------------------------------------------------------- audit
class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    action = db.Column(db.String(60), nullable=False, index=True)
    entity_type = db.Column(db.String(30))
    entity_id = db.Column(db.Integer)
    detail = db.Column(db.Text)                                 # JSON {old,new,...}
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(250))
    at = db.Column(db.DateTime, default=now_naive, index=True)
    prev_hash = db.Column(db.String(64))
    hash = db.Column(db.String(64), nullable=False)

    user = db.relationship("User")

    @staticmethod
    def chain_hash(prev: str, org_id, user_id, action, entity_type, entity_id, detail, at) -> str:
        payload = json.dumps([prev, org_id, user_id, action, entity_type, entity_id, detail, str(at)],
                             default=str, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- chatbot knowledge base (§SaaS)
KB_STATUSES = ("approved", "pending", "rejected")


class KnowledgeArticle(db.Model):
    """Multi-tenant dialogue library.

    org_id NULL  -> global master library (shared by every tenant)
    org_id set   -> tenant-specific dialogue; status 'pending' until approved.
    Learning loop: unanswered chats + thumbs feed reports; admins may promote a
    good tenant answer to the global master (with approval).
    """
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), index=True)  # NULL = global
    category = db.Column(db.String(40), nullable=False, index=True)
    intent = db.Column(db.String(60), nullable=False, index=True)
    keywords = db.Column(db.Text, nullable=False)          # newline/comma-separated triggers
    en = db.Column(db.Text, nullable=False)                # premium English
    pidgin = db.Column(db.Text)                            # Nigerian Pidgin
    yo = db.Column(db.Text)
    ha = db.Column(db.Text)
    ig = db.Column(db.Text)
    cta = db.Column(db.String(200))                        # soft call-to-action
    clinical_safe = db.Column(db.Boolean, default=True)    # False = refuse/redirect template
    scope = db.Column(db.String(8), default="global")      # global | tenant
    status = db.Column(db.String(10), default="approved", index=True)
    submitted_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    approved_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    hit_count = db.Column(db.Integer, default=0)
    thumbs_up = db.Column(db.Integer, default=0)
    thumbs_down = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=now_naive)
    updated_at = db.Column(db.DateTime, default=now_naive, onupdate=now_naive)


class ChatSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), index=True)
    lang = db.Column(db.String(4), default="en")
    channel = db.Column(db.String(12), default="web")       # web | whatsapp
    started_at = db.Column(db.DateTime, default=now_naive)
    ended_at = db.Column(db.DateTime)
    handed_off = db.Column(db.Boolean, default=False)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("chat_session.id"), index=True)
    role = db.Column(db.String(8), nullable=False)          # user | bot
    text = db.Column(db.Text, nullable=False)
    intent = db.Column(db.String(60))
    confidence = db.Column(db.Float)
    article_id = db.Column(db.Integer, db.ForeignKey("knowledge_article.id"))
    unanswered = db.Column(db.Boolean, default=False)
    at = db.Column(db.DateTime, default=now_naive)


class ChatFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("chat_message.id"), index=True)
    article_id = db.Column(db.Integer, db.ForeignKey("knowledge_article.id"))
    rating = db.Column(db.String(4), nullable=False)        # up | down
    at = db.Column(db.DateTime, default=now_naive)


# ---------------------------------------------------------------- self-service password reset
class PasswordReset(db.Model):
    """Single-use, short-lived OTP for self-service 'forgot password' (§burden off admin)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    otp_hash = db.Column(db.String(256), nullable=False)
    channel = db.Column(db.String(12), default="sms")            # sms | email
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    used_at = db.Column(db.DateTime)
    attempts = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=now_naive)
    user = db.relationship("User")


# ---------------------------------------------------------------- brute-force defence
class LoginAttempt(db.Model):
    """Per-username failed-login counter driving temporary account lockout.

    The IP-based rate limiter cannot protect an account when every request
    arrives from the same proxy IP, and it also cannot stop a slow distributed
    guess. This adds a second, account-scoped gate.
    """
    __tablename__ = "login_attempt"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    failures = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, index=True)
    last_failure_at = db.Column(db.DateTime)
    last_ip = db.Column(db.String(64))


# ---------------------------------------------------------------- NDPA data-subject requests
class DataRequest(db.Model):
    """Patient request to access or erase their data (NDPA 2023 rights)."""
    __tablename__ = "data_request"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    ref = db.Column(db.String(40), unique=True, nullable=False)
    kind = db.Column(db.String(12), nullable=False)          # access | erase
    phone = db.Column(db.String(32), nullable=False, index=True)
    note = db.Column(db.Text)
    status = db.Column(db.String(16), default="NEW", nullable=False, index=True)  # NEW|DONE|REJECTED
    created_at = db.Column(db.DateTime, default=now_naive, index=True)
    handled_at = db.Column(db.DateTime)
    handled_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    outcome = db.Column(db.Text)


# ---------------------------------------------------------------- user prefs (§19)
class UserPref(db.Model):
    """Per-user alert preferences: voice reminders, quiet hours, browser push."""
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)
    key = db.Column(db.String(40), primary_key=True)
    value = db.Column(db.Text)

    DEFAULTS = {
        "voice_enabled": True,
        "voice_min_level": "standard",   # standard | urgent | emergency
        # Quiet hours OFF by default. They used to default to 22:00-07:00,
        # which silenced every announcement for night-shift staff — precisely
        # the people who most need to hear that a patient is waiting. Staff can
        # switch quiet hours on themselves at /alert-settings.
        "quiet_start": "",
        "quiet_end": "",
        "push_enabled": False,
    }

    @staticmethod
    def get(user_id: int, key: str):
        row = db.session.get(UserPref, (user_id, key))
        if row is not None:
            return row.value
        d = UserPref.DEFAULTS.get(key)
        if isinstance(d, bool):
            return d
        return d

    @staticmethod
    def set(user_id: int, key: str, value):
        row = db.session.get(UserPref, (user_id, key))
        if row is None:
            row = UserPref(user_id=user_id, key=key)
            db.session.add(row)
        row.value = str(value)

    @staticmethod
    def bundle(user_id: int) -> dict:
        out = {}
        for k, d in UserPref.DEFAULTS.items():
            v = UserPref.get(user_id, k)
            if isinstance(d, bool):
                out[k] = str(v).lower() in ("true", "1", "on")
            else:
                out[k] = v
        return out


# ---------------------------------------------------------------- HIMS: patient folders
# How the patient pays. LAHSMA is the Lagos State health insurance scheme;
# Megalex is the private payment system Lagos State hospitals use to collect
# revenue. Both are recorded on the folder so Billing and the doctor know the
# route before the patient reaches them.
PAYER_TYPES = (
    ("SELF", "Self-paying (cash / transfer)"),
    ("LAHSMA", "LAHSMA — Lagos State health insurance"),
    ("MEGALEX", "Megalex — Lagos State revenue system"),
    ("NHIS", "NHIS — National Health Insurance"),
    ("HMO", "Private HMO / company retainer"),
    ("EXEMPT", "Exempt / waiver approved"),
)
PAYER_LABELS = dict(PAYER_TYPES)
PAYER_CODES = tuple(c for c, _ in PAYER_TYPES)

SEXES = (("F", "Female"), ("M", "Male"))
SEX_LABELS = dict(SEXES)

MARITAL_STATUSES = ("Single", "Married", "Widowed", "Divorced", "Separated")

# Patient categories drive Triage in Stage B: a child does not go to the same
# clinic as an antenatal mother, and an elderly patient may be seen sooner.
PATIENT_CATEGORIES = (
    ("GENERAL", "General adult"),
    ("CHILD", "Child (under 12)"),
    ("ANTENATAL", "Antenatal / maternity"),
    ("ELDERLY", "Elderly (65+)"),
    ("CHRONIC", "Chronic condition (follow-up)"),
    ("EMERGENCY", "Emergency"),
)
CATEGORY_LABELS = dict(PATIENT_CATEGORIES)
CATEGORY_CODES = tuple(c for c, _ in PATIENT_CATEGORIES)

BLOOD_GROUPS = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")
GENOTYPES = ("AA", "AS", "AC", "SS", "SC", "CC")


class Patient(db.Model):
    """A patient folder — the hospital record that everything else hangs on.

    WHY THIS EXISTS
    ---------------
    Until now the suite stored a loose ``patient_name`` and ``phone`` on each
    booking and each queue ticket. Two visits by the same woman were two
    unrelated strings. Nothing could answer "has this patient been here
    before?", nothing could carry her payment route to Billing, and the doctor
    had no record to open.

    A folder is opened ONCE, on a first visit, and found again on every return
    visit — which is exactly what the founder described:

        "HIMS Register: i. open folder for new/first visit patient,
         ii. Search for the folder of returning patient"

    IDENTIFIERS
    -----------
    ``hospital_number`` is the number written on the paper folder and called
    out at the desk. It is generated per hospital as ``IJD/2026/00001`` and is
    unique within the tenant, never across tenants.
    """
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    hospital_number = db.Column(db.String(32), nullable=False, index=True)

    # --- identity
    surname = db.Column(db.String(80), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    other_names = db.Column(db.String(80))
    sex = db.Column(db.String(1), nullable=False)                 # F | M
    date_of_birth = db.Column(db.Date)
    # Many patients genuinely do not know their date of birth. Recording a
    # stated age is honest; inventing a birthday is not.
    age_years = db.Column(db.Integer)
    marital_status = db.Column(db.String(16))
    occupation = db.Column(db.String(80))
    religion = db.Column(db.String(40))

    # --- contact
    phone = db.Column(db.String(32), index=True)
    phone_alt = db.Column(db.String(32))
    address = db.Column(db.String(300))
    lga = db.Column(db.String(80))                                # local government area
    state = db.Column(db.String(80))

    # --- next of kin (required: somebody must be reachable in an emergency)
    nok_name = db.Column(db.String(120))
    nok_relationship = db.Column(db.String(40))
    nok_phone = db.Column(db.String(32))
    nok_address = db.Column(db.String(300))

    # --- how they pay
    payer_type = db.Column(db.String(16), default="SELF", nullable=False, index=True)
    payer_number = db.Column(db.String(60))                       # LAHSMA/NHIS/HMO number
    payer_name = db.Column(db.String(120))                        # HMO or employer

    # --- clinical basics the doctor wants at a glance
    category = db.Column(db.String(16), default="GENERAL", nullable=False, index=True)
    blood_group = db.Column(db.String(4))
    genotype = db.Column(db.String(4))
    allergies = db.Column(db.String(300))
    chronic_conditions = db.Column(db.String(300))

    # --- housekeeping
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True, nullable=False)
    # NDPA: the patient consented to the hospital holding these details.
    consent_at = db.Column(db.DateTime)
    anonymized_at = db.Column(db.DateTime)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=now_naive, index=True)
    updated_at = db.Column(db.DateTime, default=now_naive, onupdate=now_naive)
    last_visit_at = db.Column(db.DateTime, index=True)

    creator = db.relationship("User", foreign_keys=[created_by])
    visits = db.relationship("PatientVisit", backref="patient", lazy="select",
                             order_by="PatientVisit.started_at.desc()")

    __table_args__ = (
        db.UniqueConstraint("org_id", "hospital_number", name="uq_patient_org_number"),
        db.Index("ix_patient_org_surname", "org_id", "surname"),
    )

    @property
    def full_name(self) -> str:
        bits = [(self.surname or "").upper(), self.first_name]
        if self.other_names:
            bits.append(self.other_names)
        return " ".join(b for b in bits if b)

    @property
    def age(self) -> int | None:
        """Age today, computed from the birthday when we have one."""
        if self.date_of_birth:
            t = now_naive().date()
            return (t.year - self.date_of_birth.year
                    - ((t.month, t.day) < (self.date_of_birth.month, self.date_of_birth.day)))
        return self.age_years

    @property
    def age_display(self) -> str:
        a = self.age
        return f"{a} yrs" if a is not None else "age not known"

    @property
    def payer_label(self) -> str:
        return PAYER_LABELS.get(self.payer_type, self.payer_type)

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    @property
    def is_returning(self) -> bool:
        return bool(self.last_visit_at)

    @property
    def alerts(self) -> list[str]:
        """Things a doctor must not miss, shown in red on the folder."""
        out = []
        if self.allergies:
            out.append(f"Allergic to: {self.allergies}")
        if self.genotype in ("SS", "SC"):
            out.append(f"Genotype {self.genotype} — sickle cell")
        if self.chronic_conditions:
            out.append(self.chronic_conditions)
        return out


VISIT_STATUSES = ("REGISTERED", "TRIAGED", "IN_CONSULTATION", "ONWARD", "CLOSED", "CANCELLED")
VISIT_TYPES = (("NEW", "First visit"), ("FOLLOW_UP", "Follow-up"),
               ("EMERGENCY", "Emergency"), ("ANTENATAL", "Antenatal"))


class PatientVisit(db.Model):
    """One attendance. Opened at the HIMS desk, then carried through the flow.

    Stage A only creates it and marks it REGISTERED. Triage (Stage B), the
    consulting room (Stage C) and onward routing (Stage D) each move it along,
    which is why the clinic/room/destination columns already exist but are left
    empty for now — so those stages add behaviour, not another migration.
    """
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patient.id"), nullable=False, index=True)
    visit_no = db.Column(db.String(40), nullable=False, index=True)
    visit_type = db.Column(db.String(16), default="FOLLOW_UP", nullable=False)
    status = db.Column(db.String(16), default="REGISTERED", nullable=False, index=True)

    reason = db.Column(db.String(300))            # what the patient says is wrong
    payer_type = db.Column(db.String(16))         # how THIS visit is being paid for
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointment.id"))
    queue_ticket_id = db.Column(db.Integer, db.ForeignKey("queue_ticket.id"))

    # filled in by later stages — deliberately created now, used later
    clinic = db.Column(db.String(20))             # OPD | SOPD | MOPD | EMERGENCY
    consulting_room = db.Column(db.String(20))
    doctor_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    started_at = db.Column(db.DateTime, default=now_naive, nullable=False, index=True)
    triaged_at = db.Column(db.DateTime)
    seen_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    registered_by = db.Column(db.Integer, db.ForeignKey("user.id"))

    department = db.relationship("Department")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    registrar = db.relationship("User", foreign_keys=[registered_by])

    __table_args__ = (db.UniqueConstraint("org_id", "visit_no", name="uq_visit_org_no"),)


# ---------------------------------------------------------------- settings
class Setting(db.Model):
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), primary_key=True)
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.Text)

    @staticmethod
    def get(org_id: int, key: str, default=None):
        row = db.session.get(Setting, (org_id, key))
        if row is None or row.value is None:
            return default
        try:
            return json.loads(row.value)
        except Exception:
            return row.value

    @staticmethod
    def set(org_id: int, key: str, value):
        row = db.session.get(Setting, (org_id, key))
        if row is None:
            row = Setting(org_id=org_id, key=key)
            db.session.add(row)
        row.value = json.dumps(value)
        return row
