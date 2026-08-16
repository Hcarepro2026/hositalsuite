"""Spoken staff announcements — "Mr Tunde, 3 patients are waiting at the dispensary".

WHY THIS EXISTS
---------------
The alert engine could already speak, but only five ADMIN events were ever
registered as speakable (complaint escalated, critical score, inspection
overdue, corrective action overdue, SLA warning). No patient event created an
alert at all, so in practice a nurse never heard anything. The founder reported
it simply as "voice reminders not working" — the plumbing worked; nothing was
ever put through the pipe.

WHAT THIS ADDS
--------------
1. Patient events (queue, dispensary, triage, consulting room) now raise alerts.
2. Each alert carries a `speech` field: a sentence written to be HEARD, not read.
   Notification bodies are written for the eye ("Ticket E-014 assigned"); spoken
   text must address the person and state the action:
       "Nurse Adelowo, 6 patients are waiting to be placed with a doctor."
3. Announcements can be addressed to a PERSON (their own device) or to a
   STATION (a shared screen at the dispensary or nurses' desk).

DESIGN NOTES
------------
* Names are shortened for speech: "Mrs. Tayo Adeyemi" is announced as
  "Mrs Tayo" — a full name read aloud sounds robotic and takes too long.
* Counts are pluralised properly. "1 patients" destroys trust instantly.
* Nothing here ever speaks a clinical instruction. Announcements say WHO is
  waiting and WHERE — never a diagnosis, drug or dose.
"""
from __future__ import annotations

import re

from .models import AppNotification, User, db, now_naive

# Urgency drives the chime, the voice rate and whether quiet hours suppress it.
STANDARD, URGENT, EMERGENCY = "standard", "urgent", "emergency"

# Speakable patient events. Key -> (urgency, subject shown on screen)
PATIENT_ALERTS: dict[str, tuple[str, str]] = {
    "queue_waiting":       (STANDARD, "Patients waiting"),
    "queue_assigned":      (URGENT, "Patient assigned to you"),
    "dispensary_waiting":  (STANDARD, "Patients at the dispensary"),
    "triage_backlog":      (URGENT, "Triage queue building up"),
    "consult_ready":       (URGENT, "Patient ready in your room"),
    "lab_waiting":         (STANDARD, "Patients waiting at the laboratory"),
    "emergency_arrival":   (EMERGENCY, "Emergency arrival"),
    "patient_waiting_long": (URGENT, "Patient waiting too long"),
    # --- HIMS reception desk (Stage A). The point of this app is that a visit
    # FEELS good, so the desk is told out loud when somebody is waiting, when a
    # patient needs help getting through the door, and when a regular returns.
    "reception_waiting":   (STANDARD, "Patients waiting at reception"),
    "patient_registered":  (STANDARD, "Patient registered"),
    "assistance_needed":   (URGENT, "Patient needs assistance"),
    "returning_patient":   (STANDARD, "Returning patient"),
}

_TITLES = ("dr", "mr", "mrs", "miss", "ms", "prof", "pharm", "engr", "cno",
           "adns", "matron", "nurse", "sir", "madam", "alhaji", "alhaja", "chief")

# How a title should be SPOKEN. Initialisms are spaced so the synthesiser reads
# them as letters — "C N O Ogunleye", not "Sno Ogunleye".
_SPOKEN_TITLES = {
    "cno": "C N O", "adns": "A D N S", "dr": "Doctor", "prof": "Professor",
    "mr": "Mr", "mrs": "Mrs", "miss": "Miss", "ms": "Ms", "pharm": "Pharmacist",
    "engr": "Engineer", "matron": "Matron", "nurse": "Nurse", "sir": "Sir",
    "madam": "Madam", "chief": "Chief", "alhaji": "Alhaji", "alhaja": "Alhaja",
}


def speech_name(full_name: str) -> str:
    """'MRS TAYO ADEYEMI' -> 'Mrs Tayo'.

    A full name read by a speech synthesiser sounds robotic and takes too long
    to hear across a busy ward. Keep the title and the first real name.
    """
    raw = " ".join((full_name or "").split())
    if not raw:
        return "Colleague"
    parts = [p for p in re.split(r"\s+", raw) if p]
    cleaned = [p.strip(".") for p in parts if p.strip(".")]

    # Strip EVERY leading title, not just one: "Nurse Mr Adelowo" must not be
    # announced as "Nurse Mr" — that is the person's title twice and no name.
    title = ""
    while cleaned and cleaned[0].lower() in _TITLES:
        if not title:
            title = _SPOKEN_TITLES.get(cleaned[0].lower(), cleaned[0].capitalize())
        cleaned.pop(0)

    first = cleaned[0].capitalize() if cleaned else ""
    out = f"{title} {first}".strip()
    return out or raw


def plural(n: int, one: str, many: str | None = None) -> str:
    """'1 patient' / '3 patients' — never '1 patients'."""
    return f"{n} {one}" if n == 1 else f"{n} {many or one + 's'}"


# ------------------------------------------------------------------ phrasing
def phrase(kind: str, *, name: str = "", count: int = 0, place: str = "",
           patient: str = "", room: str = "", detail: str = "") -> str:
    """The sentence a staff member actually HEARS.

    Written to be spoken: addressed to the person, states the number, the place
    and the action. Deliberately not reused from the on-screen notification.
    """
    who = speech_name(name) if name else "Team"
    if kind == "queue_waiting":
        return (f"{who}, {plural(count, 'patient')} "
                f"{'is' if count == 1 else 'are'} waiting"
                + (f" at {place}" if place else "") + ".")
    if kind == "queue_assigned":
        return (f"{who}, a patient has been assigned to you"
                + (f" in {room}" if room else "")
                + (f". {patient}" if patient else "") + ".")
    if kind == "dispensary_waiting":
        return (f"{who}, you have {plural(count, 'patient')} waiting for "
                f"{'attention' if not detail else detail} at "
                f"{place or 'the drug dispensary'}.")
    if kind == "triage_backlog":
        return (f"{who}, {plural(count, 'patient')} "
                f"{'is' if count == 1 else 'are'} on the queue waiting to be "
                f"placed with a doctor.")
    if kind == "consult_ready":
        return (f"{who}, {patient or 'a patient'} is ready for you"
                + (f" in {room}" if room else "") + ".")
    if kind == "lab_waiting":
        return (f"{who}, {plural(count, 'patient')} "
                f"{'is' if count == 1 else 'are'} waiting at "
                f"{place or 'the laboratory'}.")
    if kind == "emergency_arrival":
        return (f"Attention. Emergency arrival"
                + (f" at {place}" if place else "")
                + f". {detail}" if detail else
                f"Attention. Emergency arrival{' at ' + place if place else ''}. "
                f"Immediate attention required.")
    if kind == "reception_waiting":
        return (f"{who}, {plural(count, 'patient')} "
                f"{'is' if count == 1 else 'are'} waiting at "
                f"{place or 'the reception desk'}. Please attend to them.")
    if kind == "patient_registered":
        return (f"{who}, {patient or 'a patient'} has been registered"
                + (f" and is waiting for {place}" if place else "") + ".")
    if kind == "assistance_needed":
        # The whole reason this app exists: somebody at the door needs a hand.
        return (f"{who}, {patient or 'a patient'} at "
                f"{place or 'reception'} needs help. {detail or 'Please assist them.'}")
    if kind == "returning_patient":
        return (f"{who}, {patient or 'a patient'} is back with us"
                + (f" at {place}" if place else "")
                + ". Please welcome them.")
    if kind == "patient_waiting_long":
        return (f"{who}, {patient or 'a patient'} has been waiting "
                f"{detail or 'a long time'}"
                + (f" at {place}" if place else "") + ". Please attend to them.")
    return detail or f"{who}, please check the system."


# ------------------------------------------------------------------ raising
def to_user(org_id: int, user: User, kind: str, **kw) -> AppNotification | None:
    """Announce to ONE person — heard on whatever device they are signed in to."""
    if user is None or kind not in PATIENT_ALERTS:
        return None
    urgency, subject = PATIENT_ALERTS[kind]
    spoken = phrase(kind, name=user.name, **kw)
    row = AppNotification(
        org_id=org_id, user_id=user.id, channel="inapp",
        template_key=kind, subject=subject, body=spoken,
        entity_type=kw.get("entity_type"), entity_id=kw.get("entity_id"),
        status="SENT")
    db.session.add(row)
    return row


def to_role(org_id: int, role: str, kind: str, *, department_id: int | None = None,
            **kw) -> list[AppNotification]:
    """Announce to everyone in a role — optionally only within one department."""
    q = db.session.query(User).filter(User.org_id == org_id, User.role == role,
                                      User.active.is_(True))
    if department_id is not None:
        q = q.filter(User.department_id == department_id)
    out = []
    for u in q.all():
        row = to_user(org_id, u, kind, **kw)
        if row is not None:
            out.append(row)
    return out


def to_station(org_id: int, kind: str, *, department_id: int | None = None,
               **kw) -> AppNotification:
    """Announce to a SHARED station screen (dispensary tablet, nurses' desk).

    user_id is NULL: station screens poll by department rather than by person,
    so one tablet can cover a whole area without being signed in as anybody.
    """
    urgency, subject = PATIENT_ALERTS.get(kind, (STANDARD, "Announcement"))
    spoken = phrase(kind, **kw)
    row = AppNotification(
        org_id=org_id, user_id=None, channel="station",
        template_key=kind, subject=subject, body=spoken,
        entity_type="department", entity_id=department_id, status="SENT")
    db.session.add(row)
    return row


def urgency_of(template_key: str) -> str:
    return PATIENT_ALERTS.get(template_key, (STANDARD, ""))[0]
