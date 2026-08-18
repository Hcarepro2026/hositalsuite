"""Who may see what. ONE definition, used by the menu AND the routes.

WHY THIS FILE EXISTS
--------------------
An HOD of Theatre signed in and saw the System Administrator's menus. The old
template had a single `if role in (SUPER_ADMIN, MD_CEO, ADMIN_MANAGER, HOD)`
block wrapped round nearly every link, so the most junior management role got
the same menu as the person who runs the hospital.

Hiding a link is presentation, not security — every route still enforces its
own `@require_role`. But the menu and the routes must agree, or staff either
see doors they cannot open (confusing) or miss doors they need (worse). This
module is the one place that decides, so the two cannot drift apart.

PRINCIPLE: LEAST PRIVILEGE, BUT NEVER IN THE WAY OF A PATIENT
-------------------------------------------------------------
A clinical HOD gets the things they actually do — see their patients, run
their room, work their department's roster. They do not get the money desks,
the hospital-wide inspection tool, or the administrator's settings.

Front-desk work (Reception, Billing, Pay Point, HIMS) is granted by
DEPARTMENT, not by seniority: the HOD of HIMS runs the HIMS desk; the HOD of
Theatre does not. That is closer to how the hospital really works than any
rule based on rank.
"""
from __future__ import annotations

# Departments whose HOD legitimately works a front-of-house desk. Matched
# loosely (case-insensitive, substring) because hospitals name things
# differently and a receptionist must not be locked out by a spelling.
FRONT_DESK_DEPARTMENTS = (
    "hims", "health information", "medical record", "record",
    "reception", "front desk", "admin", "administration",
)
MONEY_DEPARTMENTS = (
    "billing", "finance", "account", "revenue", "cash", "megalex",
)
TRIAGE_DEPARTMENTS = (
    "triage", "accident", "emergency", "a&e", "nursing", "opd",
    "outpatient", "general outpatient",
)

# Everyone with hospital-wide sight.
MANAGEMENT = ("SUPER_ADMIN", "MD_CEO", "DMD", "DCST", "HEAD_ADMIN_HR")


def _has_department(user) -> bool:
    """Is this person's department actually recorded?"""
    return bool((getattr(getattr(user, "department", None), "name", "") or "").strip())


def _dept_matches(user, needles) -> bool:
    dept = getattr(getattr(user, "department", None), "name", "") or ""
    dept = dept.strip().lower()
    if not dept:
        return False
    return any(n in dept for n in needles)


def permissions_for(user) -> dict:
    """What this person may see. Plain booleans, easy to read in a template."""
    if user is None or not getattr(user, "is_authenticated", False):
        return {k: False for k in (
            "inspections", "reception", "cashdesk", "hims", "triage",
            "consulting", "onward", "tracking", "bookings", "complaints",
            "referrals", "corrective", "roster", "reports", "admin")}

    role = getattr(user, "role", "") or ""
    is_super = role == "SUPER_ADMIN"
    is_mgmt = role in MANAGEMENT
    is_am = role == "ADMIN_MANAGER"
    is_apex = role == "APEX_NURSE"
    is_hod = role == "HOD"

    # A clinical HOD sees patients; a front-desk HOD works the desks.
    front_desk = is_hod and _dept_matches(user, FRONT_DESK_DEPARTMENTS)
    money_desk = is_hod and _dept_matches(user, MONEY_DEPARTMENTS)
    triage_desk = is_hod and _dept_matches(user, TRIAGE_DEPARTMENTS)

    return {
        # Hospital-wide inspection tool: the Admin Manager's own job.
        "inspections": is_super or is_am or role == "MD_CEO",

        # Front of house — by department, not by rank.
        #
        # Management is included because the MD/CEO and DMD must be able to
        # LOOK at any desk; they are stopped from acting by the per-route
        # @require_role, which is the correct place for that distinction.
        #
        # An HOD with NO department set also gets through: in a small hospital
        # the record is often incomplete, and locking a real clerk out of the
        # desk they staff every day is a worse failure than letting a surgeon
        # see a reception list. Set the department to tighten it.
        "reception":   (is_super or is_am or is_mgmt
                        or (is_hod and (front_desk or not _has_department(user)))),
        "cashdesk":    (is_super or is_am or is_mgmt
                        or (is_hod and (money_desk or not _has_department(user)))),
        "hims":        (is_super or is_am or is_mgmt
                        or (is_hod and (front_desk or not _has_department(user)))),

        # Clinical flow. Any HOD may run their own consulting room — that is
        # the point of the room — but only triage/nursing areas run the bench.
        "triage":      is_super or is_am or is_apex or triage_desk or is_mgmt,
        "consulting":  is_super or is_hod or is_apex or is_mgmt,
        "onward":      is_super or is_am or is_apex or is_hod,

        # Measurement and reporting.
        "tracking":    is_super or is_mgmt or is_am or is_apex or is_hod,
        "bookings":    is_super or is_am or is_apex or front_desk or is_mgmt,
        "complaints":  is_super or is_am or is_hod or is_mgmt,
        "referrals":   is_super or is_am or is_mgmt,
        "corrective":  is_super or is_am or is_hod or is_mgmt,
        "roster":      True,                       # everyone checks their duty
        "reports":     is_super or role == "MD_CEO" or is_mgmt,

        # The administrator's settings. Nobody else, ever.
        "admin":       is_super,
    }


# ------------------------------------------------------------------ enforcement
def require_permission(key: str):
    """Route guard using the SAME permission map as the menu.

    Hiding a link is not security. An HOD of Theatre could still type
    /reception/new and reach the desk, because the routes only asked "are you
    an HOD?". This decorator asks the one question that matters — "may THIS
    person use THIS desk?" — and it is the same answer the menu gives, so the
    two can never disagree.
    """
    from functools import wraps

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from flask import abort, redirect, request, url_for
            from flask_login import current_user
            if not getattr(current_user, "is_authenticated", False):
                return redirect(url_for("auth.login", next=request.path))
            if not permissions_for(current_user).get(key, False):
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
