"""Staff clock-in geo-fence — per hospital, never per-deploy."""
from app import attendance as engine
from app import services
from app.models import Branch, StaffAttendance, User, db
from app.roles import ensure_builtin_roles

from conftest import csrf, login


GATE = (6.5244, 3.3792)          # roughly Lagos
NEAR = (6.5250, 3.3798)          # ~90 m
FAR = (6.5400, 3.4000)           # a few km away


def _pin_main(org_id, lat=GATE[0], lng=GATE[1], radius=200):
    from app.branches import ensure_main_branch
    main = ensure_main_branch(org_id)
    main.lat, main.lng, main.fence_meters = lat, lng, radius
    db.session.commit()
    return main


def test_metres_between_is_sane():
    assert engine.metres_between(*GATE, *GATE) == 0
    near = engine.metres_between(*GATE, *NEAR)
    far = engine.metres_between(*GATE, *FAR)
    assert 50 < near < 200
    assert far > 1000


def test_clock_in_works_when_fence_is_off(client, seeded):
    login(client, "hod1")
    r = client.get("/attendance")
    assert r.status_code == 200
    assert b"I am here" in r.data
    token = csrf(client, "/attendance")
    r = client.post("/attendance/in", data={"_csrf": token, "lat": GATE[0], "lng": GATE[1]},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b"signed in" in r.data.lower() or b"Welcome" in r.data
    hod = db.session.get(User, seeded["hod"])
    open_row = engine.open_row(seeded["org"], hod.id)
    assert open_row is not None and open_row.is_open


def test_required_fence_refuses_far_away(client, seeded):
    services.set_setting(seeded["org"], "attendance_mode", "required")
    _pin_main(seeded["org"])
    hod = db.session.get(User, seeded["hod"])
    row, verdict = engine.clock_in(hod, lat=FAR[0], lng=FAR[1], accuracy_m=10)
    assert row is None
    assert verdict["ok"] is False
    assert "metres" in verdict["reason"] or "m from" in verdict["reason"]


def test_required_fence_allows_inside(client, seeded):
    services.set_setting(seeded["org"], "attendance_mode", "required")
    _pin_main(seeded["org"])
    hod = db.session.get(User, seeded["hod"])
    row, verdict = engine.clock_in(hod, lat=NEAR[0], lng=NEAR[1], accuracy_m=10)
    assert verdict["ok"] is True
    assert row is not None and row.in_inside is True
    db.session.commit()


def test_required_without_pin_does_not_lock_staff(client, seeded):
    services.set_setting(seeded["org"], "attendance_mode", "required")
    hod = db.session.get(User, seeded["hod"])
    row, verdict = engine.clock_in(hod, lat=FAR[0], lng=FAR[1], accuracy_m=10)
    assert verdict["ok"] is True
    assert row is not None


def test_second_clock_in_is_refused(client, seeded):
    hod = db.session.get(User, seeded["hod"])
    engine.clock_in(hod, lat=GATE[0], lng=GATE[1])
    db.session.commit()
    row2, verdict = engine.clock_in(hod, lat=GATE[0], lng=GATE[1])
    assert verdict.get("already") is True
    assert engine.open_row(seeded["org"], hod.id) is not None


def test_clock_out_closes_the_row(client, seeded):
    hod = db.session.get(User, seeded["hod"])
    engine.clock_in(hod)
    db.session.commit()
    row, verdict = engine.clock_out(hod)
    assert verdict["ok"] is True
    assert row.clock_out_at is not None
    assert engine.open_row(seeded["org"], hod.id) is None


def test_hod_cannot_see_the_board(client, seeded):
    login(client, "hod1")
    assert client.get("/attendance/today").status_code == 403


def _png():
    import io
    return (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64), "gate.png")


def test_admin_sees_the_board_and_can_override(client, seeded):
    ensure_builtin_roles(seeded["org"])
    db.session.commit()
    hod = db.session.get(User, seeded["hod"])
    login(client, "admin")
    page = client.get("/attendance/today")
    assert page.status_code == 200
    assert b"Who is at work" in page.data
    token = csrf(client, "/attendance/today")
    r = client.post("/attendance/override", data={
        "_csrf": token, "user_id": hod.id, "help_reason": "NO_GPS",
        "reason": "screen is blank",
        "evidence": _png(),
        "next": "/attendance/today",
    }, content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    open_row = engine.open_row(seeded["org"], hod.id)
    assert open_row is not None
    assert "Phone has no place" in (open_row.override_reason or "")
    assert open_row.help_reason == "NO_GPS"
    assert open_row.evidence_path


def test_settings_are_per_hospital(client, seeded):
    login(client, "admin")
    token = csrf(client, "/admin/settings")
    client.post("/admin/settings", data={
        "_csrf": token,
        "sla_hours": 24,
        "attendance_mode": "required",
        "attendance_radius_m": 150,
        "attendance_lat": "6.5",
        "attendance_lng": "3.3",
        "gps_mode": "optional",
        "fast_track_enabled": "1",
        "fast_track_price": 15000,
    }, follow_redirects=True)
    assert services.get_setting(seeded["org"], "attendance_mode") == "required"
    assert services.get_setting(seeded["org"], "attendance_radius_m") == 150


def test_site_pin_saves(client, seeded):
    from app.branches import ensure_main_branch
    main = ensure_main_branch(seeded["org"])
    db.session.commit()
    login(client, "admin")
    token = csrf(client, "/admin/branches")
    client.post("/admin/branches", data={
        "_csrf": token, "branch_id": main.id, "name": main.name, "code": main.code,
        "lat": "6.524400", "lng": "3.379200", "fence_meters": "180",
    }, follow_redirects=True)
    main = db.session.get(Branch, main.id)
    assert abs(main.lat - 6.5244) < 0.0001
    assert main.fence_meters == 180


def test_menu_has_i_am_here(client, seeded):
    login(client, "hod1")
    page = client.get("/")
    assert b"I am here" in page.data


def test_not_an_emr():
    cols = {c.name for c in StaffAttendance.__table__.columns}
    banned = {"diagnosis", "symptom", "vital", "blood_group", "genotype",
              "allergy", "prescription", "test_result"}
    assert cols & banned == set()


def test_two_hospitals_cannot_see_each_other_clockins(app, seeded):
    from app.models import Organization
    other = Organization(code="OTH", name="Other Hospital")
    db.session.add(other)
    db.session.flush()
    hod = db.session.get(User, seeded["hod"])
    engine.clock_in(hod)
    db.session.commit()
    leaked = (db.session.query(StaffAttendance)
              .filter_by(org_id=other.id).count())
    assert leaked == 0
    mine = (db.session.query(StaffAttendance)
            .filter_by(org_id=seeded["org"]).count())
    assert mine == 1
