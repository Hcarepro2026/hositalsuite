"""Domain services: settings, reference numbers, routing, roster, analytics."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from .models import (Complaint, Department, DutyRoster, Inspection, Organization,
                     QrLocation, Section, Setting, Unit, User, db, now_naive)
from . import scoring

# ------------------------------------------------------------------ settings
DEFAULT_SETTINGS = {
    "sla_hours": 24,
    "reminder_day_before_time": "18:00",
    "reminder_duty_day_time": "07:00",
    "inspection_deadline_time": "18:00",
    "overdue_notify_time": "19:00",
    "gps_mode": "optional",               # mandatory | optional | disabled
    "whatsapp_md_number": "",
    "whatsapp_report_template": "inspection_report_v1",
    "multiple_two_threshold": 2,
    "recurring_window": 10,
    "recurring_threshold": 3,
    "retention_days": 2190,               # 6 years (NDPR-aligned default)
    "reminder_channels": ["inapp", "whatsapp"],
    "complaint_channels_note": "QR / direct link / USSD",
    "voice_storage": False,               # never store audio by default
}


def get_setting(org_id: int, key: str, default=None):
    val = Setting.get(org_id, key, None)
    return val if val is not None else DEFAULT_SETTINGS.get(key, default)


def set_setting(org_id: int, key: str, value):
    Setting.set(org_id, key, value)


def org_settings_bundle(org_id: int) -> dict:
    return {k: get_setting(org_id, k) for k in DEFAULT_SETTINGS}


def parse_hhmm(s: str) -> tuple[int, int]:
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", s or "")
    if not m:
        return 7, 0
    return int(m.group(1)), int(m.group(2))


# ------------------------------------------------------------------ references
def next_ref(org: Organization, kind: str, model, year: int) -> str:
    prefix = f"{org.code}-{kind}-{year}-"
    count = db.session.query(model).filter(
        model.org_id == org.id, model.ref.like(prefix + "%")).count()
    # ensure uniqueness even under concurrency
    n = count + 1
    while True:
        ref = f"{prefix}{n:06d}"
        exists = db.session.query(model).filter_by(ref=ref).first()
        if not exists:
            return ref
        n += 1


def next_inspection_ref(org: Organization, when: datetime) -> str:
    return next_ref(org, "INS", Inspection, when.year)


def next_complaint_ref(org: Organization, when: datetime) -> str:
    return next_ref(org, "CMP", Complaint, when.year)


# ------------------------------------------------------------------ duty / roster
def on_duty(org_id: int, day: date) -> Optional[User]:
    row = db.session.query(DutyRoster).filter_by(org_id=org_id, duty_date=day).first()
    return row.user if row else None


def todays_inspection(org_id: int, day: date) -> Optional[Inspection]:
    return (db.session.query(Inspection)
            .filter_by(org_id=org_id, duty_date=day, status="SUBMITTED")
            .order_by(Inspection.submitted_at.desc()).first())


def inspection_state(org_id: int, day: date, now: datetime = None) -> dict:
    """Return duty/inspection status for a day: completed | pending | overdue | unassigned."""
    now = now or now_naive()
    duty = on_duty(org_id, day)
    insp = todays_inspection(org_id, day)
    hh, mm = parse_hhmm(get_setting(org_id, "inspection_deadline_time"))
    deadline = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if insp:
        state = "completed"
    elif not duty:
        state = "unassigned"
    elif now > deadline:
        state = "overdue"
    else:
        state = "pending"
    return {"duty": duty, "inspection": insp, "state": state, "deadline": deadline}


# ------------------------------------------------------------------ routing
def department_chain(dept: Department, section: Section = None, unit: Unit = None):
    """Most-specific HOD first, falling back to department HOD."""
    for obj in (unit, section, dept):
        if obj is not None and getattr(obj, "hod_user_id", None):
            yield obj.hod
    return None


def route_hod(dept: Department, section: Section = None, unit: Unit = None) -> Optional[User]:
    for u in department_chain(dept, section, unit):
        if u and u.active:
            return u
    return None


# ------------------------------------------------------------------ analytics
def department_history(org_id: int, department_id: int, limit: int = 10) -> list[Inspection]:
    return (db.session.query(Inspection)
            .filter_by(org_id=org_id, department_id=department_id, status="SUBMITTED")
            .order_by(Inspection.submitted_at.desc()).limit(limit).all())


def inspection_criterion_map(insp: Inspection) -> dict:
    return {s.criterion_no: s.score for s in insp.scores}


def recurring_flags_for_department(org_id: int, department_id: int) -> list[str]:
    window = int(get_setting(org_id, "recurring_window") or 10)
    threshold = int(get_setting(org_id, "recurring_threshold") or 3)
    hist = department_history(org_id, department_id, limit=window)
    as_dicts = [{"criterion_scores": inspection_criterion_map(i)} for i in hist]
    return scoring.recurring_findings(as_dicts, window=window, threshold=threshold)


def management_attention(org_id: int, now: datetime = None) -> list[dict]:
    """The 'Management Attention' list: the issues that need action right now."""
    now = now or now_naive()
    items: list[dict] = []

    # 1. Overdue corrective actions
    from .models import CorrectiveAction
    overdue_cas = (db.session.query(CorrectiveAction)
                   .filter(CorrectiveAction.org_id == org_id,
                           CorrectiveAction.status.in_(("OPEN", "IN_PROGRESS", "OVERDUE")),
                           CorrectiveAction.deadline < now.date()).all())
    for ca in overdue_cas:
        items.append({"level": "high", "kind": "Corrective action overdue",
                      "text": f"Overdue corrective action: {ca.finding[:120]}",
                      "href": f"/corrective-actions?highlight={ca.id}"})

    # 2. Escalated open complaints
    esc = (db.session.query(Complaint)
           .filter(Complaint.org_id == org_id, Complaint.escalated.is_(True),
                   Complaint.status.in_(("NEW", "ACKNOWLEDGED", "IN_PROGRESS", "ESCALATED"))).all())
    for c in esc:
        items.append({"level": "high", "kind": "Escalated complaint",
                      "text": f"{c.ref} — {c.category} in {c.department.name} is escalated to MD/CEO.",
                      "href": f"/complaints/{c.id}"})

    # 3. SLA about to breach (within 4h)
    soon = (db.session.query(Complaint)
            .filter(Complaint.org_id == org_id, Complaint.escalated.is_(False),
                    Complaint.status.in_(("NEW", "ACKNOWLEDGED", "IN_PROGRESS")),
                    Complaint.sla_deadline_at < now + timedelta(hours=4),
                    Complaint.sla_deadline_at > now).all())
    for c in soon:
        items.append({"level": "medium", "kind": "SLA expiring soon",
                      "text": f"{c.ref} — SLA expires {c.sla_deadline_at.strftime('%H:%M')} today.",
                      "href": f"/complaints/{c.id}"})

    # 4. Recurring poor criteria per department
    for dept in db.session.query(Department).filter_by(org_id=org_id, active=True).all():
        for msg in recurring_flags_for_department(org_id, dept.id):
            items.append({"level": "medium", "kind": "Recurring finding",
                          "text": f"{dept.name}: {msg}", "href": f"/reports/departments/{dept.id}"})

    # 5. Failed WhatsApp report deliveries
    from .models import WhatsAppMessage
    failed = (db.session.query(WhatsAppMessage)
              .filter_by(org_id=org_id, status="FAILED").count())
    if failed:
        items.append({"level": "high", "kind": "WhatsApp delivery failure",
                      "text": f"{failed} WhatsApp message(s) failed to deliver. Review and retry.",
                      "href": "/admin/notifications"})

    # 6. Missed inspections in last 7 days
    today = now.date()
    for offset in range(1, 8):
        day = today - timedelta(days=offset)
        st = inspection_state(org_id, day, now=now)
        if st["state"] in ("overdue", "unassigned") and on_duty(org_id, day) is None and st["state"] == "unassigned":
            continue
        if st["state"] == "overdue" or (st["duty"] and not st["inspection"]):
            items.append({"level": "medium", "kind": "Missed inspection",
                          "text": f"No inspection recorded on {day.strftime('%a %d %b')} "
                                  f"(on duty: {st['duty'].name if st['duty'] else '—'}).",
                          "href": "/inspections"})
    return items


def heatmap_data(org_id: int, days: int = 14) -> dict:
    """department -> list of (date, total|None) for the last N days."""
    today = now_naive().date()
    start = today - timedelta(days=days - 1)
    depts = db.session.query(Department).filter_by(org_id=org_id, active=True).order_by(Department.name).all()
    inspections = (db.session.query(Inspection)
                   .filter(Inspection.org_id == org_id, Inspection.status == "SUBMITTED",
                           Inspection.duty_date >= start).all())
    grid = {}
    for d in depts:
        row = []
        for off in range(days):
            day = start + timedelta(days=off)
            scores = [i.total_score for i in inspections if i.department_id == d.id and i.duty_date == day]
            row.append(max(scores) if scores else None)
        grid[d.name] = row
    return {"start": start, "days": days, "grid": grid}
