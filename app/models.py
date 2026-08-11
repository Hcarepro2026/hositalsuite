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

ROLES = ("SUPER_ADMIN", "MD_CEO", "ADMIN_MANAGER", "HOD")

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
class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(12), unique=True, nullable=False)       # e.g. HOSP
    name = db.Column(db.String(160), nullable=False)
    logo_path = db.Column(db.String(300))
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
    created_at = db.Column(db.DateTime, default=now_naive)
    last_login_at = db.Column(db.DateTime)

    org = db.relationship("Organization", backref="users")

    @property
    def is_super(self): return self.role == "SUPER_ADMIN"
    @property
    def is_md(self): return self.role == "MD_CEO"
    @property
    def is_am(self): return self.role == "ADMIN_MANAGER"
    @property
    def is_hod(self): return self.role == "HOD"

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
    active = db.Column(db.Boolean, default=True, nullable=False)
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
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), nullable=False, index=True)
    category = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(32), nullable=False)
    contact_method = db.Column(db.String(20), default="phone")   # phone | whatsapp | either
    attachment_path = db.Column(db.String(300))
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
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    at = db.Column(db.DateTime, default=now_naive)
    user = db.relationship("User")


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
