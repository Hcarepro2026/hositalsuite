"""Wave A tests: patient feedback + service-recovery routing (§7, §8)."""
from app.models import AppNotification, Complaint, PatientFeedback, db

from conftest import csrf, login


def _rate(client, rating, **over):
    data = {"_csrf": csrf(client, "/feedback"), "rating": str(rating)}
    data.update({k: str(v) for k, v in over.items()})
    return client.post("/feedback/submit", data=data, follow_redirects=True)


def test_feedback_portal_public(client, seeded):
    r = client.get("/feedback")
    assert r.status_code == 200 and b"How was your experience" in r.data


def test_positive_feedback_thanks_and_refer_prompts(client, seeded):
    r = _rate(client, 5, comment="The nurses were wonderful and very quick.",
              department_id=seeded["dept"])
    assert b"glad you had a good experience" in r.data
    assert b"BOOK ANOTHER VISIT" in r.data and b"REFER A FRIEND" in r.data
    fb = db.session.query(PatientFeedback).first()
    assert fb.rating == 5 and fb.status == "NEW"
    # positive feedback must NOT create a complaint
    assert db.session.query(Complaint).count() == 0


def test_low_feedback_routes_instantly_to_service_recovery(client, seeded):
    r = _rate(client, 1, comment="Nobody attended to my mother for hours.",
              department_id=seeded["dept"], phone="08044445555")
    assert b"sent" in r.data and b"immediately" in r.data
    fb = db.session.query(PatientFeedback).first()
    c = db.session.query(Complaint).first()
    assert fb.status == "ROUTED" and fb.complaint_id == c.id
    assert "rated their experience 1/5" in c.description
    assert c.status == "NEW"
    # routed to HOD + AM on duty like a complaint
    notes = db.session.query(AppNotification).filter(
        AppNotification.template_key.in_(("complaint_new_admin", "complaint_new_hod"))).all()
    recipients = {n.user_id for n in notes}
    assert seeded["am"] in recipients and seeded["hod"] in recipients
    # reference shown to the patient for tracking
    assert c.ref.encode() in r.data


def test_neutral_feedback_not_routed(client, seeded):
    _rate(client, 3, department_id=seeded["dept"])
    fb = db.session.query(PatientFeedback).first()
    assert fb.status == "NEW"
    assert db.session.query(Complaint).count() == 0


def test_invalid_rating_rejected(client, seeded):
    r = _rate(client, 9)
    assert db.session.query(PatientFeedback).count() == 0


def test_staff_see_feedback_and_satisfaction(client, seeded):
    _rate(client, 5, department_id=seeded["dept"])
    _rate(client, 2, department_id=seeded["dept"])
    login(client, "md")
    r = client.get("/feedbacks")
    assert r.status_code == 200
    assert b"Average satisfaction" in r.data
    assert b"Recovery ticket" in r.data  # low rating shows its linked ticket
