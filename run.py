#!/usr/bin/env python3
"""Hospital Admin Manager Suite — entry point & CLI.

Usage:
  python run.py                  # start the web server (with scheduler)
  python run.py seed             # first-time setup: hospital, users, structure, roster
  python run.py demo             # seed + sample inspection/complaint history for evaluation
  python run.py tick             # run one scheduler pass (reminders, SLA, WhatsApp queue)
  python run.py backup           # create a database backup now
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta

from app.config import Config

os.environ.setdefault("DISABLE_SCHEDULER", "0")


def seed(demo: bool = False):
    from app import create_app
    from app.models import (ComplaintCategory, Department, DutyRoster, Organization,
                            QrLocation, Section, Unit, User, db, new_code, now_naive)
    app = create_app(scheduler=False)
    with app.app_context():
        if db.session.query(Organization).first():
            print("Already seeded. Use the running application to manage configuration.")
            return
        org = Organization(code="HOSP", name="Lagos City Teaching Hospital")
        db.session.add(org)
        db.session.flush()

        def user(username, name, role, pw, phone=None, email=None):
            u = User(org_id=org.id, username=username, name=name, role=role,
                     phone=phone, email=email, must_change_password=True)
            u.set_password(pw)
            db.session.add(u)
            db.session.flush()
            return u

        admin = user("admin", "System Administrator", "SUPER_ADMIN", "Admin#2026!")
        md = user("md", "Dr. Amina Bello", "MD_CEO", "Mdceo#2026!", phone="2348011112222",
                  email="md@lcth.example.org")
        am1 = user("am.funke", "Funke Adeyemi", "ADMIN_MANAGER", "Amfunke#2026!",
                   phone="2348022223333", email="funke@lcth.example.org")
        am2 = user("am.emeka", "Emeka Okafor", "ADMIN_MANAGER", "Amemeka#2026!",
                   phone="2348033334444")
        hod_med = user("hod.medicine", "Dr. Tunde Bakare", "HOD", "Hodmed#2026!", phone="2348044445555")
        hod_surg = user("hod.surgery", "Dr. Ngozi Eze", "HOD", "Hodsurg#2026!")
        hod_paeds = user("hod.paeds", "Dr. Chidi Nwosu", "HOD", "Hodpaeds#2026!")
        hod_er = user("hod.emergency", "Dr. Sola Ajayi", "HOD", "Hoder#2026!")
        hod_pharm = user("hod.pharmacy", "Pharm. Bisi Lawal", "HOD", "Hodpharm#2026!")
        hod_lab = user("hod.lab", "Mrs. Grace Obi", "HOD", "Hodlab#2026!")

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

        # two-week roster alternating the two Admin Managers
        today = now_naive().date()
        for i in range(14):
            db.session.add(DutyRoster(org_id=org.id, duty_date=today + timedelta(days=i),
                                      user_id=(am1.id if i % 2 == 0 else am2.id), source="manual"))

        db.session.commit()
        print("=" * 64)
        print("Seeded hospital:", org.name)
        print("-" * 64)
        print("Super Admin   : admin        / Admin#2026!")
        print("MD/CEO        : md           / Mdceo#2026!")
        print("Admin Manager : am.funke     / Amfunke#2026!")
        print("Admin Manager : am.emeka     / Amemeka#2026!")
        print("HODs          : hod.medicine / Hodmed#2026!  (+ 5 others)")
        print("=" * 64)
        print("Change all passwords before production use.")

        if demo:
            _seed_demo(app, org, am1, am2, hod_med)


def _seed_demo(app, org, am1, am2, hod_med):
    """Optional evaluation data: historical inspections + one complaint."""
    from app import pdfgen, scoring, services
    from app.models import (Complaint, ComplaintStatusHistory, Department, Inspection,
                            InspectionScore, db, new_code, now_naive)
    from app.config import Config
    import os as _os

    with app.app_context():
        if db.session.query(Inspection).first():
            print("Demo data already present.")
            return
        depts = db.session.query(Department).filter_by(org_id=org.id).all()
        today = now_naive().date()
        import random
        random.seed(42)
        for back in range(10, 0, -1):
            day = today - timedelta(days=back)
            dept = depts[back % len(depts)]
            insp = Inspection(
                org_id=org.id, ref=services.next_inspection_ref(org, now_naive()),
                verify_code=new_code(10), inspector_id=(am1.id if back % 2 == 0 else am2.id),
                duty_date=day, department_id=dept.id, status="SUBMITTED",
                started_at=now_naive() - timedelta(days=back), submitted_at=now_naive() - timedelta(days=back))
            scores = {n: random.choice([3, 3, 4, 4, 4, 5]) for n in range(1, 6)}
            if dept.name == "Laboratory":
                scores[3] = random.choice([1, 2])  # recurring equipment problem
                if scores[3] <= 2:
                    pass
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
                    explanation=("Essential equipment not functioning; two analyser machines down since last week."
                                 if scores[n] <= 2 else None)))
            # generate a PDF for the archive
            try:
                pdf_path = _os.path.join(Config.REPORT_DIR, f"{insp.ref}.pdf")
                pdfgen.build_inspection_pdf(org, insp,
                                            {s.criterion_no: s for s in insp.scores},
                                            pdf_path, f"{Config.PUBLIC_BASE_URL}/verify/{insp.verify_code}")
                insp.pdf_path = pdf_path
            except Exception:
                pass
        db.session.commit()
        print("Demo inspection history created (10 days).")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "seed":
        seed(demo=False)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        seed(demo=True)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "tick":
        os.environ["DISABLE_SCHEDULER"] = "1"
        from app import create_app
        from app.scheduler import tick
        app = create_app(scheduler=False)
        tick(app)
        print("Scheduler pass complete.")
        return
    if len(sys.argv) > 1 and sys.argv[1] == "backup":
        from app import create_app
        from app.scheduler import job_nightly_backup
        app = create_app(scheduler=False)
        with app.app_context():
            job_nightly_backup(app)
        print("Backup complete.")
        return

    from app import create_app
    app = create_app()
    port = int(os.environ.get("PORT", "8077"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
