"""Dashboards, notification inbox, corrective actions, management attention."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from .. import scoring, services
from ..audit import audit
from ..models import (AppNotification, Complaint, CorrectiveAction, Department,
                      DutyRoster, Inspection, db, now_naive)
from ..security import require_login, save_upload

bp = Blueprint("main", __name__)


def _kpi(org_id: int) -> dict:
    now = now_naive()
    today = now.date()
    st = services.inspection_state(org_id, today, now=now)

    insp_all = db.session.query(Inspection).filter_by(org_id=org_id, status="SUBMITTED").all()
    total_inspections = len(insp_all)
    avg_score = round(sum(i.total_score or 0 for i in insp_all) / total_inspections, 1) if total_inspections else 0

    # department averages (last 30 days)
    since = today - timedelta(days=30)
    dept_rows = []
    for d in db.session.query(Department).filter_by(org_id=org_id, active=True).order_by(Department.name).all():
        recent = [i.total_score for i in insp_all if i.department_id == d.id and i.duty_date >= since]
        if recent:
            dept_rows.append({"dept": d, "avg": round(sum(recent) / len(recent), 1), "n": len(recent)})
    dept_rows.sort(key=lambda r: r["avg"])

    critical_findings = sum(i.critical_count or 0 for i in insp_all if i.duty_date >= since)

    complaints = db.session.query(Complaint).filter_by(org_id=org_id).all()
    open_complaints = [c for c in complaints if c.status in ("NEW", "ACKNOWLEDGED", "IN_PROGRESS", "ESCALATED")]
    escalated = [c for c in complaints if c.escalated]
    resolved = [c for c in complaints if c.status in ("RESOLVED", "CLOSED")]
    sla_breaches = len([c for c in complaints if c.escalated])

    # inspection compliance (last 30 days): roster days with a submitted inspection
    roster_days = db.session.query(DutyRoster).filter(
        DutyRoster.org_id == org_id, DutyRoster.duty_date >= since, DutyRoster.duty_date <= today).all()
    inspected_dates = {i.duty_date for i in insp_all if i.duty_date >= since}
    compliance = round(100 * len([r for r in roster_days if r.duty_date in inspected_dates]) / len(roster_days)) if roster_days else 0

    cas_open = db.session.query(CorrectiveAction).filter(
        CorrectiveAction.org_id == org_id,
        CorrectiveAction.status.in_(("OPEN", "IN_PROGRESS", "OVERDUE"))).all()

    return {
        "today": st,
        "total_inspections": total_inspections,
        "avg_score": avg_score,
        "lowest_depts": dept_rows[:5],
        "critical_findings_30d": critical_findings,
        "complaints_total": len(complaints),
        "complaints_new": len([c for c in complaints if c.status == "NEW"]),
        "complaints_open": len(open_complaints),
        "complaints_escalated": len(escalated),
        "sla_breaches": sla_breaches,
        "resolution_rate": round(100 * len(resolved) / len(complaints)) if complaints else 0,
        "compliance_rate": compliance,
        "cas_open": cas_open,
        "heatmap": services.heatmap_data(org_id, days=14),
    }


@bp.get("/")
@require_login
def dashboard():
    org_id = current_user.org_id
    kpi = _kpi(org_id)
    attention = services.management_attention(org_id) if (current_user.is_md or current_user.is_super) else []
    my_cas = None
    if current_user.is_am or current_user.is_hod:
        my_cas = (db.session.query(CorrectiveAction)
                  .filter(CorrectiveAction.org_id == org_id, CorrectiveAction.owner_id == current_user.id,
                          CorrectiveAction.status.in_(("OPEN", "IN_PROGRESS", "OVERDUE")))
                  .order_by(CorrectiveAction.deadline).all())
    recent_complaints = None
    if current_user.is_hod:
        recent_complaints = (db.session.query(Complaint)
                             .filter(Complaint.org_id == org_id,
                                     Complaint.status.in_(("NEW", "ACKNOWLEDGED", "IN_PROGRESS", "ESCALATED")))
                             .order_by(Complaint.submitted_at.desc()).limit(8).all())
    return render_template("dashboard.html", kpi=kpi, attention=attention, my_cas=my_cas,
                           recent_complaints=recent_complaints, scoring=scoring)


# ------------------------------------------------------------------ notifications inbox
@bp.get("/notifications")
@require_login
def notifications_inbox():
    items = (db.session.query(AppNotification)
             .filter_by(org_id=current_user.org_id, user_id=current_user.id, channel="inapp")
             .order_by(AppNotification.created_at.desc()).limit(100).all())
    return render_template("notifications.html", items=items)


@bp.post("/notifications/read")
@require_login
def notifications_read():
    (db.session.query(AppNotification)
     .filter_by(org_id=current_user.org_id, user_id=current_user.id, channel="inapp", status="SENT")
     .update({"status": "READ"}))
    db.session.commit()
    return redirect(url_for("main.notifications_inbox"))


# ------------------------------------------------------------------ corrective actions
@bp.get("/corrective-actions")
@require_login
def corrective_actions():
    q = db.session.query(CorrectiveAction).filter(CorrectiveAction.org_id == current_user.org_id)
    status = request.args.get("status")
    if status in ("OPEN", "IN_PROGRESS", "COMPLETED", "OVERDUE", "VERIFIED"):
        q = q.filter(CorrectiveAction.status == status)
    mine = request.args.get("mine")
    if mine == "1" or (current_user.is_am or current_user.is_hod):
        if mine == "1":
            q = q.filter(CorrectiveAction.owner_id == current_user.id)
    items = q.order_by(CorrectiveAction.deadline).all()
    from ..models import User
    users = db.session.query(User).filter_by(org_id=current_user.org_id, active=True).order_by(User.name).all()
    return render_template("corrective_actions.html", items=items, users=users,
                           highlight=request.args.get("highlight"),
                           can_create=current_user.role in ("SUPER_ADMIN", "MD_CEO", "ADMIN_MANAGER"))


@bp.post("/corrective-actions")
@require_login
def corrective_action_create():
    if current_user.role not in ("SUPER_ADMIN", "MD_CEO", "ADMIN_MANAGER"):
        return redirect(url_for("main.corrective_actions"))
    finding = (request.form.get("finding") or "").strip()
    action_required = (request.form.get("action_required") or "").strip()
    owner_id = request.form.get("owner_id", type=int)
    deadline = request.form.get("deadline")
    source_type = request.form.get("source_type", "inspection")
    source_id = request.form.get("source_id", type=int) or 0
    if not finding or not action_required or not owner_id or not deadline:
        flash("All corrective-action fields are required.", "error")
        return redirect(url_for("main.corrective_actions"))
    from datetime import date as _date
    try:
        dl = _date.fromisoformat(deadline)
    except ValueError:
        flash("Invalid deadline date.", "error")
        return redirect(url_for("main.corrective_actions"))
    ca = CorrectiveAction(org_id=current_user.org_id, source_type=source_type, source_id=source_id,
                          finding=finding, action_required=action_required, owner_id=owner_id,
                          deadline=dl, status="OPEN")
    db.session.add(ca)
    db.session.flush()
    audit("CA_CREATED", "ca", ca.id, {"finding": finding[:120], "deadline": deadline})
    from .. import notifications
    notifications.notify(current_user.org_id, ca.owner, "ca_assigned",
                         {"details": finding[:100], "date": dl.strftime("%d %b %Y")},
                         channels=["inapp"], entity_type="ca", entity_id=ca.id)
    db.session.commit()
    flash("Corrective action created and owner notified.", "success")
    return redirect(url_for("main.corrective_actions"))


@bp.post("/corrective-actions/<int:ca_id>/update")
@require_login
def corrective_action_update(ca_id: int):
    ca = db.session.get(CorrectiveAction, ca_id)
    if not ca or ca.org_id != current_user.org_id:
        flash("Corrective action not found.", "error")
        return redirect(url_for("main.corrective_actions"))
    new_status = request.form.get("status")
    if new_status not in ("OPEN", "IN_PROGRESS", "COMPLETED", "VERIFIED"):
        flash("Invalid status.", "error")
        return redirect(url_for("main.corrective_actions"))
    # verification is management-only
    if new_status == "VERIFIED" and current_user.role not in ("SUPER_ADMIN", "MD_CEO"):
        flash("Only management can verify a corrective action.", "error")
        return redirect(url_for("main.corrective_actions"))
    old = ca.status
    ca.status = new_status
    if new_status == "COMPLETED":
        ca.completed_at = now_naive()
        file = request.files.get("evidence")
        if file and file.filename:
            path, err = save_upload(file, "ca")
            if not err:
                ca.evidence_path = path
    if new_status == "VERIFIED":
        ca.verified_by_id = current_user.id
        ca.verified_at = now_naive()
    audit("CA_UPDATED", "ca", ca.id, {"old_status": old, "new_status": new_status})
    db.session.commit()
    flash(f"Corrective action updated to {new_status}.", "success")
    return redirect(url_for("main.corrective_actions"))
