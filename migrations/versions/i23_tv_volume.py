"""TV volume slider per TV

Revision ID: i23
Revises: h22
Create Date: 2026-08-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'i23'
down_revision = 'h22'
branch_labels = None
depends_on = None


def upgrade():
    try:
        op.add_column('tv_screen', sa.Column('voice_volume', sa.Integer(), nullable=True, server_default='100'))
    except Exception:
        pass


def downgrade():
    try:
        op.drop_column('tv_screen', 'voice_volume')
    except Exception:
        pass
