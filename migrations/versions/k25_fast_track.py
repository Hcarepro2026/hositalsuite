"""Fast-track Elderly/Pregnant/Child + journey time

Revision ID: k25_fasttrack
Revises: j24_merge
Create Date: 2026-08-22
Adds is_fast_track + fast_track_reason to patient_visit, reception_intake, queue_ticket
Per-tenant, no EMR, premium patient care.
"""
from alembic import op
import sqlalchemy as sa

revision = 'k25_fasttrack'
down_revision = 'j24_merge'
branch_labels = None
depends_on = None

def upgrade():
    for table in ('patient_visit', 'reception_intake', 'queue_ticket'):
        try:
            op.add_column(table, sa.Column('is_fast_track', sa.Boolean(), nullable=True, server_default=sa.text('0')))
        except Exception:
            pass
        try:
            op.add_column(table, sa.Column('fast_track_reason', sa.String(length=40), nullable=True))
        except Exception:
            pass
    # Ensure boolean defaults are 0/False and not null for new rows
    try:
        op.execute("UPDATE patient_visit SET is_fast_track=0 WHERE is_fast_track IS NULL")
        op.execute("UPDATE reception_intake SET is_fast_track=0 WHERE is_fast_track IS NULL")
        op.execute("UPDATE queue_ticket SET is_fast_track=0 WHERE is_fast_track IS NULL")
    except Exception:
        pass

def downgrade():
    for table in ('patient_visit', 'reception_intake', 'queue_ticket'):
        try:
            op.drop_column(table, 'is_fast_track')
        except Exception:
            pass
        try:
            op.drop_column(table, 'fast_track_reason')
        except Exception:
            pass
