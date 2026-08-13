"""Patient feedback & service-recovery intake (spec §7, §8).

Extremely simple: rating → optional voice/text comment → optional phone.
Low ratings are INSTANTLY routed into the complaint/service-recovery
pipeline (while the patient is still recoverable). High ratings unlock
the return/refer prompts (§14).
"""
from __future__ import annotations

import re

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user

from .. import notifications, referrals as refeng, scoring, services
from ..audit import audit
from ..models import (Complaint, ComplaintCategory, ComplaintStatusHistory,
                      Department, Organization, PatientFeedback, db, now_naive)
from ..security import rate_limit, require_login

bp = Blueprint("feedback", __name__)

PHONE_RE = re.compile(r"^\+?\d{7,15}$")
LOW_RATING_THRESHOLD = 2


def _default_org():
    return db.session.query(Organization).order_by(Organization.id).first()


# ================================================================ PUBLIC
@bp.get("/feedback")
@rate_limit(limit=30, window=60.0)
def portal():
    org = _default_org()
    if not org:
        abort(503)
    depts = (db.session.query(Department)
             .filter_by(org_id=org.id, active=True).order_by(Department.name).all())
    return render_template("feedback_portal.html", org=org, depts=depts)


@bp.post("/feedback/submit")
@rate_limit(limit=10, window=120.0)
def portal_submit():
    org = _default_org()
    if not org:
        abort(503)
    now = now_naive()
    rating = request.form.get("rating", type=int)
    dept_id = request.form.get("department_id", type=int)
    comment = (request.form.get("comment") or "").strip()
    phone = (request.form.get("phone") or "").strip().replace(" ", "")

    if not rating or not (1 <= rating <= 5):
        flash("Please choose a star rating.", "error")
        return redirect(url_for("feedback.portal"))
    dept = db.session.get(Department, dept_id) if dept_id else None
    if dept and dept.org_id != org.id:
        dept = None
    if phone and not PHONE_RE.match(phone):
        flash("Please enter a valid phone number or leave it empty.", "error")
        return redirect(url_for("feedback.portal"))

    fb = PatientFeedback(org_id=org.id, department_id=dept.id if dept else None,
                         rating=rating, comment=comment[:4000] or None,
                         phone=phone or None, status="NEW",
                         source="qr" if request.form.get("loc") else "link")
    db.session.add(fb)
    db.session.flush()
    refeng.stamp_feedback(org.id, fb)
    audit("FEEDBACK_SUBMITTED", "feedback", fb.id, {"rating": rating}, org_id=org.id)

    # ---- service recovery: low ratings route instantly to the complaint pipeline
    if rating <= LOW_RATING_THRESHOLD:
        target_dept = dept or db.session.query(Department).filter_by(
            org_id=org.id, active=True).order_by(Department.id).first()
        if target_dept is None:
            db.session.commit()   # keep the feedback record; hospital has no departments yet
            return redirect(url_for("feedback.portal_thanks", rating=rating))
        category = (db.session.query(ComplaintCategory)
                    .filter(ComplaintCategory.name.ilike("%feedback%")).first())
        cat_name = category.name if category else "Other"
        sla_hours = int(services.get_setting(org.id, "sla_hours") or 24)
        desc = f"Patient rated their experience {rating}/5." + \
               (f" Comment: {comment[:2000]}" if comment else "")
        c = Complaint(org_id=org.id, ref=services.next_complaint_ref(org, now),
                      department_id=target_dept.id, category=cat_name,
                      description=desc, phone=phone or "not provided", status="NEW",
                      sla_hours=sla_hours, sla_deadline_at=scoring.sla_deadline(now, sla_hours))
        db.session.add(c)
        db.session.flush()
        db.session.add(ComplaintStatusHistory(complaint_id=c.id, from_status=None, to_status="NEW",
                                              note="Created automatically from low patient feedback"))
        fb.status = "ROUTED"
        fb.complaint_id = c.id
        audit("FEEDBACK_ROUTED_TO_RECOVERY", "feedback", fb.id,
              {"complaint": c.ref}, org_id=org.id)
        # route exactly like a complaint: AM on duty + HOD
        ctx = {"ref": c.ref, "dept": target_dept.name, "category": cat_name,
               "sla": sla_hours, "hospital": org.name}
        duty = services.on_duty(org.id, now.date())
        if duty:
            notifications.notify(org.id, duty, "complaint_new_admin", ctx,
                                 channels=["inapp"], entity_type="complaint", entity_id=c.id)
        hod = services.route_hod(target_dept)
        if hod:
            notifications.notify(org.id, hod, "complaint_new_hod", ctx,
                                 channels=["inapp", "whatsapp"], entity_type="complaint", entity_id=c.id)
        db.session.commit()
        return redirect(url_for("feedback.portal_thanks", rating=rating, ref=c.ref))

    # High ratings unlock a personal, trackable share-link (§14). No prizes.
    extra = {}
    if rating >= refeng.HIGH_RATING:
        link = refeng.issue_patient_referral(
            org, fb, department_id=dept.id if dept else None,
            referrer_phone=phone or None)
        extra["code"] = link.code
    db.session.commit()
    return redirect(url_for("feedback.portal_thanks", rating=rating, **extra))


@bp.get("/feedback/thanks")
def portal_thanks():
    rating = request.args.get("rating", type=int) or 5
    ref = request.args.get("ref", "")
    code = (request.args.get("code") or "").strip().upper()
    org = _default_org()
    referral = None
    share_url = wa = None
    if org and code:
        referral = refeng.find_any(org.id, code)
        if referral:
            share_url = refeng.share_url(referral)
            wa = refeng.whatsapp_share_url(org.name, share_url)
    return render_template("feedback_thanks.html", rating=rating, ref=ref, org=org,
                           referral=referral, share_url=share_url, wa=wa)


# ================================================================ STAFF
@bp.get("/feedbacks")
@require_login
def staff_list():
    q = db.session.query(PatientFeedback).filter(PatientFeedback.org_id == current_user.org_id)
    dept = request.args.get("dept", type=int)
    if dept:
        q = q.filter(PatientFeedback.department_id == dept)
    items = q.order_by(PatientFeedback.created_at.desc()).limit(200).all()
    depts = db.session.query(Department).filter_by(org_id=current_user.org_id, active=True).all()
    all_items = db.session.query(PatientFeedback).filter_by(org_id=current_user.org_id).all()
    avg = round(sum(f.rating for f in all_items) / len(all_items), 1) if all_items else None
    return render_template("feedbacks_staff.html", items=items, depts=depts, avg=avg,
                           dept=dept, total=len(all_items))
