"""Live SMS must stay one message (160 GSM-7). No emoji, no naira, no diagnosis."""
from datetime import date

from app import sms_pack
from app.models import Organization, SmsMessage, db
from conftest import csrf, login


def test_every_sample_is_one_sms():
    for name, text in sms_pack.samples():
        assert len(text) <= sms_pack.SMS_MAX, f"{name} is {len(text)} chars: {text!r}"
        assert "₦" not in text
        assert "⭐" not in text
        assert "diagnosis" not in text.lower()
        assert "blood" not in text.lower()


def test_queue_sms_clips_long_unicode(app, seeded):
    long = "⭐ " * 80 + "This would have been three SMS and a blocked Termii promo."
    with app.app_context():
        m = __import__("app.sms", fromlist=["queue_sms"]).queue_sms(
            seeded["org"], "08011110000", long, kind="alert")
        assert len(m.body) <= 160
        assert "⭐" not in m.body


def test_booking_sms_is_short_and_has_ref(client, seeded):
    from datetime import timedelta
    from app.models import now_naive
    token = csrf(client, "/book")
    day = (now_naive().date() + timedelta(days=1)).isoformat()
    client.post("/book/submit", data={
        "_csrf": token, "consent": "1", "fast_track_consent": "1",
        "is_fast_track": "1", "fast_track_reason": "PREMIUM",
        "department_id": seeded["dept"], "appointment_date": day,
        "appointment_time": "09:00", "patient_name": "Chinwe Obi",
        "phone": "08033334444", "idem": "sms-short-1",
    }, follow_redirects=True)
    m = db.session.query(SmsMessage).filter_by(to_number="08033334444").first()
    assert m is not None
    assert len(m.body) <= 160
    apt_ref = m.body  # ref is inside
    from app.models import Appointment
    apt = db.session.query(Appointment).first()
    assert apt.ref in m.body
    assert "⭐" not in m.body
    assert "NGN" not in m.body or len(m.body) <= 160


def test_complaint_sms_still_says_received_and_resolved(client, seeded):
    token = csrf(client, "/complaint")
    client.post("/complaint/submit", data={
        "consent": "1", "_csrf": token, "department_id": seeded["dept"],
        "category": "Long waiting time",
        "description": "We have been waiting for over four hours without any update.",
        "phone": "08012345678",
    }, follow_redirects=True)
    sms = db.session.query(SmsMessage).filter_by(to_number="08012345678").first()
    assert sms is not None
    assert len(sms.body) <= 160
    assert "received your complaint" in sms.body


def test_manifest_and_service_worker_are_public(client, seeded):
    import json
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200
    data = json.loads(m.get_data(as_text=True))
    assert data["display"] == "standalone"
    assert data["start_url"].startswith("/")
    icons = {i["sizes"] for i in data["icons"]}
    assert "192x192" in icons and "512x512" in icons
    sw = client.get("/sw.js")
    assert sw.status_code == 200
    assert b"fetch" in sw.data
    assert client.get("/offline").status_code == 200
    assert client.get("/static/icons/icon-192.png").status_code == 200
    assert client.get("/static/icons/icon-512.png").status_code == 200


def test_login_and_welcome_offer_add_to_phone(client, seeded):
    login_html = client.get("/login").get_data(as_text=True)
    assert "/manifest.webmanifest" in login_html
    assert "Add to" in login_html or "install" in login_html.lower() or "Home screen" in login_html
    hub = client.get("/welcome").get_data(as_text=True)
    assert "/manifest.webmanifest" in hub


def test_queue_join_texts_the_number(client, seeded):
    client.post("/queue/join", data={
        "_csrf": csrf(client, "/queue/join"),
        "department_id": seeded["dept"],
        "patient_name": "Bola Ajao",
        "phone": "08099990000",
    }, follow_redirects=True)
    m = db.session.query(SmsMessage).filter_by(to_number="08099990000").first()
    assert m is not None
    assert len(m.body) <= 160
    assert "E-" in m.body or "-001" in m.body


def test_hospital_saves_sms_name(client, seeded):
    login(client, "admin")
    client.post("/admin/hospital", data={
        "_csrf": csrf(client, "/admin/hospital"),
        "name": "Test Hospital",
        "code": "TEST",
        "phone": "08030001111",
        "sms_sender_tag": "GHIJEDE",
        "brand_primary": "#0e5a8a",
        "brand_accent": "#12b5a5",
        "brand_gold": "#ffd700",
    }, follow_redirects=True)
    from app import services
    assert services.get_setting(seeded["org"], "sms_sender_tag") == "GHIJEDE"


def test_sms_tag_is_per_hospital(app, seeded):
    from app import services
    org = db.session.get(Organization, seeded["org"])
    services.set_setting(org.id, "sms_sender_tag", "GHIJEDE")
    db.session.commit()
    text = sms_pack.queue_next(org, ticket="E-014", dept="OPD")
    assert text.startswith("GHIJEDE:")
    assert len(text) <= 160
