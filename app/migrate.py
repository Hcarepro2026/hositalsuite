"""Zero-dependency schema drift fixer.

db.create_all() creates missing tables but cannot add columns to existing
tables. This helper adds known missing columns (idempotent, safe on both
SQLite and PostgreSQL) so existing deployments upgrade without manual SQL.
"""
from __future__ import annotations

import os

from sqlalchemy import inspect, text

from .models import db


def _bool_sql() -> str:
    """BOOLEAN on PostgreSQL, INTEGER on SQLite — both accept 0/1 defaults."""
    if str(db.engine.url).startswith("postgres"):
        return "BOOLEAN DEFAULT FALSE"
    return "INTEGER DEFAULT 0"


# (table, column, sql_type) — sql_type may be a callable for dialect-specific types
COLUMNS = [
    ("complaint", "idempotency_key", "VARCHAR(40)"),
    ("department", "roster_mode", "VARCHAR(10) DEFAULT 'two_12h'"),
    ("department", "roster_staff_per_shift", "INTEGER DEFAULT 1"),
    ("appointment", "referral_id", "INTEGER"),
    ("appointment", "is_repeat", _bool_sql),
    ("patient_feedback", "referral_id", "INTEGER"),
    ("organization", "email", "VARCHAR(160)"),
    ("organization", "phone", "VARCHAR(32)"),
    ("organization", "phone_alt", "VARCHAR(32)"),
    ("organization", "address", "VARCHAR(300)"),
    ("complaint_status_history", "patient_message", "VARCHAR(480)"),
    # --- multi-tenant public portals
    ("organization", "slug", "VARCHAR(40)"),
    # --- NDPA: consent, anonymity, erasure
    ("complaint", "is_anonymous", _bool_sql),
    ("complaint", "consent_at", "TIMESTAMP"),
    ("complaint", "anonymized_at", "TIMESTAMP"),
    ("appointment", "consent_at", "TIMESTAMP"),
    ("appointment", "anonymized_at", "TIMESTAMP"),
    ("patient_feedback", "consent_at", "TIMESTAMP"),
    ("patient_feedback", "anonymized_at", "TIMESTAMP"),
    ("queue_ticket", "anonymized_at", "TIMESTAMP"),
]

# unique partial indexes — make idempotency race-proof at the DB level (§41)
UNIQUE_INDEXES = [
    ("uq_complaint_idem", "complaint", "org_id, idempotency_key", "idempotency_key IS NOT NULL"),
    ("uq_appointment_idem", "appointment", "org_id, idempotency_key", "idempotency_key IS NOT NULL"),
]


def run_alembic_upgrade(app) -> bool:
    """Apply Alembic migrations at boot.

    The founder's host (Render free) has no shell and no one-off jobs, so
    migrations cannot be run by hand — they must self-apply on deploy.

    Databases created before Alembic existed are 'stamped' with the baseline
    revision instead of re-running it, so nothing is created twice. Any failure
    is logged and swallowed: ensure_schema() below is the belt-and-braces
    fallback, and a migration problem must never take the hospital offline.
    """
    if os.environ.get("DISABLE_MIGRATIONS") == "1":
        return False
    try:
        from alembic import command
        from alembic.config import Config as AlembicConfig
    except ImportError:
        app.logger.info("alembic not installed — using ensure_schema() only")
        return False

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ini = os.path.join(root, "alembic.ini")
    if not os.path.exists(ini):
        return False

    cfg = AlembicConfig(ini)
    cfg.set_main_option("script_location", os.path.join(root, "migrations"))
    cfg.set_main_option("sqlalchemy.url",
                        str(db.engine.url.render_as_string(hide_password=False)).replace("%", "%%"))
    try:
        insp = inspect(db.engine)
        tables = set(insp.get_table_names())
        if tables and "alembic_version" not in tables:
            # Pre-Alembic database: record where we are rather than replaying history.
            command.stamp(cfg, "head")
            app.logger.info("alembic: stamped existing database at head")
            return True
        command.upgrade(cfg, "head")
        app.logger.info("alembic: database is at head")
        return True
    except Exception as exc:                     # noqa: BLE001
        app.logger.warning("alembic upgrade skipped (%s) — falling back to ensure_schema()", exc)
        return False


def ensure_schema() -> None:
    insp = inspect(db.engine)
    existing_tables = set(insp.get_table_names())
    for table, column, coltype in COLUMNS:
        if table not in existing_tables:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if column not in cols:
            resolved = coltype() if callable(coltype) else coltype
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {resolved}'))
    for name, table, cols, where in UNIQUE_INDEXES:
        if table not in existing_tables:
            continue
        with db.engine.begin() as conn:
            conn.execute(text(
                f'CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({cols}) WHERE {where}'))
