"""Background scheduler — one daemon thread driving all time-based automation:

* duty reminders (day-before + duty-day, configurable times)
* overdue inspection detection + management notification
* complaint SLA breach -> automatic escalation to MD/CEO
* complaint SLA warnings
* overdue corrective actions
* WhatsApp queue processing + retry
* nightly database backup

All jobs are idempotent (guarded by 'already-sent' markers / audit rows) so
restarting the app never double-sends.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from datetime import timedelta

from . import notifications, scoring, services, whatsapp
from .audit import audit
from .models import (AppNotification, Complaint, CorrectiveAction, DutyRoster,
                     Organization, db, now_naive)

_started = False
_lock = threading.Lock()


# ------------------------------------------------------------------ helpers
def _sent_marker(org_id: int, template_key: str, entity_type: str, entity_id: int) -> bool:
    return db.session.query(AppNotification).filter_by(
        org_id=org_id, template_key=template_key, entity_type=entity_type,
        entity_id=entity_id).first() is not None


def _mark(template_key: str, user, body: str, org_id: int, entity_type: str, entity_id: int):
    db.session.add(AppNotification(org_id=org_id, user_id=user.id if user else None,
                                   channel="inapp", template_key=template_key,
                                   subject=template_key, body=body,
                                   entity_type=entity_type, entity_id=entity_id, status="SENT"))


# ------------------------------------------------------------------ jobs
def job_duty_reminders(app):
    """Day-before reminder and duty-day reminder at configured times."""
    now = now_naive()
    today = now.date()
    for org in db.session.query(Organization).all():
        db_hh, db_mm = services.parse_hhmm(services.get_setting(org.id, "reminder_day_before_time"))
        dy_hh, dy_mm = services.parse_hhmm(services.get_setting(org.id, "reminder_duty_day_time"))
        channels = services.get_setting(org.id, "reminder_channels") or ["inapp"]

        # day-before (tomorrow's duty)
        tomorrow = today + timedelta(days=1)
        roster = db.session.query(DutyRoster).filter_by(org_id=org.id, duty_date=tomorrow).first()
        if roster and now.replace(second=0, microsecond=0) >= now.replace(hour=db_hh, minute=db_mm, second=0, microsecond=0):
            if not _sent_marker(org.id, "duty_reminder_day_before", "roster", roster.id):
                notifications.notify(org.id, roster.user, "duty_reminder_day_before",
                                     {"name": roster.user.name, "date": tomorrow.strftime("%A, %d %B %Y"),
                                      "hospital": org.name},
                                     channels=channels, entity_type="roster", entity_id=roster.id)
                _mark("duty_reminder_day_before", roster.user,
                      f"Reminder sent for duty on {tomorrow}", org.id, "roster", roster.id)
                audit("REMINDER_SENT", "roster", roster.id, {"type": "day_before"},
                      org_id=org.id)

        # duty-day
        roster = db.session.query(DutyRoster).filter_by(org_id=org.id, duty_date=today).first()
        if roster and now.replace(second=0, microsecond=0) >= now.replace(hour=dy_hh, minute=dy_mm, second=0, microsecond=0):
            if not _sent_marker(org.id, "duty_reminder_day_of", "roster", roster.id):
                notifications.notify(org.id, roster.user, "duty_reminder_day_of",
                                     {"name": roster.user.name, "date": today.strftime("%A, %d %B %Y"),
                                      "hospital": org.name},
                                     channels=channels, entity_type="roster", entity_id=roster.id)
                _mark("duty_reminder_day_of", roster.user,
                      f"Reminder sent for duty on {today}", org.id, "roster", roster.id)
                audit("REMINDER_SENT", "roster", roster.id, {"type": "day_of"}, org_id=org.id)


def job_overdue_inspection(app):
    now = now_naive()
    today = now.date()
    for org in db.session.query(Organization).all():
        st = services.inspection_state(org.id, today, now=now)
        if st["state"] != "overdue":
            continue
        roster = db.session.query(DutyRoster).filter_by(org_id=org.id, duty_date=today).first()
        if not roster:
            continue
        if not _sent_marker(org.id, "inspection_overdue", "roster", roster.id):
            hh, mm = services.parse_hhmm(services.get_setting(org.id, "overdue_notify_time"))
            if now.hour * 60 + now.minute >= hh * 60 + mm:
                ctx = {"name": roster.user.name, "time":
                       services.get_setting(org.id, "inspection_deadline_time"), "hospital": org.name}
                # nudge the Admin Manager
                notifications.notify(org.id, roster.user, "inspection_overdue", ctx,
                                     channels=["inapp", "whatsapp"], entity_type="roster", entity_id=roster.id)
                # inform MD/CEO + super admins
                for md in notifications.md_ceos(org.id) + notifications.super_admins(org.id):
                    notifications.notify(org.id, md, "inspection_overdue", ctx,
                                         channels=["inapp"], entity_type="roster", entity_id=roster.id)
                _mark("inspection_overdue", roster.user, "Overdue inspection notification",
                      org.id, "roster", roster.id)
                audit("INSPECTION_OVERDUE_FLAG", "roster", roster.id, {"date": str(today)}, org_id=org.id)


def job_complaint_sla(app):
    """Warn before SLA expiry; escalate to MD/CEO when it expires."""
    now = now_naive()
    for org in db.session.query(Organization).all():
        open_complaints = (db.session.query(Complaint)
                           .filter(Complaint.org_id == org.id,
                                   Complaint.status.in_(("NEW", "ACKNOWLEDGED", "IN_PROGRESS")),
                                   Complaint.escalated.is_(False)).all())
        for c in open_complaints:
            if scoring.should_escalate(c.status, c.escalated, c.sla_deadline_at, now):
                old_status = c.status                     # capture BEFORE mutation
                c.escalated = True
                c.status = "ESCALATED"
                c.escalated_at = now
                from .models import ComplaintStatusHistory
                db.session.add(ComplaintStatusHistory(complaint_id=c.id, from_status=old_status,
                                                      to_status="ESCALATED",
                                                      note="Automatic escalation — HOD SLA expired"))
                audit("COMPLAINT_ESCALATED", "complaint", c.id,
                      {"reason": "SLA expired", "deadline": str(c.sla_deadline_at)}, org_id=org.id)
                ctx = {"ref": c.ref, "dept": c.department.name, "hospital": org.name}
                for md in notifications.md_ceos(org.id):
                    notifications.notify(org.id, md, "complaint_escalated", ctx,
                                         channels=["inapp", "email", "whatsapp"],
                                         entity_type="complaint", entity_id=c.id)
                hod = services.route_hod(c.department)
                if hod:
                    notifications.notify(org.id, hod, "complaint_escalated", ctx,
                                         channels=["inapp", "whatsapp"],
                                         entity_type="complaint", entity_id=c.id)
                duty = services.on_duty(org.id, now.date())
                if duty:
                    notifications.notify(org.id, duty, "complaint_escalated", ctx,
                                         channels=["inapp"], entity_type="complaint", entity_id=c.id)
            else:
                # 4-hour warning, once
                remaining = (c.sla_deadline_at - now).total_seconds() / 3600
                if 0 < remaining <= 4 and not _sent_marker(org.id, "complaint_sla_warning", "complaint", c.id):
                    hod = services.route_hod(c.department)
                    if hod:
                        notifications.notify(org.id, hod, "complaint_sla_warning",
                                             {"ref": c.ref, "dept": c.department.name,
                                              "hours": f"{remaining:.0f}", "hospital": org.name},
                                             channels=["inapp", "whatsapp"],
                                             entity_type="complaint", entity_id=c.id)
                        _mark("complaint_sla_warning", hod, "SLA warning", org.id, "complaint", c.id)


def job_corrective_actions(app):
    today = now_naive().date()
    cas = (db.session.query(CorrectiveAction)
           .filter(CorrectiveAction.status.in_(("OPEN", "IN_PROGRESS")),
                   CorrectiveAction.deadline < today).all())
    for ca in cas:
        ca.status = "OVERDUE"
        if not _sent_marker(ca.org_id, "ca_overdue", "ca", ca.id):
            notifications.notify(ca.org_id, ca.owner, "ca_overdue",
                                 {"details": ca.finding[:100], "date": ca.deadline.strftime("%d %b %Y")},
                                 channels=["inapp"], entity_type="ca", entity_id=ca.id)
            for md in notifications.md_ceos(ca.org_id):
                notifications.notify(ca.org_id, md, "ca_overdue",
                                     {"details": ca.finding[:100], "date": ca.deadline.strftime("%d %b %Y")},
                                     channels=["inapp"], entity_type="ca", entity_id=ca.id)
            _mark("ca_overdue", ca.owner, "Overdue CA", ca.org_id, "ca", ca.id)
            audit("CA_OVERDUE", "ca", ca.id, {"deadline": str(ca.deadline)}, org_id=ca.org_id)


def job_whatsapp_queue(app):
    whatsapp.process_queue(limit=20)
    from . import sms as sms_engine
    sms_engine.process_sms_queue(limit=30)


def job_nightly_backup(app):
    """SQLite file backup (for PostgreSQL use pg_dump in ops). Keeps BACKUP_KEEP copies."""
    from .config import Config
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite"):
        return
    db_path = uri.replace("sqlite:///", "")
    if not os.path.exists(db_path):
        return
    stamp = now_naive().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(Config.BACKUP_DIR, f"hospitalsuite-{stamp}.db")
    if os.path.exists(dest):
        return
    shutil.copy2(db_path, dest)
    backups = sorted(f for f in os.listdir(Config.BACKUP_DIR) if f.endswith(".db"))
    for old in backups[: max(0, len(backups) - Config.BACKUP_KEEP)]:
        try:
            os.remove(os.path.join(Config.BACKUP_DIR, old))
        except OSError:
            pass


# ------------------------------------------------------------------ tick
JOB_SEQUENCE = (job_duty_reminders, job_overdue_inspection, job_complaint_sla,
                job_corrective_actions, job_whatsapp_queue)


def tick(app):
    """Run one full automation pass (used by the scheduler thread and by tests/CLI)."""
    with app.app_context():
        try:
            for job in JOB_SEQUENCE:
                try:
                    job(app)
                except Exception as exc:  # noqa: BLE001 — one job must not kill the rest
                    app.logger.exception("Scheduler job %s failed: %s", job.__name__, exc)
                    db.session.rollback()
            db.session.commit()
        except Exception as exc:  # noqa: BLE001
            app.logger.exception("Scheduler tick failed: %s", exc)
            db.session.rollback()


def _loop(app, interval: int):
    # initial backup check on boot day
    last_backup_day = None
    while True:
        try:
            tick(app)
            today = now_naive().date()
            if last_backup_day != today and now_naive().hour >= 2:
                with app.app_context():
                    job_nightly_backup(app)
                last_backup_day = today
        except Exception as exc:  # noqa: BLE001
            app.logger.exception("scheduler loop error: %s", exc)
        time.sleep(interval)


def start_scheduler(app, interval: int = 30):
    global _started
    with _lock:
        if _started:
            return
        t = threading.Thread(target=_loop, args=(app, interval), daemon=True, name="hms-scheduler")
        t.start()
        _started = True
