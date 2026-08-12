"""First-run bootstrap & seed data.

`seed_data` builds a complete starter hospital (users, departments, roster,
categories, QR locations). `auto_seed` is the production bootstrap used when
AUTO_SEED=1: it runs ONLY on an empty database (no Organization row) and prints
the initial credentials exactly once to the server log (Render → Logs).
All seeded accounts are flagged must_change_password, so the first login
forces a password change.
"""
from __future__ import annotations

import os
import secrets
from datetime import timedelta

DEFAULT_PASSWORDS = {
    "admin": "Admin#2026!",
    "md": "Mdceo#2026!",
    "am.funke": "Amfunke#2026!",
    "am.emeka": "Amemeka#2026!",
    "hod.medicine": "Hodmed#2026!",
    "hod.surgery": "Hodsurg#2026!",
    "hod.paeds": "Hodpaeds#2026!",
    "hod.emergency": "Hoder#2026!",
    "hod.pharmacy": "Hodpharm#2026!",
    "hod.lab": "Hodlab#2026!",
}


def _pw(username: str, overrides: dict | None) -> str:
    if overrides and username in overrides:
        return overrides[username]
    return DEFAULT_PASSWORDS[username]


def seed_data(app, demo: bool = False, passwords: dict | None = None,
              hospital_name: str | None = None, hospital_code: str | None = None,
              announce: bool = True):
    """Create the starter hospital if (and only if) the database is empty."""
    from .models import (ComplaintCategory, Department, DutyRoster, Organization,
                         QrLocation, Section, Unit, User, db, new_code, now_naive)
    with app.app_context():
        if db.session.query(Organization).first():
            return None
        org = Organization(code=(hospital_code or "HOSP")[:12],
                           name=hospital_name or "Lagos City Teaching Hospital")
        db.session.add(org)
        db.session.flush()

        def user(username, name, role, phone=None, email=None):
            u = User(org_id=org.id, username=username, name=name, role=role,
                     phone=phone, email=email, must_change_password=True)
            u.set_password(_pw(username, passwords))
            db.session.add(u)
            db.session.flush()
            return u

        admin = user("admin", "System Administrator", "SUPER_ADMIN")
        md = user("md", "Dr. Amina Bello", "MD_CEO", phone="2348011112222")
        am1 = user("am.funke", "Funke Adeyemi", "ADMIN_MANAGER", phone="2348022223333")
        am2 = user("am.emeka", "Emeka Okafor", "ADMIN_MANAGER", phone="2348033334444")
        hod_med = user("hod.medicine", "Dr. Tunde Bakare", "HOD", phone="2348044445555")
        hod_surg = user("hod.surgery", "Dr. Ngozi Eze", "HOD")
        hod_paeds = user("hod.paeds", "Dr. Chidi Nwosu", "HOD")
        hod_er = user("hod.emergency", "Dr. Sola Ajayi", "HOD")
        hod_pharm = user("hod.pharmacy", "Pharm. Bisi Lawal", "HOD")
        hod_lab = user("hod.lab", "Mrs. Grace Obi", "HOD")

        dept_specs = [
            ("Internal Medicine", hod_med, [("Outpatient Clinic", ["General OPD", "Specialist Clinic"]),
                                            ("Wards", ["Ward A", "Ward B"])]),
            ("Surgery", hod_surg, [("Theatre Complex", ["Theatre 1", "Theatre 2"]),
                                   ("Surgical Ward", ["Ward C"])]),
            ("Paediatrics", hod_paeds, [("Paediatric Ward", ["PD Ward 1"]),
                                        ("Neonatal Unit", ["NICU"])]),
            ("Emergency", hod_er, [("Accident & Emergency", ["Triage", "Resuscitation Room"])]),
            ("Pharmacy", hod_pharm, [("Dispensary", ["Main Pharmacy", "Emergency Pharmacy"])]),
            ("Laboratory", hod_lab, [("Main Lab", ["Haematology", "Chemistry", "Microbiology"])]),
            ("Records & Billing", None, [("Front Desk", ["Reception", "Billing"])]),
        ]
        for dname, dhod, sections in dept_specs:
            d = Department(org_id=org.id, name=dname, hod_user_id=dhod.id if dhod else None)
            db.session.add(d)
            db.session.flush()
            for sname, units in sections:
                s = Section(org_id=org.id, department_id=d.id, name=sname)
                db.session.add(s)
                db.session.flush()
                for uname in units:
                    db.session.add(Unit(org_id=org.id, department_id=d.id, section_id=s.id, name=uname))

        for cat in ("Staff attitude / conduct", "Long waiting time", "Billing / charges",
                    "Cleanliness / hygiene", "Equipment / facility issue", "Medication / pharmacy",
                    "Communication", "Lost document / records", "Other"):
            db.session.add(ComplaintCategory(org_id=org.id, name=cat))

        for loc in ("Reception", "Ward A", "Emergency Unit", "Outpatient Department", "Pharmacy"):
            db.session.add(QrLocation(org_id=org.id, name=loc, code=new_code(6)))

        today = now_naive().date()
        for i in range(14):
            db.session.add(DutyRoster(org_id=org.id, duty_date=today + timedelta(days=i),
                                      user_id=(am1.id if i % 2 == 0 else am2.id), source="manual"))
        db.session.commit()

        if announce:
            print("=" * 70)
            print("FIRST-RUN SETUP COMPLETE — initial accounts (change at first login):")
            print("-" * 70)
            for uname in DEFAULT_PASSWORDS:
                print(f"  {uname:14s} / {_pw(uname, passwords)}")
            print("=" * 70)

        if demo:
            _seed_demo(app, org, am1, am2)
        return org


def _seed_demo(app, org, am1, am2):
    from . import pdfgen, scoring, services
    from .config import Config
    from .models import (Department, Inspection, InspectionScore, db, new_code,
                         now_naive)
    import os as _os
    import random

    with app.app_context():
        if db.session.query(Inspection).first():
            return
        depts = db.session.query(Department).filter_by(org_id=org.id).all()
        today = now_naive().date()
        random.seed(42)
        for back in range(10, 0, -1):
            day = today - timedelta(days=back)
            dept = depts[back % len(depts)]
            insp = Inspection(
                org_id=org.id, ref=services.next_inspection_ref(org, now_naive()),
                verify_code=new_code(10), inspector_id=(am1.id if back % 2 == 0 else am2.id),
                duty_date=day, department_id=dept.id, status="SUBMITTED",
                started_at=now_naive() - timedelta(days=back),
                submitted_at=now_naive() - timedelta(days=back))
            scores = {n: random.choice([3, 3, 4, 4, 4, 5]) for n in range(1, 6)}
            if dept.name == "Laboratory":
                scores[3] = random.choice([1, 2])
            insp.total_score = scoring.calc_total(scores)
            insp.percent = scoring.calc_percent(insp.total_score)
            insp.rating = scoring.rating_for(insp.total_score)
            insp.critical_count = scoring.critical_count(scores)
            insp.poor_count = scoring.poor_count(scores)
            insp.gps_mode = "optional"
            db.session.add(insp)
            db.session.flush()
            for n in range(1, 6):
                db.session.add(InspectionScore(
                    inspection_id=insp.id, criterion_no=n, score=scores[n],
                    explanation=("Essential equipment not functioning; two analyser "
                                 "machines down since last week." if scores[n] <= 2 else None)))
            try:
                pdf_path = _os.path.join(Config.REPORT_DIR, f"{insp.ref}.pdf")
                pdfgen.build_inspection_pdf(
                    org, insp, {s.criterion_no: s for s in insp.scores}, pdf_path,
                    f"{Config.PUBLIC_BASE_URL}/verify/{insp.verify_code}")
                insp.pdf_path = pdf_path
            except Exception:
                pass
        db.session.commit()


def auto_seed(app):
    """Production bootstrap (AUTO_SEED=1): runs once on an empty database.

    Credentials: from SEED_<USERNAME> env vars when provided, otherwise
    strong random passwords printed ONCE to the server log.
    """
    from .models import Organization, db
    with app.app_context():
        if db.session.query(Organization).first():
            return
    overrides = {}
    for uname in DEFAULT_PASSWORDS:
        env_key = "SEED_" + uname.upper().replace(".", "_").replace("-", "_")
        val = os.environ.get(env_key)
        if val:
            overrides[uname] = val
    if not overrides:
        overrides = {uname: secrets.token_urlsafe(10) + "A1!" for uname in DEFAULT_PASSWORDS}
    seed_data(app, passwords=overrides,
              hospital_name=os.environ.get("SEED_HOSPITAL_NAME"),
              hospital_code=os.environ.get("SEED_HOSPITAL_CODE"))
