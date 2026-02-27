"""Add unique constraint on (org_id, event_name) for events upsert.

Revision ID: 002
Revises: 001
Create Date: 2026-02-19
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_event_org_name", "events", ["org_id", "event_name"], schema="crm"
    )


def downgrade() -> None:
    op.drop_constraint("uq_event_org_name", "events", schema="crm")
