"""Centralized notification engine: in-app, email, WhatsApp (+SMS hook).

Every notification is templated, logged (AppNotification) and channel
failures never break the business flow.
"""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from flask import current_app

from . import services, whatsapp
from .models import AppNotification, User, db, now_naive

# Templates: (subject, body). Placeholders: {name},{hospital},{date},{ref},{dept},{time},{details}
TEMPLATES = {
    "duty_reminder_day_before": (
        "Duty reminder — tomorrow",
        "Dear {name}, you are scheduled as the Admin Manager on duty tomorrow "
        "({date}) at {hospital}. Please prepare for your daily hospital inspection."),
    "duty_reminder_day_of": (
        "Duty reminder — today",
        "Dear {name}, you are the Admin Manager on duty today ({date}) at {hospital}. "
        "Please complete today's departmental inspection."),
    "inspection_overdue": (
        "Inspection overdue",
        "Today's inspection at {hospital} is overdue. Admin Manager on duty: {name}. "
        "Deadline was {time}."),
    "inspection_submitted": (
        "Daily inspection report",
        "Daily inspection report {ref} for {dept} has been submitted by {name}. "
        "Overall rating: {rating} ({total}/25)."),
    "complaint_new_hod": (
        "New patient complaint",
        "A new patient complaint ({ref}) concerning {dept} ({category}) requires your "
        "attention within {sla} hours. Sign in to review and acknowledge."),
    "complaint_new_admin": (
        "New patient complaint on your duty day",
        "A new patient complaint ({ref}) concerning {dept} ({category}) has been received."),
    "complaint_escalated": (
        "Complaint ESCALATED — SLA breached",
        "Complaint {ref} ({dept}) was not resolved within the SLA and has been "
        "escalated to the MD/CEO. Details are available in the system."),
    "complaint_sla_warning": (
        "Complaint SLA warning",
        "Complaint {ref} ({dept}) must be resolved within the next {hours} hours to "
        "avoid escalation."),
    "ca_assigned": (
        "Corrective action assigned",
        "A corrective action has been assigned to you: {details}. Deadline: {date}."),
    "ca_overdue": (
        "Corrective action overdue",
        "Corrective action '{details}' is overdue (deadline {date})."),
    "critical_score": (
        "ALERT: Critical inspection finding",
        "Inspection {ref} at {dept} recorded a critical finding. Immediate intervention required."),
    "booking_new": (
        "New patient booking",
        "New booking {ref}: {dept}. Please see the Bookings screen for details."),
}


def render(template_key: str, ctx: dict) -> tuple[str, str]:
    subject_t, body_t = TEMPLATES[template_key]
    ctx.setdefault("hospital", "the hospital")
    return subject_t.format(**ctx), body_t.format(**ctx)


def _send_email(user: User, subject: str, body: str) -> str | None:
    cfg = current_app.config
    if not cfg.get("SMTP_HOST") or not user.email:
        return "SMTP not configured" if not cfg.get("SMTP_HOST") else "No user email"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["SMTP_FROM"]
    msg["To"] = user.email
    try:
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=20) as s:
            if cfg.get("SMTP_TLS"):
                s.starttls()
            if cfg.get("SMTP_USER"):
                s.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            s.send_message(msg)
        return None
    except Exception as exc:  # noqa: BLE001 — logged, never fatal
        return str(exc)[:300]


def notify(org_id: int, user: User, template_key: str, ctx: dict,
           channels: list[str] | None = None, entity_type: str = None,
           entity_id: int = None, wa_body_override: str = None,
           wa_media_path: str = None, wa_kind: str = "alert"):
    """Send a templated notification through configured channels. Always logged."""
    channels = channels or services.get_setting(org_id, "reminder_channels", ["inapp"])
    subject, body = render(template_key, ctx)

    # 1) in-app — always recorded
    db.session.add(AppNotification(org_id=org_id, user_id=user.id, channel="inapp",
                                   template_key=template_key, subject=subject, body=body,
                                   entity_type=entity_type, entity_id=entity_id, status="SENT"))

    # 2) email — only when SMTP configured and user has an email
    if "email" in channels:
        err = _send_email(user, subject, body)
        db.session.add(AppNotification(org_id=org_id, user_id=user.id, channel="email",
                                       template_key=template_key, subject=subject, body=body,
                                       entity_type=entity_type, entity_id=entity_id,
                                       status="SENT" if err is None else "FAILED", error=err))

    # 3) WhatsApp — queue for the WhatsApp engine (official Business API / sandbox)
    if "whatsapp" in channels and user.phone:
        whatsapp.queue_message(org_id, user.phone, wa_body_override or body, kind=wa_kind,
                               media_path=wa_media_path, entity_type=entity_type,
                               entity_id=entity_id, to_user_id=user.id)

    # 4) SMS — provider interface (Termii primary / Twilio fallback / sandbox)
    if "sms" in channels and user.phone:
        from . import sms as sms_engine
        sms_engine.queue_sms(org_id, user.phone, wa_body_override or body, kind=wa_kind,
                             entity_type=entity_type, entity_id=entity_id)
    db.session.commit()


def notify_many(org_id: int, users: list[User], template_key: str, ctx: dict, **kw):
    for u in users:
        if u and u.active:
            notify(org_id, u, template_key, dict(ctx, name=u.name), **kw)


def admin_managers(org_id: int) -> list[User]:
    return db.session.query(User).filter_by(org_id=org_id, role="ADMIN_MANAGER", active=True).all()


def md_ceos(org_id: int) -> list[User]:
    return db.session.query(User).filter_by(org_id=org_id, role="MD_CEO", active=True).all()


def super_admins(org_id: int) -> list[User]:
    return db.session.query(User).filter_by(org_id=org_id, role="SUPER_ADMIN", active=True).all()
