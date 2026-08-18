"""Stage C (consulting room) and Stage D (onward routing).

Closes the last two gaps in the patient journey: the doctor could see a queue
but not call anybody in or finish with them, and there was nowhere to send a
patient afterwards.
"""
from datetime import date, timedelta

from app import consulting, triage
from app.models import (Patient, PatientVisit, RosterEntry, User, VisitOnward,
                        db, now_naive)
from tests.conftest import csrf, login

_seq = [0]


def _patient(org_id, surname="Abatan", first="Folake", **kw):
    _seq[0] += 1
    p = Patient(org_id=org_id, hospital_number=f"IJE/2026/{_seq[0]:05d}",
                surname=surname, first_name=first, sex="F", **kw)
    db.session.add(p)
    db.session.flush()
    return p


def _doctor(org_id, username="doc1", name="Dr Ade Ogun"):
    u = User(org_id=org_id, username=username, name=name, role="HOD")
    u.set_password("Passw0rd!x")
    db.session.add(u)
    db.session.flush()
    db.session.add(RosterEntry(org_id=org_id, duty_date=date.today(),
                               user_id=u.id, kind="DUTY", shift="DAY",
                               scope="DEPARTMENT"))
    db.session.flush()
    return u


def _triaged(org_id, patient, doctor, room="Room 1", minutes_ago=10):
    v = PatientVisit(org_id=org_id, patient_id=patient.id,
                     visit_no=f"V-{patient.id}", visit_type="NEW",
                     status="TRIAGED", clinic="OPD", consulting_room=room,
                     doctor_id=doctor.id,
                     started_at=now_naive() - timedelta(minutes=minutes_ago + 5),
                     triaged_at=now_naive() - timedelta(minutes=minutes_ago))
    db.session.add(v)
    db.session.flush()
    return v


# ------------------------------------------------------------------ Stage C
def test_the_doctor_sees_only_their_own_queue(app, seeded):
    with app.app_context():
        org_id = seeded["org"]
        mine = _doctor(org_id, "doc_a", "Dr A")
        theirs = _doctor(org_id, "doc_b", "Dr B")
        _triaged(org_id, _patient(org_id, "Mine", "P"), mine)
        _triaged(org_id, _patient(org_id, "Theirs", "P"), theirs)
        db.session.commit()

        q = consulting.doctor_queue(org_id, mine.id)
        assert len(q) == 1
        assert db.session.get(Patient, q[0].patient_id).surname == "Mine"


def test_calling_a_patient_in_puts_them_in_the_room(app, seeded):
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        v = _triaged(org_id, _patient(org_id), doc)
        db.session.commit()

        assert consulting.call_in(v, doc.id) == ""
        db.session.commit()
        assert v.status == "IN_CONSULTATION"
        assert v.seen_at is not None
        assert consulting.in_consultation(org_id, doc.id).id == v.id


def test_only_one_patient_at_a_time_in_a_room(app, seeded):
    """Two people 'in consultation' with one doctor is a lie about reality."""
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        first = _triaged(org_id, _patient(org_id, "First", "P"), doc)
        second = _triaged(org_id, _patient(org_id, "Second", "P"), doc)
        db.session.commit()

        assert consulting.call_in(first, doc.id) == ""
        db.session.commit()
        err = consulting.call_in(second, doc.id)
        assert "already have a patient" in err
        assert second.status == "TRIAGED"


def test_a_doctor_cannot_call_in_another_doctors_patient(app, seeded):
    with app.app_context():
        org_id = seeded["org"]
        mine = _doctor(org_id, "doc_a", "Dr A")
        theirs = _doctor(org_id, "doc_b", "Dr B")
        v = _triaged(org_id, _patient(org_id), theirs)
        db.session.commit()
        assert "not on your call room queue" in consulting.call_in(v, mine.id)


def test_finishing_with_no_destination_closes_the_visit(app, seeded):
    """Plenty of patients are seen and simply go home."""
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        v = _triaged(org_id, _patient(org_id), doc)
        db.session.commit()
        consulting.call_in(v, doc.id)
        err, steps = consulting.finish(v, doc.id, [])
        db.session.commit()
        assert err == "" and steps == []
        assert v.status == "CLOSED" and v.closed_at is not None


def test_a_consultation_cannot_be_finished_twice(app, seeded):
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        v = _triaged(org_id, _patient(org_id), doc)
        db.session.commit()
        consulting.call_in(v, doc.id)
        consulting.finish(v, doc.id, ["PHARMACY"])
        db.session.commit()
        err, _ = consulting.finish(v, doc.id, ["LABORATORY"])
        assert "already been finished" in err


# ------------------------------------------------------------------ Stage D
def test_a_patient_can_be_sent_to_one_two_or_three_places(app, seeded):
    """The founder's exact words: 'one, two or three out of the following'."""
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        v = _triaged(org_id, _patient(org_id), doc)
        db.session.commit()
        consulting.call_in(v, doc.id)
        err, steps = consulting.finish(
            v, doc.id, ["LABORATORY", "PHARMACY", "BILLING"])
        db.session.commit()

        assert err == ""
        assert len(steps) == 3
        assert v.status == "ONWARD"
        assert {s.destination for s in v.onward_steps} == {
            "LABORATORY", "PHARMACY", "BILLING"}
        assert all(s.status == "PENDING" for s in v.onward_steps)


def test_rubbish_destinations_are_ignored_not_saved(app, seeded):
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        v = _triaged(org_id, _patient(org_id), doc)
        db.session.commit()
        consulting.call_in(v, doc.id)
        _, steps = consulting.finish(v, doc.id,
                                     ["PHARMACY", "'; DROP TABLE--", "NOWHERE"])
        db.session.commit()
        assert [s.destination for s in steps] == ["PHARMACY"]


def test_the_same_desk_is_never_added_twice(app, seeded):
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        v = _triaged(org_id, _patient(org_id), doc)
        db.session.commit()
        consulting.call_in(v, doc.id)
        _, steps = consulting.finish(v, doc.id, ["PHARMACY", "PHARMACY"])
        db.session.commit()
        assert len(steps) == 1


def test_the_visit_closes_only_when_every_desk_is_done(app, seeded):
    """The lab finishing must not send a patient home who still owes pharmacy."""
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        v = _triaged(org_id, _patient(org_id), doc)
        db.session.commit()
        consulting.call_in(v, doc.id)
        _, steps = consulting.finish(v, doc.id, ["LABORATORY", "PHARMACY"])
        db.session.commit()

        closed = consulting.complete_step(steps[0])
        db.session.commit()
        assert closed is False, "the visit closed while pharmacy was still waiting"
        assert v.status == "ONWARD"

        closed = consulting.complete_step(steps[1])
        db.session.commit()
        assert closed is True
        assert v.status == "CLOSED" and v.closed_at is not None


def test_each_desk_sees_only_its_own_patients(app, seeded):
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        v1 = _triaged(org_id, _patient(org_id, "Labonly", "P"), doc)
        v2 = _triaged(org_id, _patient(org_id, "Pharmonly", "P"), doc, room="Room 2")
        db.session.commit()
        consulting.call_in(v1, doc.id)
        consulting.finish(v1, doc.id, ["LABORATORY"])
        db.session.commit()
        consulting.call_in(v2, doc.id)
        consulting.finish(v2, doc.id, ["PHARMACY"])
        db.session.commit()

        assert len(consulting.pending_for(org_id, "LABORATORY")) == 1
        assert len(consulting.pending_for(org_id, "PHARMACY")) == 1
        assert len(consulting.pending_for(org_id, "BILLING")) == 0
        assert consulting.pending_counts(org_id)["LABORATORY"] == 1


def test_completing_a_step_twice_does_not_double_close(app, seeded):
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        v = _triaged(org_id, _patient(org_id), doc)
        db.session.commit()
        consulting.call_in(v, doc.id)
        _, steps = consulting.finish(v, doc.id, ["PHARMACY"])
        db.session.commit()
        assert consulting.complete_step(steps[0]) is True
        db.session.commit()
        assert consulting.complete_step(steps[0]) is False


# ------------------------------------------------------------------ voice
def test_calling_a_patient_in_says_their_name_and_the_room(app, seeded):
    from app.models import AppNotification
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        p = _patient(org_id)
        v = _triaged(org_id, p, doc, room="Room 3")
        db.session.commit()
        consulting.call_in(v, doc.id)
        consulting.announce_called_in(v, p)
        db.session.commit()

        rows = db.session.query(AppNotification).filter_by(
            template_key="consult_call_in").all()
        assert rows, "the patient was never called in"
        assert "folake" in rows[0].body.lower(), (
            "the patient was called by a different name than Reception used")
        assert "room 3" in rows[0].body.lower()


def test_onward_tells_the_patient_every_place_in_one_sentence(app, seeded):
    """Three separate announcements while walking away is impossible to follow."""
    from app.models import AppNotification
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        p = _patient(org_id)
        v = _triaged(org_id, p, doc)
        db.session.commit()
        consulting.call_in(v, doc.id)
        _, steps = consulting.finish(v, doc.id, ["LABORATORY", "PHARMACY"])
        consulting.announce_onward(v, p, steps)
        db.session.commit()

        rows = db.session.query(AppNotification).filter_by(
            template_key="go_onward").all()
        assert len(rows) == 1, "the patient should hear ONE clear instruction"
        said = rows[0].body.lower()
        assert "laboratory" in said and "pharmacy" in said
        assert "then" in said, "the order was not made clear"

        # and each desk is told to expect them
        desks = db.session.query(AppNotification).filter_by(
            template_key="desk_expecting").all()
        assert len(desks) == 2


def test_a_patient_sent_to_emergency_raises_an_emergency_call(app, seeded):
    from app.models import AppNotification
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        p = _patient(org_id)
        v = _triaged(org_id, p, doc)
        db.session.commit()
        consulting.call_in(v, doc.id)
        _, steps = consulting.finish(v, doc.id, ["EMERGENCY"])
        consulting.announce_onward(v, p, steps)
        db.session.commit()
        assert db.session.query(AppNotification).filter_by(
            template_key="emergency_arrival").count() == 1


def test_a_finished_patient_is_told_they_can_go_home(app, seeded):
    from app.models import AppNotification
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        p = _patient(org_id)
        v = _triaged(org_id, p, doc)
        db.session.commit()
        consulting.call_in(v, doc.id)
        consulting.finish(v, doc.id, [])
        consulting.announce_onward(v, p, [])
        db.session.commit()
        rows = db.session.query(AppNotification).filter_by(
            template_key="visit_complete").all()
        assert rows and "done for today" in rows[0].body.lower()


# ------------------------------------------------------------------ NOT an EMR
def test_onward_routing_holds_no_medical_record(app, seeded):
    """'Send to Pharmacy' is a direction to a desk, NOT a prescription."""
    banned = {"prescription", "medication", "drug", "dose", "dosage",
              "diagnosis", "symptoms", "test_type", "test_result", "result",
              "temperature", "blood_pressure", "clinical_note", "findings"}
    columns = {c.name for c in VisitOnward.__table__.columns}
    leaked = banned & columns
    assert not leaked, f"EMR field(s) appeared on onward routing: {leaked}"


# ------------------------------------------------------------------ routes
def _login_as(client, app, seeded, role="ADMIN_MANAGER"):
    with app.app_context():
        u = db.session.query(User).filter_by(org_id=seeded["org"], role=role).first()
        u.must_change_password = False
        db.session.commit()
        return login(client, u.username)


def test_every_consulting_and_onward_route_answers(app, client, seeded):
    """Drives the real pages — catches view bugs the engine tests cannot see."""
    with app.app_context():
        org_id = seeded["org"]
        am = db.session.query(User).filter_by(org_id=org_id,
                                              role="ADMIN_MANAGER").first()
        db.session.add(RosterEntry(org_id=org_id, duty_date=date.today(),
                                   user_id=am.id, kind="DUTY", shift="DAY",
                                   scope="DEPARTMENT"))
        p = _patient(org_id)
        v = PatientVisit(org_id=org_id, patient_id=p.id, visit_no="V-R1",
                         visit_type="NEW", status="TRIAGED", clinic="OPD",
                         consulting_room="Room 1", doctor_id=am.id,
                         triaged_at=now_naive())
        db.session.add(v)
        db.session.commit()
        vid = v.id

    _login_as(client, app, seeded)
    assert client.get("/consulting-room").status_code == 200
    assert client.get("/onward").status_code == 200

    r = client.post(f"/consulting-room/{vid}/call-in",
                    data={"_csrf": csrf(client, "/consulting-room")},
                    follow_redirects=True)
    assert r.status_code == 200
    assert "called in" in r.get_data(as_text=True).lower()

    r = client.post(f"/consulting-room/{vid}/finish",
                    data={"_csrf": csrf(client, "/consulting-room"),
                          "destination": ["LABORATORY", "PHARMACY"],
                          "note": "bring the card back"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert "sent to" in r.get_data(as_text=True).lower()

    with app.app_context():
        steps = db.session.query(VisitOnward).all()
        assert len(steps) == 2
        first_id = steps[0].id

    board = client.get("/onward").get_data(as_text=True)
    assert "ABATAN" in board.upper()   # written register order on screen
    assert "bring the card back" in board

    r = client.post(f"/onward/{first_id}/done",
                    data={"_csrf": csrf(client, "/onward")},
                    follow_redirects=True)
    assert r.status_code == 200
    assert "done at" in r.get_data(as_text=True).lower()

    with app.app_context():
        # one desk done, one still pending -> visit must stay open
        assert db.session.get(PatientVisit, vid).status == "ONWARD"


def test_the_old_triage_room_link_still_works(app, client, seeded):
    """Old bookmarks must not 404 after the page was superseded."""
    _login_as(client, app, seeded)
    r = client.get("/triage/consulting-room", follow_redirects=True)
    assert r.status_code == 200
    assert "call room queue" in r.get_data(as_text=True).lower()


def test_a_patient_is_called_the_SAME_name_at_every_step(app, seeded):
    """Reception says "Folake". Triage and the doctor must not say "Abatan".

    The folder is written SURNAME-first because that is how a register reads,
    but a person is CALLED by their first name. Announcing two different names
    for one patient across one visit is exactly the confusion this app exists
    to remove.
    """
    from app.models import AppNotification
    from app import reception
    with app.app_context():
        org_id = seeded["org"]
        doc = _doctor(org_id)
        p = _patient(org_id, surname="Abatan", first="Folake")
        v = _triaged(org_id, p, doc)
        db.session.commit()

        triage.announce_placement(v, p, None)
        consulting.call_in(v, doc.id)
        consulting.announce_called_in(v, p)
        _, steps = consulting.finish(v, doc.id, ["PHARMACY"])
        consulting.announce_onward(v, p, steps)
        db.session.commit()

        spoken_to_patient = [
            r.body.lower() for r in db.session.query(AppNotification).all()
            if r.template_key in ("consult_call_in", "go_onward", "queue_assigned")
        ]
        assert spoken_to_patient, "nothing was said to the patient"
        for said in spoken_to_patient:
            assert "folake" in said, f"patient called by the wrong name: {said!r}"
