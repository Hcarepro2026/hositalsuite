"""Upgrade batch tests: full CRUD for admin entities + department rosters
with 12h/24h shift systems and 1–2 staff on duty."""
import io
from datetime import timedelta

from app.models import (ComplaintCategory, Department, DeptRosterEntry,
                        QrLocation, User, db, now_naive)

from conftest import csrf, login


# ------------------------------------------------------------------ CRUD (#4)
def test_user_edit_name_role_phone(client, seeded):
    login(client, "admin")
    tok = csrf(client, "/admin/users")
    r = client.post(f"/admin/users/{seeded['hod']}/edit",
                    data={"_csrf": tok, "name": "Hannah HeadOfDept", "role": "HOD",
                          "phone": "2348099990000", "email": "hod@test.org"},
                    follow_redirects=True)
    assert b"updated" in r.data
    u = db.session.get(User, seeded["hod"])
    assert u.name == "Hannah HeadOfDept" and u.phone == "2348099990000"
    # invalid role rejected
    client.post(f"/admin/users/{seeded['hod']}/edit", data={"_csrf": tok, "name": "x", "role": "HACKER"})
    assert db.session.get(User, seeded["hod"]).role == "HOD"
    # HOD cannot edit users
    login(client, "hod1")
    assert client.post(f"/admin/users/{seeded['hod']}/edit",
                       data={"_csrf": tok, "name": "y", "role": "HOD"}).status_code == 403


def test_department_delete_guarded(client, app, seeded):
    login(client, "admin")
    tok = csrf(client, "/admin/structure")
    # Emergency has records? none yet in seeded — add a complaint to create a reference
    from app.models import Complaint
    db.session.add(Complaint(org_id=seeded["org"], ref="TEST-CMP-2026-000099",
                             department_id=seeded["dept"], category="Other",
                             description="x" * 20, phone="0801", status="NEW",
                             sla_hours=24, sla_deadline_at=now_naive()))
    db.session.commit()
    r = client.post(f"/admin/structure/department/{seeded['dept']}/delete",
                    data={"_csrf": tok}, follow_redirects=True)
    assert b"sections/units first" in r.data
    assert db.session.get(Department, seeded["dept"]) is not None
    # a department with children is blocked too
    r = client.post("/admin/structure/department", data={"_csrf": tok, "name": "Empty Dept"})
    new_id = db.session.query(Department).filter_by(name="Empty Dept").first().id
    client.post(f"/admin/structure/department/{new_id}/delete", data={"_csrf": tok},
                follow_redirects=True)
    assert db.session.get(Department, new_id) is None


def test_category_and_qr_lifecycle(client, seeded):
    login(client, "admin")
    tok = csrf(client, "/admin/settings")
    cat = db.session.query(ComplaintCategory).first()
    client.post(f"/admin/settings/categories/{cat.id}/toggle", data={"_csrf": tok})
    assert db.session.get(ComplaintCategory, cat.id).active is False
    # used categories cannot be deleted
    client.post("/complaint/submit", data={"consent": "1", "_csrf": csrf(client, "/complaint"),
                                           "department_id": seeded["dept"],
                                           "category": cat.name,
                                           "description": "A test complaint for deletion guard.",
                                           "phone": "08011112222", "idem": "crud-1"},
                follow_redirects=True)
    client.post(f"/admin/settings/categories/{cat.id}/delete", data={"_csrf": tok},
                follow_redirects=True)
    assert db.session.get(ComplaintCategory, cat.id) is not None
    # unused category deletes fine
    free = db.session.query(ComplaintCategory).filter_by(name="Billing / charges").first()
    client.post(f"/admin/settings/categories/{free.id}/delete", data={"_csrf": tok})
    assert db.session.get(ComplaintCategory, free.id) is None
    # QR location rename + delete
    loc = db.session.query(QrLocation).first()
    client.post(f"/admin/settings/locations/{loc.id}/edit", data={"_csrf": tok, "name": "Main Gate"})
    assert db.session.get(QrLocation, loc.id).name == "Main Gate"
    client.post(f"/admin/settings/locations/{loc.id}/delete", data={"_csrf": tok})
    assert db.session.get(QrLocation, loc.id) is None   # nothing references it yet


# ------------------------------------------------------------------ dept rosters (#5)
def _add(client, dept, date, shift, s1, s2=""):
    return client.post("/dept-roster/add", data={
        "_csrf": csrf(client, f"/dept-roster?dept={dept}"), "department_id": dept,
        "duty_date": date, "shift": shift, "staff1": s1, "staff2": s2},
        follow_redirects=True)


def test_hod_manages_own_dept_only(client, seeded):
    login(client, "hod1")
    day = (now_naive().date() + timedelta(days=2)).isoformat()
    r = _add(client, seeded["dept"], day, "DAY", "Hannah Hod")
    assert db.session.query(DeptRosterEntry).count() == 1
    # another (non-HOD) department: create one, then try — 403
    db.session.add(Department(org_id=seeded["org"], name="Radiology"))
    db.session.commit()
    rad = db.session.query(Department).filter_by(name="Radiology").first()
    assert client.post("/dept-roster/add", data={
        "_csrf": csrf(client, "/dept-roster"), "department_id": rad.id,
        "duty_date": day, "shift": "DAY", "staff1": "Hannah Hod"}).status_code == 403


def test_shift_system_rules(client, seeded):
    login(client, "admin")
    dept = seeded["dept"]
    day = (now_naive().date() + timedelta(days=3)).isoformat()
    # default mode two_12h: 24H rejected
    r = _add(client, dept, day, "24H", "Alice Manager")
    assert b"must be one of" in r.data and db.session.query(DeptRosterEntry).count() == 0
    # single-staff dept: second staff rejected
    r = _add(client, dept, day, "DAY", "Alice Manager", "Bob Manager")
    assert b"ONE staff" in r.data
    # valid entry + duplicate rejected
    _add(client, dept, day, "DAY", "Alice Manager")
    r = _add(client, dept, day, "DAY", "Bob Manager")
    assert b"already exists" in r.data
    assert db.session.query(DeptRosterEntry).count() == 1
    # switch dept to 24h + 2 staff via department edit
    tok = csrf(client, "/admin/structure")
    client.post("/admin/structure/department", data={
        "_csrf": tok, "department_id": dept, "name": "Emergency",
        "roster_mode": "24h", "roster_staff_per_shift": "2"})
    d = db.session.get(Department, dept)
    assert d.roster_mode == "24h" and d.roster_staff_per_shift == 2
    day2 = (now_naive().date() + timedelta(days=4)).isoformat()
    r = _add(client, dept, day2, "24H", "Alice Manager", "Bob Manager")
    e = db.session.query(DeptRosterEntry).filter_by(duty_date=day2).first()
    assert e is not None and e.staff2_user_id is not None
    # now DAY is rejected for a 24h dept
    r = _add(client, dept, (now_naive().date() + timedelta(days=5)).isoformat(), "DAY", "Alice Manager")
    assert b"must be one of" in r.data


def test_dept_roster_edit_delete_import_template(client, seeded):
    login(client, "admin")
    dept = seeded["dept"]
    day = (now_naive().date() + timedelta(days=6)).isoformat()
    _add(client, dept, day, "NIGHT", "Alice Manager")
    e = db.session.query(DeptRosterEntry).first()
    # edit staff
    client.post(f"/dept-roster/{e.id}/edit", data={
        "_csrf": csrf(client, f"/dept-roster?dept={dept}"), "duty_date": day,
        "shift": "NIGHT", "staff1": "Bob Manager"}, follow_redirects=True)
    assert db.session.get(DeptRosterEntry, e.id).staff1_user_id == seeded["am2"]
    # template download
    r = client.get("/dept-roster/template?mode=two_12h")
    assert r.status_code == 200 and b"Date,Shift,Staff1,Staff2" in r.data
    # import one good + one bad row
    csv_body = ("Date,Shift,Staff1,Staff2\n"
                f"{(now_naive().date() + timedelta(days=7)).isoformat()},DAY,Hannah Hod,\n"
                f"not-a-date,DAY,Alice Manager,\n")
    r = client.post("/dept-roster/import", data={
        "_csrf": csrf(client, f"/dept-roster?dept={dept}"), "department_id": dept,
        "file": (io.BytesIO(csv_body.encode()), "roster.csv")},
        content_type="multipart/form-data", follow_redirects=True)
    assert b"1 added" in r.data and b"1 rejected" in r.data
    # delete
    client.post(f"/dept-roster/{e.id}/delete", data={"_csrf": csrf(client, "/dept-roster")})
    assert db.session.get(DeptRosterEntry, e.id) is None
