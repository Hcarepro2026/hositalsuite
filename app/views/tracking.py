"""Monitoring & Tracking — the numbers that prove the hospital works."""
from __future__ import annotations

import csv
import io

from flask import Blueprint, Response, render_template, request
from flask_login import current_user

from .. import tracking
from ..models import JOURNEY_STAGE_LABELS, Patient, PatientVisit, db
from ..security import require_role

bp = Blueprint("tracking", __name__)

VIEWERS = ("SUPER_ADMIN", "MD_CEO", "DMD", "DCST", "APEX_NURSE",
           "HEAD_ADMIN_HR", "ADMIN_MANAGER", "HOD")


def _days() -> int:
    """Requested window, clamped. A hostile ?days=99999 must not scan forever."""
    raw = request.args.get("days", type=int) or 7
    return max(1, min(raw, 90))


@bp.get("/tracking")
@require_role(*VIEWERS)
def dashboard():
    org_id = current_user.org_id
    days = _days()
    return render_template(
        "tracking/dashboard.html",
        days=days,
        head=tracking.headline(org_id, days),
        stages=tracking.stage_performance(org_id, days),
        departments=tracking.department_performance(org_id, days),
        staff=tracking.staff_workload(org_id, days),
        live=tracking.live_board(org_id),
        advice=tracking.suggest_allocation(org_id),
        weeks=tracking.trend(org_id, 4),
        hours=tracking.busiest_hours(org_id),
        colours=tracking.RATING_COLOURS,
        targets=tracking.STAGE_TARGET_MINUTES,
        min_sample=tracking.MIN_SAMPLE)


@bp.get("/tracking/patient/<int:visit_id>")
@require_role(*VIEWERS)
def patient_journey(visit_id: int):
    """One patient's whole walk, step by step, with the time at each."""
    org_id = current_user.org_id
    visit = db.session.get(PatientVisit, visit_id)
    if visit is None or visit.org_id != org_id:
        from flask import abort
        abort(404)
    segments = tracking.journey_for(org_id, visit_id)
    return render_template(
        "tracking/journey.html", visit=visit,
        patient=db.session.get(Patient, visit.patient_id),
        segments=segments,
        total=tracking.total_minutes(segments),
        targets=tracking.STAGE_TARGET_MINUTES)


@bp.get("/tracking/export")
@require_role(*VIEWERS)
def export():
    """Every finished stretch as CSV — so the figures can be checked by hand."""
    org_id = current_user.org_id
    days = _days()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["stage", "label", "patients_measured", "average_minutes",
                "median_minutes", "longest_minutes", "target_minutes",
                "verdict", "enough_data"])
    for s in tracking.stage_performance(org_id, days):
        w.writerow([s["stage"], s["label"], s["count"], s["average"],
                    s["median"], s["longest"],
                    tracking.STAGE_TARGET_MINUTES.get(s["stage"], ""),
                    s["rating"], "yes" if s["reliable"] else "no"])
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="patient-flow-{days}days.csv"'})
