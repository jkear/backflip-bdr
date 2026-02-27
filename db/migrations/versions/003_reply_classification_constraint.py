"""Add CHECK constraint on classification for inbound_replies.

Revision ID: 003
Revises: 002
Create Date: 2026-02-26
"""
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_reply_classification'
                  AND conrelid = 'crm.inbound_replies'::regclass
            ) THEN
                ALTER TABLE crm.inbound_replies
                    ADD CONSTRAINT ck_reply_classification
                    CHECK (classification IS NULL OR classification IN
                           ('INTERESTED', 'NURTURE', 'NOT_FIT', 'UNSUBSCRIBE'));
            END IF;
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE crm.inbound_replies DROP CONSTRAINT IF EXISTS ck_reply_classification;"
    )
