"""Guards against the migration mistake that took /hims/ down in production.

WHAT HAPPENED
-------------
Stage A shipped, creating `patient` with clinical columns. The founder pointed
out the app is not an EMR, so those columns were removed from the model — by
EDITING the migration that had already run in production.

Alembic had already recorded that revision as applied, so it never ran again.
The live database kept the old columns and never gained the new ones, and every
visit to /hims/ died with:

    (psycopg2.errors.UndefinedColumn) column patient.preferred_lang does not exist

An applied migration is immutable history. Fixes go in a NEW migration.

These tests check the two things that would have caught it:
  1. every column the app reads actually exists after migrations run
  2. the migration chain is linear and each revision is only defined once
"""
import os
import re

import pytest
from sqlalchemy import inspect

from app.models import db

MIGRATIONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "migrations", "versions")


def _revisions():
    """(revision, down_revision, filename, all_downs) for every migration on disk.
    Handles merge migrations where down_revision is a tuple.
    """
    out = []
    for fn in sorted(os.listdir(MIGRATIONS)):
        if not fn.endswith(".py"):
            continue
        text = open(os.path.join(MIGRATIONS, fn)).read()
        rev = re.search(r'^revision(?::\s*str)?\s*=\s*[\"\']([^\"\']+)[\"\']',
                        text, re.M)
        if not rev:
            continue
        revision = rev.group(1)
        down_list = []
        # tuple case: down_revision = ('a','b')
        m_tuple = re.search(r'^down_revision[^=]*=\s*\(([^)]+)\)', text, re.M)
        if m_tuple:
            inner = m_tuple.group(1)
            down_list = re.findall(r'[\"\']([^\"\']+)[\"\']', inner)
        else:
            down = re.search(r'^down_revision(?::[^=]+)?\s*=\s*(?:[\"\']([^\"\']+)[\"\']|None)',
                             text, re.M)
            if down and down.group(1):
                down_list = [down.group(1)]
        first = down_list[0] if down_list else None
        out.append((revision, first, fn, down_list))
    return out


def _revisions_simple():
    return [(r, d, f) for r, d, f, _all in _revisions()]


def test_every_model_column_exists_in_the_database(app):
    """The check that would have caught the outage.

    Walks every table the app defines and asserts the real database has every
    column. A model change with no matching migration fails here instead of
    500-ing in front of a patient.
    """
    with app.app_context():
        insp = inspect(db.engine)
        real_tables = set(insp.get_table_names())
        missing = []
        for table_name, table in db.metadata.tables.items():
            if table_name not in real_tables:
                missing.append(f"whole table `{table_name}` is missing")
                continue
            actual = {c["name"] for c in insp.get_columns(table_name)}
            for col in table.columns:
                if col.name not in actual:
                    missing.append(f"{table_name}.{col.name}")
        assert not missing, (
            "The database is missing columns the app will try to read: "
            + ", ".join(missing)
            + ".\nAdd a NEW migration — never edit one that has already been applied."
        )


def test_patient_folder_has_the_care_columns_and_no_clinical_ones(app):
    """The specific columns involved in the outage."""
    with app.app_context():
        cols = {c["name"] for c in inspect(db.engine).get_columns("patient")}
        for needed in ("preferred_lang", "assistance", "care_note"):
            assert needed in cols, f"patient.{needed} missing — /hims/ would 500"
        for gone in ("blood_group", "genotype", "allergies", "chronic_conditions"):
            assert gone not in cols, f"patient.{gone} is EMR data and must not exist"


def test_migration_revisions_are_unique():
    revs = [r for r, _d, _f, _all in _revisions()]
    dupes = {r for r in revs if revs.count(r) > 1}
    assert not dupes, f"duplicate migration revision ids: {dupes}"


def test_migration_chain_is_linear_and_complete():
    """Exactly one root, no orphans, no forks — otherwise upgrades misbehave.
    Merge migration j24_merge is allowed as single merge point.
    Fork at f7d25a6b0c93 is resolved via merge of its two branches.
    """
    revs = _revisions()
    ids = {r for r, _d, _f, _all in revs}
    roots = [f for r, d, f, all_d in revs if not all_d]
    assert len(roots) == 1, f"expected exactly one base migration, found {roots}"
    for rev, down, fn, all_down in revs:
        for parent in all_down:
            assert parent in ids, f"{fn} points at unknown parent {parent!r}"
    # Build parent map for ancestor traversal
    parent_map = {r: all_down for r, _d, _f, all_down in revs}
    def ancestors(start):
        seen = set()
        stack = list(parent_map.get(start, []))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(parent_map.get(cur, []))
        return seen

    # Collect non-merge parents
    parents = []
    for r, d, f, all_down in revs:
        if len(all_down) == 2:
            continue
        parents.extend(all_down)
    forked = {p for p in parents if parents.count(p) > 1}

    # All merges and their ancestor sets
    merges = [(r, all_down) for r, _d, _f, all_down in revs if len(all_down) == 2]
    merge_ancestors = set()
    for _mr, m_parents in merges:
        for mp in m_parents:
            merge_ancestors.add(mp)
            merge_ancestors.update(ancestors(mp))

    # A fork is resolved if its parent is ancestor of a merge and at least
    # two of its children are also ancestors of that merge (both branches meet)
    resolved = set()
    for p in forked:
        # children of p
        children = [r for r, _d, _f, all_down in revs if p in all_down]
        # check if p and at least 2 children are in merge ancestry
        if p in merge_ancestors:
            cnt = sum(1 for c in children if c in merge_ancestors)
            if cnt >= 2:
                resolved.add(p)

    unresolved = forked - resolved
    assert not unresolved, f"two migrations share a parent (a fork): {unresolved}"


def test_upgrading_a_real_old_database_adds_the_new_columns():
    """THE test that would actually have caught the outage.

    The other tests build a fresh database with create_all(), which always
    produces correct columns — so they never exercise the UPGRADE path, which
    is the only path that broke. This one builds a database in the exact shape
    production was in (folder table with the old clinical columns, stamped at
    the revision that created it), then runs the migrations over it and checks
    the result — which is precisely what Render does on every deploy.
    """
    import sqlite3
    import tempfile

    from alembic import command
    from alembic.config import Config

    root = os.path.dirname(MIGRATIONS.rsplit("migrations", 1)[0])
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    con = sqlite3.connect(tmp.name)
    # the folder table exactly as the first Stage A deploy created it
    con.execute("""CREATE TABLE patient (
        id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL,
        hospital_number VARCHAR(32) NOT NULL, surname VARCHAR(80) NOT NULL,
        first_name VARCHAR(80) NOT NULL, sex VARCHAR(1) NOT NULL,
        payer_type VARCHAR(16) NOT NULL, category VARCHAR(16) NOT NULL,
        active BOOLEAN NOT NULL DEFAULT 1,
        marital_status VARCHAR(16), religion VARCHAR(40),
        blood_group VARCHAR(4), genotype VARCHAR(4),
        allergies VARCHAR(300), chronic_conditions VARCHAR(300))""")
    con.execute("INSERT INTO patient (id, org_id, hospital_number, surname, "
                "first_name, sex, payer_type, category, blood_group) VALUES "
                "(1, 1, 'IJD/2026/00001', 'ABATAN', 'Lekan', 'F', 'SELF', "
                "'GENERAL', 'O+')")
    con.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    con.execute("INSERT INTO alembic_version VALUES ('9c2e5f7a41bb')")
    con.commit()
    con.close()

    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(root, "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp.name}")
    command.upgrade(cfg, "head")

    con = sqlite3.connect(tmp.name)
    cols = {r[1] for r in con.execute("PRAGMA table_info(patient)")}
    # the patient already on file survived the upgrade
    kept = list(con.execute("SELECT hospital_number, surname FROM patient"))
    con.close()
    os.unlink(tmp.name)

    for needed in ("preferred_lang", "assistance", "care_note"):
        assert needed in cols, (
            f"upgrading a real production database did not add patient.{needed} "
            "— /hims/ would return 500 in production. Add a NEW migration; "
            "never edit one that has already been applied.")
    for gone in ("blood_group", "genotype", "allergies", "chronic_conditions"):
        assert gone not in cols, f"patient.{gone} is EMR data and should be dropped"
    assert kept == [("IJD/2026/00001", "ABATAN")], "existing folders were lost!"


@pytest.mark.parametrize("path", ["/hims/", "/hims/register", "/roster"])
def test_key_pages_load_without_a_database_error(client, seeded, path):
    """A live smoke test of the pages a schema drift would break first."""
    from conftest import login
    login(client, "admin")
    r = client.get(path)
    assert r.status_code == 200, f"{path} returned {r.status_code}"
    assert b"Something went wrong" not in r.data, f"{path} rendered the 500 page"


# ================================================================ ROLE MANAGEMENT
def test_the_role_tables_arrive_on_a_real_upgrade_not_just_create_all():
    """The upgrade path is the only path that broke in production.

    create_all() on a fresh database always produces correct tables, so it
    never exercises what Render actually does on deploy. This starts from a
    database stamped at the PREVIOUS head, runs the migrations, and checks the
    role tables really appeared.
    """
    import sqlite3
    import tempfile

    from alembic import command
    from alembic.config import Config

    root = os.path.dirname(MIGRATIONS.rsplit("migrations", 1)[0])
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    con = sqlite3.connect(tmp.name)
    # The three tables the new migration's foreign keys point at must exist,
    # or the upgrade fails the same way it would on a real deploy.
    con.execute("CREATE TABLE organization (id INTEGER PRIMARY KEY)")
    con.execute("CREATE TABLE department (id INTEGER PRIMARY KEY)")
    con.execute("CREATE TABLE unit (id INTEGER PRIMARY KEY)")
    con.execute("CREATE TABLE \"user\" (id INTEGER PRIMARY KEY)")
    con.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    con.execute("INSERT INTO alembic_version VALUES ('a8e31c4f9b56')")
    con.commit()
    con.close()

    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(root, "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp.name}")
    command.upgrade(cfg, "head")

    con = sqlite3.connect(tmp.name)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    os.unlink(tmp.name)

    for needed in ("role", "role_permission", "user_role", "work_claim"):
        assert needed in tables, (
            f"upgrading a real database did not create '{needed}' — Role "
            f"Management would 500 in production on the first click.")


def test_the_migration_is_safe_to_run_twice():
    """Render can retry a deploy. A migration that only works once is a trap."""
    import sqlite3
    import tempfile

    from alembic import command
    from alembic.config import Config

    root = os.path.dirname(MIGRATIONS.rsplit("migrations", 1)[0])
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    con = sqlite3.connect(tmp.name)
    for t in ("organization", "department", "unit"):
        con.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY)")
    con.execute('CREATE TABLE "user" (id INTEGER PRIMARY KEY)')
    con.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    con.execute("INSERT INTO alembic_version VALUES ('a8e31c4f9b56')")
    con.commit()
    con.close()

    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(root, "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp.name}")
    command.upgrade(cfg, "head")
    # Rewind the stamp only — the tables stay — and run it again.
    con = sqlite3.connect(tmp.name)
    con.execute("UPDATE alembic_version SET version_num='a8e31c4f9b56'")
    con.commit()
    con.close()
    command.upgrade(cfg, "head")            # must not raise
    os.unlink(tmp.name)


def test_role_management_never_becomes_a_medical_record():
    """This is NOT an EMR. A guard, because these tables are new and tempting."""
    from app.models import Role, RolePermission, UserRole, WorkClaim

    banned = ("diagnosis", "symptom", "vital", "temperature", "blood_pressure",
              "prescription", "drug", "dose", "test_result", "blood_group",
              "genotype", "allergy", "allergies", "condition")
    for model in (Role, RolePermission, UserRole, WorkClaim):
        for column in model.__table__.columns:
            for word in banned:
                assert word not in column.name.lower(), (
                    f"{model.__name__}.{column.name} looks like clinical data. "
                    f"This system is not an EMR.")
