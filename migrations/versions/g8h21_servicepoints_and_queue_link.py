"""servicepoints (clinics, 8 rooms, 24 destinations) + queue linkage

Revision ID: g8h21
Revises: f7d25a6b0c93
Create Date: 2026-08-21

Adds:
- service_clinic, consulting_room, service_destination, clinic_destination
- queue_ticket.patient_id, patient_visit_id, intake_id (use_alter for cycle)
"""
from alembic import op
import sqlalchemy as sa

revision = 'g8h21'
down_revision = 'f7d25a6b0c93'
branch_labels = None
depends_on = None


def upgrade():
    # --- service clinics
    op.create_table(
        'service_clinic',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.String(length=300), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, default=True),
        sa.Column('sort_order', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'code', name='uq_clinic_org_code')
    )
    op.create_index('ix_clinic_org_active', 'service_clinic', ['org_id', 'active'])

    op.create_table(
        'consulting_room',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, default=True),
        sa.Column('sort_order', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['clinic_id'], ['service_clinic.id'], ),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'code', name='uq_room_org_code')
    )
    op.create_index('ix_room_org_active', 'consulting_room', ['org_id', 'active'])

    op.create_table(
        'service_destination',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('place', sa.String(length=120), nullable=True),
        sa.Column('description', sa.String(length=300), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, default=True),
        sa.Column('sort_order', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'code', name='uq_dest_org_code')
    )
    op.create_index('ix_dest_org_active', 'service_destination', ['org_id', 'active'])

    op.create_table(
        'clinic_destination',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=False),
        sa.Column('destination_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['clinic_id'], ['service_clinic.id'], ),
        sa.ForeignKeyConstraint(['destination_id'], ['service_destination.id'], ),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('clinic_id', 'destination_id', name='uq_clinic_dest')
    )
    op.create_index('ix_clinic_dest_org', 'clinic_destination', ['org_id', 'clinic_id'])

    # --- queue linkage (may already exist via ensure_schema, so try/except)
    try:
        op.add_column('queue_ticket', sa.Column('patient_id', sa.Integer(), nullable=True))
        op.create_index('ix_queue_ticket_patient_id', 'queue_ticket', ['patient_id'])
    except Exception:
        pass
    try:
        op.add_column('queue_ticket', sa.Column('patient_visit_id', sa.Integer(), nullable=True))
        op.create_index('ix_queue_ticket_patient_visit_id', 'queue_ticket', ['patient_visit_id'])
    except Exception:
        pass
    try:
        op.add_column('queue_ticket', sa.Column('intake_id', sa.Integer(), nullable=True))
        op.create_index('ix_queue_ticket_intake_id', 'queue_ticket', ['intake_id'])
    except Exception:
        pass


def downgrade():
    try:
        op.drop_table('clinic_destination')
    except Exception:
        pass
    try:
        op.drop_table('service_destination')
    except Exception:
        pass
    try:
        op.drop_table('consulting_room')
    except Exception:
        pass
    try:
        op.drop_table('service_clinic')
    except Exception:
        pass
    for col in ('patient_id', 'patient_visit_id', 'intake_id'):
        try:
            op.drop_column('queue_ticket', col)
        except Exception:
            pass
