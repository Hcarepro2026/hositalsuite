"""Stage A — HIMS Register: open a folder, find a returning patient.

These tests exist because a HIMS desk fails in specific, well-known ways:
duplicate folders, invented birthdays, unreachable next of kin, insurance
patients with no scheme number, and folder numbers colliding when two clerks
register at the same moment. Each of those has a test here.
"""
from datetime import date, timedelta

from app.hims import (next_hospital_number, possible_duplicates, search,
                      validate)
from app.models import Organization, Patient, PatientVisit, db, now_naive

from conftest import csrf, login


def _folder(client, **over):
    """Post a valid folder form, overriding whatever the test cares about."""
    data = {
        "_csrf": csrf(client, "/hims/register"),
        "surname": "ABATAN", "first_name": "Lekan", "sex": "F",
        "age_years": "34", "phone": "08059826879",
        "nok_name": "Mr Abatan", "nok_relationship": "husband",
        "nok_phone": "08033901140", "payer_type": "SELF",
    }
    data.update(over)
    return client.post("/hims/register", data=data, follow_redirects=True)


# ------------------------------------------------------------------ numbering
def test_hospital_numbers_run_in_sequence_per_hospital(client, seeded):
    login(client, "admin")
    _folder(client, surname="ONE", first_name="Patient")
    _folder(client, surname="TWO", first_name="Patient", phone="08065226200")
    nums = sorted(p.hospital_number for p in db.session.query(Patient).all())
    year = now_naive().year
    assert nums == [f"TES/{year}/00001", f"TES/{year}/00002"], nums


def test_hospital_number_is_unique_per_tenant_not_globally(app, seeded):
    """Two hospitals may each have folder 00001 — they must not collide."""
    with app.app_context():
        other = Organization(code="OTHER", name="Another Hospital")
        db.session.add(other)
        db.session.commit()
        n1 = next_hospital_number(db.session.get(Organization, seeded["org"]))
        p = Patient(org_id=seeded["org"], hospital_number=n1, surname="A",
                    first_name="B", sex="F", age_years=20, payer_type="SELF",
                    category="GENERAL")
        db.session.add(p)
        db.session.commit()
        # the other hospital still starts at 1
        assert next_hospital_number(other).endswith("00001")
        # this hospital moves on
        assert next_hospital_number(
            db.session.get(Organization, seeded["org"])).endswith("00002")


def test_number_generator_skips_a_taken_number(app, seeded):
    """If a number already exists the generator must find the next free one."""
    with app.app_context():
        org = db.session.get(Organization, seeded["org"])
        year = now_naive().year
        db.session.add(Patient(org_id=org.id, hospital_number=f"TES/{year}/00001",
                               surname="X", first_name="Y", sex="M", age_years=1,
                               payer_type="SELF", category="CHILD"))
        db.session.commit()
        assert next_hospital_number(org) == f"TES/{year}/00002"


# ------------------------------------------------------------------ validation
def test_age_is_required_but_a_birthday_is_not(client, seeded):
    """Many patients do not know their date of birth — an age must be enough."""
    login(client, "admin")
    r = _folder(client, age_years="", date_of_birth="")
    assert b"Enter either a date of birth or the patient" in r.data
    assert db.session.query(Patient).count() == 0
    _folder(client, age_years="52", date_of_birth="")
    p = db.session.query(Patient).first()
    assert p.age == 52 and p.date_of_birth is None
    assert p.age_display == "52 yrs"


def test_birthday_gives_a_computed_age(client, seeded):
    login(client, "admin")
    dob = date(now_naive().year - 40, 1, 1)
    _folder(client, age_years="", date_of_birth=dob.isoformat())
    p = db.session.query(Patient).first()
    assert p.date_of_birth == dob and p.age in (39, 40)


def test_impossible_dates_are_refused(client, seeded):
    login(client, "admin")
    future = (now_naive().date() + timedelta(days=30)).isoformat()
    r = _folder(client, age_years="", date_of_birth=future)
    assert b"in the future" in r.data
    r = _folder(client, age_years="", date_of_birth="1850-01-01")
    assert b"over 130 years old" in r.data
    r = _folder(client, age_years="", date_of_birth="not a date")
    assert b"Could not read the date of birth" in r.data
    assert db.session.query(Patient).count() == 0


def test_next_of_kin_is_required(client, seeded):
    """In an emergency somebody must be reachable."""
    login(client, "admin")
    r = _folder(client, nok_name="", nok_phone="")
    assert b"Next of kin name is required" in r.data
    assert b"Next of kin phone number is required" in r.data
    assert db.session.query(Patient).count() == 0


def test_insurance_patient_must_have_a_scheme_number(client, seeded):
    """LAHSMA without an enrolment number means Billing cannot claim."""
    login(client, "admin")
    r = _folder(client, payer_type="LAHSMA", payer_number="")
    assert b"needs their scheme/enrolment number" in r.data
    assert db.session.query(Patient).count() == 0
    _folder(client, payer_type="LAHSMA", payer_number="LAH/2026/99881")
    p = db.session.query(Patient).first()
    assert p.payer_type == "LAHSMA" and p.payer_number == "LAH/2026/99881"
    assert "LAHSMA" in p.payer_label


def test_megalex_is_a_payment_route(client, seeded):
    login(client, "admin")
    _folder(client, payer_type="MEGALEX")
    assert db.session.query(Patient).first().payer_type == "MEGALEX"


def test_bad_phone_numbers_are_rejected_not_silently_dropped(client, seeded):
    login(client, "admin")
    r = _folder(client, phone="not-a-number")
    assert b"Enter a valid phone number" in r.data
    r = _folder(client, nok_phone="12")
    assert b"next of kin phone number is not valid" in r.data


def test_genotype_must_be_real(client, seeded):
    login(client, "admin")
    r = _folder(client, genotype="ZZ")
    assert b"Genotype must be one of" in r.data


def test_category_follows_the_age(client, seeded):
    """Triage depends on this, so the system corrects a wrong pick."""
    login(client, "admin")
    _folder(client, surname="CHILD", age_years="6", category="GENERAL")
    _folder(client, surname="ELDER", age_years="72", category="GENERAL",
            phone="08065226200")
    _folder(client, surname="ADULT", age_years="30", category="GENERAL",
            phone="08028327098")
    cats = {p.surname: p.category for p in db.session.query(Patient).all()}
    assert cats == {"CHILD": "CHILD", "ELDER": "ELDERLY", "ADULT": "GENERAL"}
    # an explicit choice is never overridden
    _folder(client, surname="MOTHER", age_years="28", category="ANTENATAL",
            phone="07032322597")
    assert db.session.query(Patient).filter_by(surname="MOTHER").first().category == "ANTENATAL"


# ------------------------------------------------------------------ duplicates
def test_duplicate_folder_is_blocked_until_the_clerk_confirms(client, seeded):
    """The classic HIMS failure: two folders, half the history in each."""
    login(client, "admin")
    _folder(client)
    assert db.session.query(Patient).count() == 1

    r = _folder(client)                               # same name, same phone
    assert b"this patient may already have a folder" in r.data
    assert db.session.query(Patient).count() == 1, "duplicate was created!"

    # the clerk checks, decides it really is a different person, confirms
    _folder(client, confirm_new="1")
    assert db.session.query(Patient).count() == 2


def test_duplicate_check_matches_on_phone_alone(app, seeded):
    """Same phone, different spelling of the name — still worth a warning."""
    with app.app_context():
        db.session.add(Patient(org_id=seeded["org"], hospital_number="X/1",
                               surname="ABATAN", first_name="Lekan", sex="F",
                               age_years=34, phone="08059826879",
                               payer_type="SELF", category="GENERAL"))
        db.session.commit()
        found = possible_duplicates(seeded["org"], "ABATAN-JONES", "Lekanmi",
                                    "08059826879")
        assert len(found) == 1


def test_duplicate_check_is_tenant_isolated(app, seeded):
    with app.app_context():
        other = Organization(code="OTH", name="Other Hospital")
        db.session.add(other)
        db.session.flush()
        db.session.add(Patient(org_id=other.id, hospital_number="OTH/1",
                               surname="ABATAN", first_name="Lekan", sex="F",
                               age_years=34, phone="08059826879",
                               payer_type="SELF", category="GENERAL"))
        db.session.commit()
        assert possible_duplicates(seeded["org"], "ABATAN", "Lekan",
                                   "08059826879") == []


# ------------------------------------------------------------------ search
def test_search_finds_a_returning_patient_every_way_a_clerk_would_try(client, seeded):
    login(client, "admin")
    _folder(client, surname="OGUNLEYE", first_name="Bisi", phone="08062801586")
    p = db.session.query(Patient).first()

    for term in (p.hospital_number, "ogunleye", "OGUNLEYE", "Bisi",
                 "08062801586", "2801586", "ogunleye bisi", "bisi ogunleye"):
        found = search(seeded["org"], term)
        assert len(found) == 1, f"search failed for {term!r}"
        assert found[0].id == p.id

    assert search(seeded["org"], "somebody else entirely") == []
    assert search(seeded["org"], "") == []


def test_search_is_tenant_isolated(app, seeded):
    with app.app_context():
        other = Organization(code="OTH2", name="Other Hospital 2")
        db.session.add(other)
        db.session.flush()
        db.session.add(Patient(org_id=other.id, hospital_number="OTH2/1",
                               surname="SECRET", first_name="Patient", sex="M",
                               age_years=40, payer_type="SELF", category="GENERAL"))
        db.session.commit()
        assert search(seeded["org"], "SECRET") == []
        assert len(search(other.id, "SECRET")) == 1


def test_retired_folders_drop_out_of_search(client, seeded):
    login(client, "admin")
    _folder(client, surname="MISTAKE", first_name="Duplicate")
    p = db.session.query(Patient).first()
    assert len(search(seeded["org"], "MISTAKE")) == 1
    client.post(f"/hims/folder/{p.id}/retire",
                data={"_csrf": csrf(client, "/hims/"), "reason": "duplicate"},
                follow_redirects=True)
    assert search(seeded["org"], "MISTAKE") == []
    # but nothing was deleted
    assert db.session.get(Patient, p.id) is not None


def test_desk_page_shows_results_and_offers_a_new_folder(client, seeded):
    login(client, "admin")
    _folder(client, surname="ADESANYA", first_name="Kemi")
    r = client.get("/hims/?q=adesanya")
    assert b"ADESANYA Kemi" in r.data and b"1 folder found" in r.data
    r = client.get("/hims/?q=nobody-at-all")
    assert b"No folder found" in r.data
    assert b"Open a new folder" in r.data


# ------------------------------------------------------------------ visits
def test_first_visit_and_returning_visit_are_labelled_correctly(client, seeded):
    login(client, "admin")
    _folder(client, start_visit="1", reason="fever for 3 days")
    p = db.session.query(Patient).first()
    assert p.is_returning is True                      # a visit was started
    v = db.session.query(PatientVisit).first()
    assert v.visit_type == "NEW" and v.status == "REGISTERED"
    assert v.reason == "fever for 3 days"
    assert v.payer_type == p.payer_type                # payment route travels with them

    # they come back another day
    v.started_at = now_naive() - timedelta(days=30)
    v.status = "CLOSED"
    db.session.commit()
    client.post(f"/hims/folder/{p.id}/visit",
                data={"_csrf": csrf(client, f"/hims/folder/{p.id}"),
                      "reason": "follow up"}, follow_redirects=True)
    assert db.session.query(PatientVisit).count() == 2
    latest = db.session.query(PatientVisit).order_by(PatientVisit.id.desc()).first()
    assert latest.visit_type == "FOLLOW_UP"


def test_folder_can_be_opened_without_starting_a_visit(client, seeded):
    """Registering ahead of time must not fake an attendance."""
    login(client, "admin")
    _folder(client)                                     # no start_visit
    p = db.session.query(Patient).first()
    assert db.session.query(PatientVisit).count() == 0
    assert p.last_visit_at is None and p.is_returning is False


def test_two_open_visits_on_the_same_day_are_blocked(client, seeded):
    login(client, "admin")
    _folder(client, start_visit="1")
    p = db.session.query(Patient).first()
    r = client.post(f"/hims/folder/{p.id}/visit",
                    data={"_csrf": csrf(client, f"/hims/folder/{p.id}")},
                    follow_redirects=True)
    assert b"already has an open visit today" in r.data
    assert db.session.query(PatientVisit).count() == 1


def test_visit_numbers_are_unique_and_dated(client, seeded):
    login(client, "admin")
    _folder(client, surname="A", start_visit="1")
    _folder(client, surname="B", phone="08065226200", start_visit="1")
    nos = [v.visit_no for v in db.session.query(PatientVisit).all()]
    assert len(set(nos)) == 2
    assert all(n.startswith(f"V{now_naive():%Y%m%d}-") for n in nos)


def test_closing_a_visit_works(client, seeded):
    login(client, "admin")
    _folder(client, start_visit="1")
    v = db.session.query(PatientVisit).first()
    client.post(f"/hims/visit/{v.id}/close",
                data={"_csrf": csrf(client, "/hims/")}, follow_redirects=True)
    assert db.session.get(PatientVisit, v.id).status == "CLOSED"


# ------------------------------------------------------------------ folder page
def test_folder_page_shows_the_clinical_warnings_in_red(client, seeded):
    login(client, "admin")
    _folder(client, allergies="penicillin", genotype="SS",
            chronic_conditions="hypertension")
    p = db.session.query(Patient).first()
    r = client.get(f"/hims/folder/{p.id}")
    body = r.data.decode()
    assert "do not miss" in body
    assert "Allergic to: penicillin" in body
    assert "sickle cell" in body
    assert "hypertension" in body


def test_folder_can_be_edited(client, seeded):
    login(client, "admin")
    _folder(client)
    p = db.session.query(Patient).first()
    client.post(f"/hims/folder/{p.id}/edit", data={
        "_csrf": csrf(client, f"/hims/folder/{p.id}/edit"),
        "surname": "ABATAN", "first_name": "Lekan", "sex": "F", "age_years": "35",
        "phone": "08059826879", "nok_name": "Mr Abatan", "nok_phone": "08033901140",
        "payer_type": "MEGALEX"}, follow_redirects=True)
    p = db.session.get(Patient, p.id)
    assert p.age == 35 and p.payer_type == "MEGALEX"


def test_surname_is_stored_uppercase_so_the_export_matches_the_screen(client, seeded):
    """Found by the browser check: the page showed ABATAN, the CSV said Abatan."""
    login(client, "admin")
    _folder(client, surname="Abatan")
    p = db.session.query(Patient).first()
    assert p.surname == "ABATAN"
    body = client.get("/hims/export").data.decode()
    assert "ABATAN" in body and ",Abatan," not in body
    # and it is still findable however the clerk types it
    assert len(search(seeded["org"], "abatan")) == 1
    assert len(search(seeded["org"], "ABATAN")) == 1


def test_full_name_puts_the_surname_first(app, seeded):
    with app.app_context():
        p = Patient(org_id=seeded["org"], hospital_number="N/1", surname="abatan",
                    first_name="Lekan", other_names="Folake", sex="F", age_years=30,
                    payer_type="SELF", category="GENERAL")
        assert p.full_name == "ABATAN Lekan Folake"


# ------------------------------------------------------------------ permissions
def test_a_patient_cannot_reach_the_register(client, seeded):
    """Folders hold names, phones and addresses — never public."""
    for path in ("/hims/", "/hims/register", "/hims/export"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code in (302, 401, 403), path
        if r.status_code == 302:
            assert "/login" in r.headers["Location"]


def test_management_can_read_but_only_the_desk_can_write(client, seeded):
    login(client, "md")
    assert client.get("/hims/").status_code == 200            # MD may look
    assert client.get("/hims/register").status_code == 403     # but not register
    r = client.post("/hims/register", data={"_csrf": csrf(client, "/hims/"),
                                            "surname": "X", "first_name": "Y"})
    assert r.status_code == 403
    assert db.session.query(Patient).count() == 0


def test_only_senior_staff_can_retire_a_folder(client, seeded):
    login(client, "admin")
    _folder(client)
    p = db.session.query(Patient).first()
    login(client, "hod1")
    r = client.post(f"/hims/folder/{p.id}/retire",
                    data={"_csrf": csrf(client, "/hims/")})
    assert r.status_code == 403
    assert db.session.get(Patient, p.id).active is True


def test_one_hospital_cannot_open_another_hospitals_folder(client, app, seeded):
    with app.app_context():
        other = Organization(code="OTH3", name="Other Hospital 3")
        db.session.add(other)
        db.session.flush()
        p = Patient(org_id=other.id, hospital_number="OTH3/1", surname="THEIRS",
                    first_name="Patient", sex="M", age_years=40,
                    payer_type="SELF", category="GENERAL")
        db.session.add(p)
        db.session.commit()
        pid = p.id
    login(client, "admin")
    assert client.get(f"/hims/folder/{pid}").status_code == 404
    assert client.get(f"/hims/folder/{pid}/edit").status_code == 404


# ------------------------------------------------------------------ export
def test_register_exports_as_csv(client, seeded):
    login(client, "admin")
    _folder(client, surname="EXPORTED", first_name="Patient",
            payer_type="LAHSMA", payer_number="LAH/1")
    r = client.get("/hims/export")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Hospital Number,Surname" in body
    assert "EXPORTED" in body and "LAH/1" in body


# ------------------------------------------------------------------ engine unit tests
def test_validate_trims_and_caps_long_input(app, seeded):
    with app.app_context():
        v, errors = validate({"surname": "A" * 200, "first_name": "B", "sex": "F",
                              "age_years": "30", "nok_name": "N",
                              "nok_phone": "08033901140"}, org_id=seeded["org"])
        assert errors == []
        assert len(v["surname"]) == 80
