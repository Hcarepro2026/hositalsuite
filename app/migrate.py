"""Zero-dependency schema drift fixer.

db.create_all() creates missing tables but cannot add columns to existing
tables. This helper adds known missing columns (idempotent, safe on both
SQLite and PostgreSQL) so existing deployments upgrade without manual SQL.
"""
from __future__ import annotations

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
]

# unique partial indexes — make idempotency race-proof at the DB level (§41)
UNIQUE_INDEXES = [
    ("uq_complaint_idem", "complaint", "org_id, idempotency_key", "idempotency_key IS NOT NULL"),
    ("uq_appointment_idem", "appointment", "org_id, idempotency_key", "idempotency_key IS NOT NULL"),
]


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
