"""Reception — the front door of the patient flow.

Guards the walk the founder described:

    Reception -> Billing -> Megalex/Pay-Point -> HIMS folder -> Triage

and the rule that the patient answers each question ONCE.
"""
from app import reception
from app.models import Patient, ReceptionIntake, db


def _good_form(**over):
    form = {
        "surname": "Abatan", "first_name": "Folake", "sex": "F",
        "age_years": "34", "occupation": "Trader",
        "phone": "08031234567", "address": "12 Ijede Road, Ikorodu",
        "nok_name": "Tunde Abatan", "nok_phone": "08039876543",
        "nok_relationship": "Husband",
        "payer_type": "SELF", "payer_number": "", "payer_name": "",
        "preferred_lang": "yo", "care_note": "Travels from Ikorodu",
        "needs_blood_sugar": "1",
    }
    form.update(over)
    return _Form(form)


class _Form(dict):
    """Mimics a Werkzeug MultiDict closely enough for clean_form."""

    def __init__(self, data, assistance=None):
        super().__init__(data)
        self._assistance = assistance or []

    def getlist(self, key):
        return self._assistance if key == "assistance" else []


# ------------------------------------------------------------------ validation
def test_next_of_kin_needs_name_phone_and_relationship(app, seeded):
    """All three, because a name with no number helps nobody in an emergency."""
    for missing in ("nok_name", "nok_phone", "nok_relationship"):
        _, errors = reception.clean_form(_good_form(**{missing: ""}))
        assert any("next of kin" in e.lower() for e in errors), \
            f"missing {missing} was accepted"


def test_insurance_route_demands_a_policy_number(app, seeded):
    """Billing cannot claim against 'LAHSMA, number unknown'."""
    for scheme in ("LAHSMA", "NHIS", "HMO"):
        _, errors = reception.clean_form(_good_form(payer_type=scheme, payer_number=""))
        assert any(scheme in e for e in errors), f"{scheme} accepted with no number"
    # ...but self-payers must not be blocked by that rule.
    _, errors = reception.clean_form(_good_form(payer_type="SELF", payer_number=""))
    assert not errors, errors


def test_a_stated_age_is_accepted_without_inventing_a_birthday(app, seeded):
    values, errors = reception.clean_form(_good_form(age_years="70"))
    assert not errors
    assert values["age_years"] == 70


def test_special_needs_are_captured_at_reception(app, seeded):
    form = _Form(dict(_good_form()), assistance=["WHEELCHAIR", "HEARING"])
    values, errors = reception.clean_form(form)
    assert not errors
    assert "WHEELCHAIR" in values["assistance"]
    assert "HEARING" in values["assistance"]


def test_rubbish_assistance_codes_are_ignored(app, seeded):
    form = _Form(dict(_good_form()), assistance=["WHEELCHAIR", "'; DROP TABLE--"])
    values, _ = reception.clean_form(form)
    assert values["assistance"] == "WHEELCHAIR"


# ------------------------------------------------------------------ the walk
def test_the_walk_runs_reception_to_triage(app, seeded, client):
    """Every stage, in order, with the timestamps stamped as it goes."""
    with app.app_context():
        org_id = seeded["org"]
        values, errors = reception.clean_form(_good_form())
        assert not errors
        intake = reception.create_intake(org_id, values)
        db.session.commit()

        assert intake.stage == "RECEPTION"
        reception.advance(intake, "BILLING", ref="BILL-1")
        assert intake.stage == "BILLING"
        # billed_at is stamped when the bill is actually RAISED (on leaving the
        # billing desk), not when the patient is merely sent there — otherwise
        # "how long does Billing take?" measures the wrong thing.
        reception.advance(intake, "PAYMENT", ref="BILL-1")
        assert intake.stage == "PAYMENT"
        assert intake.billed_at is not None
        assert intake.bill_ref == "BILL-1", "the bill number was discarded"
        reception.advance(intake, "PAID", ref="RCT-9")
        assert intake.stage == "PAID" and intake.paid_at is not None
        assert intake.payment_ref == "RCT-9"
        reception.advance(intake, "REGISTERED")
        assert intake.registered_at is not None


def test_folder_values_carry_everything_so_nothing_is_asked_twice(app, seeded):
    """The whole point of Reception: HIMS must not re-ask the patient."""
    with app.app_context():
        form = _Form(dict(_good_form()), assistance=["WHEELCHAIR"])
        values, _ = reception.clean_form(form)
        intake = reception.create_intake(seeded["org"], values)
        db.session.commit()

        carried = reception.folder_values(intake)
        assert carried["surname"] == "Abatan"
        assert carried["nok_relationship"] == "Husband"
        assert carried["nok_phone"]
        assert carried["preferred_lang"] == "yo"
        assert "WHEELCHAIR" in carried["assistance"]
        assert carried["occupation"] == "Trader"
        assert carried["address"]


def test_reception_holds_no_medical_record(app, seeded):
    """This app is NOT an EMR. Reception must never grow clinical columns.

    'Blood sugar test' is a BILLING LINE and a Triage instruction. If a column
    ever appears here that could store a reading, a diagnosis or a symptom,
    this test fails the build.
    """
    banned = {"blood_sugar_value", "blood_sugar_result", "glucose", "reading",
              "diagnosis", "symptoms", "complaint", "temperature", "bp",
              "blood_pressure", "pulse", "weight", "allergies", "genotype",
              "blood_group", "medication", "prescription", "test_result"}
    columns = {c.name for c in ReceptionIntake.__table__.columns}
    leaked = banned & columns
    assert not leaked, f"EMR field(s) appeared on the Reception intake: {leaked}"


# ------------------------------------------------------------------ voice
def test_arrival_is_announced_and_special_needs_get_their_own_urgent_call(app, seeded):
    """A wheelchair request buried inside a routine line is a request nobody acts on."""
    from app.models import AppNotification
    with app.app_context():
        form = _Form(dict(_good_form()), assistance=["WHEELCHAIR"])
        values, _ = reception.clean_form(form)
        intake = reception.create_intake(seeded["org"], values)
        reception.announce_arrival(intake)
        db.session.commit()

        rows = db.session.query(AppNotification).filter_by(org_id=seeded["org"]).all()
        kinds = {r.template_key for r in rows}
        assert "reception_arrival" in kinds
        assert "assistance_needed" in kinds, "special needs did not raise their own call"
        urgent = [r for r in rows if r.template_key == "assistance_needed"]
        assert "wheelchair" in urgent[0].body.lower()


def test_each_stage_calls_the_patient_onward_by_name(app, seeded):
    from app.models import AppNotification
    with app.app_context():
        values, _ = reception.clean_form(_good_form())
        intake = reception.create_intake(seeded["org"], values)
        for stage in ("BILLING", "PAYMENT", "PAID", "REGISTERED"):
            reception.advance(intake, stage)
            reception.announce_stage(intake)
        db.session.commit()

        said = " ".join(r.body for r in db.session.query(AppNotification)
                        .filter_by(org_id=seeded["org"]).all()).lower()
        assert "billing" in said
        assert "paying point" in said
        assert "triage" in said
        # speech_name() deliberately shortens to title + first name: a full
        # name read by a synthesiser is slow and robotic across a noisy hall.
        assert "folake" in said, "the patient is never called by name"


# ------------------------------------------------------------------ the desk
def test_desk_lists_who_is_waiting(app, seeded):
    with app.app_context():
        values, _ = reception.clean_form(_good_form())
        reception.create_intake(seeded["org"], values)
        db.session.commit()
        assert len(reception.waiting(seeded["org"])) == 1
        assert reception.counts_by_stage(seeded["org"])["RECEPTION"] == 1


def test_a_patient_who_leaves_never_becomes_a_folder(app, seeded):
    """Somebody quoted a fee who walks out must not consume a hospital number."""
    with app.app_context():
        values, _ = reception.clean_form(_good_form())
        intake = reception.create_intake(seeded["org"], values)
        intake.stage = "CANCELLED"
        db.session.commit()

        assert db.session.query(Patient).count() == 0
        assert intake.patient_id is None
        assert intake not in reception.waiting(seeded["org"])


# ------------------------------------------------------------------ the routes
# The unit tests above exercise the ENGINE. These drive the actual HTTP routes,
# because a view can be broken (a wrong audit() signature, a bad template name)
# while every engine test still passes. That exact bug shipped once — a 500 on
# POST /reception/new that no unit test could see.
def _login_desk(client, app, seeded):
    from tests.conftest import login
    with app.app_context():
        from app.models import User
        u = db.session.query(User).filter_by(org_id=seeded["org"],
                                             role="ADMIN_MANAGER").first()
        u.must_change_password = False
        db.session.commit()
        username = u.username
    return login(client, username)


def _post_new(client, **over):
    from tests.conftest import csrf
    data = {
        "_csrf": csrf(client, "/reception/new"),
        "surname": "Abatan", "first_name": "Folake", "sex": "F",
        "age_years": "72", "occupation": "Trader", "phone": "08031234567",
        "address": "12 Ijede Road", "nok_name": "Tunde Abatan",
        "nok_phone": "08039876543", "nok_relationship": "Husband",
        "payer_type": "LAHSMA", "payer_number": "LAS/2026/771",
        "preferred_lang": "yo", "assistance": "WHEELCHAIR",
        "care_note": "Travels from Ikorodu", "needs_blood_sugar": "1",
    }
    data.update(over)
    return client.post("/reception/new", data=data, follow_redirects=True)


def test_every_reception_route_answers_without_a_server_error(app, client, seeded):
    """Drives the whole walk over HTTP. Catches view-layer bugs unit tests miss."""
    _login_desk(client, app, seeded)
    from tests.conftest import csrf

    assert client.get("/reception/").status_code == 200
    assert client.get("/reception/new").status_code == 200

    r = _post_new(client)
    assert r.status_code == 200, f"POST /reception/new returned {r.status_code}"
    assert "taken in" in r.get_data(as_text=True).lower()

    with app.app_context():
        intake = db.session.query(ReceptionIntake).one()
        iid = intake.id

    for step in ("to-billing", "to-payment", "paid"):
        r = client.post(f"/reception/{iid}/{step}",
                        data={"_csrf": csrf(client, "/reception/")},
                        follow_redirects=True)
        assert r.status_code == 200, f"/{step} returned {r.status_code}"

    r = client.post(f"/reception/{iid}/open-folder",
                    data={"_csrf": csrf(client, "/reception/")},
                    follow_redirects=True)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Folder" in body and "Triage" in body

    with app.app_context():
        patient = db.session.query(Patient).one()
        assert patient.hospital_number
        # Everything taken at Reception must be on the folder, untyped again.
        assert patient.nok_relationship == "Husband"
        assert patient.payer_number == "LAS/2026/771"
        assert "WHEELCHAIR" in (patient.assistance or "")
        assert patient.preferred_lang == "yo"
        assert patient.occupation == "Trader"
        refreshed = db.session.get(ReceptionIntake, iid)
        assert refreshed.stage == "REGISTERED"
        assert refreshed.patient_id == patient.id


def test_a_folder_is_never_opened_before_payment(app, client, seeded):
    """The founder's order: pay first, then HIMS opens the folder."""
    from tests.conftest import csrf
    _login_desk(client, app, seeded)
    _post_new(client)
    with app.app_context():
        iid = db.session.query(ReceptionIntake).one().id

    r = client.post(f"/reception/{iid}/open-folder",
                    data={"_csrf": csrf(client, "/reception/")},
                    follow_redirects=True)
    assert "has not paid" in r.get_data(as_text=True).lower()
    with app.app_context():
        assert db.session.query(Patient).count() == 0


def test_the_same_intake_cannot_produce_two_folders(app, client, seeded):
    from tests.conftest import csrf
    _login_desk(client, app, seeded)
    _post_new(client)
    with app.app_context():
        iid = db.session.query(ReceptionIntake).one().id
    for step in ("to-billing", "to-payment", "paid"):
        client.post(f"/reception/{iid}/{step}",
                    data={"_csrf": csrf(client, "/reception/")}, follow_redirects=True)

    client.post(f"/reception/{iid}/open-folder",
                data={"_csrf": csrf(client, "/reception/")}, follow_redirects=True)
    client.post(f"/reception/{iid}/open-folder",
                data={"_csrf": csrf(client, "/reception/")}, follow_redirects=True)

    with app.app_context():
        assert db.session.query(Patient).count() == 1, \
            "a double-click opened two folders and burned a hospital number"


def test_a_bad_form_is_explained_not_crashed(app, client, seeded):
    _login_desk(client, app, seeded)
    r = _post_new(client, nok_relationship="", surname="")
    assert r.status_code == 400
    body = r.get_data(as_text=True).lower()
    assert "surname is required" in body
    assert "relationship" in body


# ------------------------------------------------------------------ the contract
# RECEPTION MUST NEVER COLLECT SOMETHING HIMS WILL REJECT.
#
# This was a real defect, found by walking a patient through rather than by a
# unit test: age was optional at Reception but REQUIRED by HIMS. A receptionist
# could take the details, send the patient to Billing, take their money at the
# Paying Point — and only then be told the folder could not be opened. The
# patient had already paid. These tests make that class of bug impossible.

def test_age_is_required_at_reception_because_hims_demands_it(app, seeded):
    _, errors = reception.clean_form(_good_form(age_years=""))
    assert any("age is required" in e.lower() for e in errors), \
        "Reception accepted a patient HIMS will later refuse"


def test_everything_reception_collects_is_accepted_by_hims(app, seeded):
    """The contract between the two desks, enforced.

    Whatever Reception considers a valid patient, HIMS must be able to turn
    into a folder. If these two ever disagree again, this fails the build
    instead of failing a patient who has already paid.
    """
    from app import hims
    with app.app_context():
        values, errors = reception.clean_form(_good_form())
        assert not errors, errors
        intake = reception.create_intake(seeded["org"], values)
        db.session.commit()

        _, hims_errors = hims.validate(reception.folder_values(intake),
                                       org_id=seeded["org"])
        assert not hims_errors, (
            "Reception accepted details that HIMS rejects — the patient would "
            f"be blocked AFTER paying: {hims_errors}")


def test_the_minimum_reception_form_still_opens_a_folder(app, seeded):
    """The least a receptionist can type must still work end to end."""
    from app import hims
    minimal = _Form({
        "surname": "Bello", "first_name": "Musa", "sex": "M", "age_years": "40",
        "nok_name": "Aisha Bello", "nok_phone": "08031112222",
        "nok_relationship": "Wife", "payer_type": "SELF",
    })
    with app.app_context():
        values, errors = reception.clean_form(minimal)
        assert not errors, errors
        intake = reception.create_intake(seeded["org"], values)
        db.session.commit()
        _, hims_errors = hims.validate(reception.folder_values(intake),
                                       org_id=seeded["org"])
        assert not hims_errors, hims_errors
