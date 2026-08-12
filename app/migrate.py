"""Zero-dependency schema drift fixer.

db.create_all() creates missing tables but cannot add columns to existing
tables. This helper adds known missing columns (idempotent, safe on both
SQLite and PostgreSQL) so existing deployments upgrade without manual SQL.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from .models import db

# (table, column, sql_type)
COLUMNS = [
    ("complaint", "idempotency_key", "VARCHAR(40)"),
    ("department", "roster_mode", "VARCHAR(10) DEFAULT 'two_12h'"),
    ("department", "roster_staff_per_shift", "INTEGER DEFAULT 1"),
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
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {coltype}'))
    for name, table, cols, where in UNIQUE_INDEXES:
        if table not in existing_tables:
            continue
        with db.engine.begin() as conn:
            conn.execute(text(
                f'CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({cols}) WHERE {where}'))
