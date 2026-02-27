"""Initial schema: crm, obs, improve tables.

Revision ID: 001
Revises:
Create Date: 2026-02-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── CRM Schema ──────────────────────────────────────────────────────────

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("domain", sa.Text, nullable=False),
        sa.Column("website", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("org_type", sa.Text, nullable=True),
        sa.Column("employee_count_range", sa.Text, nullable=True),
        sa.Column("icp_score", sa.Integer, nullable=True),
        sa.Column("icp_score_dimensions", sa.JSON, nullable=True),
        sa.Column("pipeline_stage", sa.Text, nullable=False, server_default="discovered"),
        sa.Column("why_fit", sa.Text, nullable=True),
        sa.Column("last_outreach_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_outreach_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("disqualified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("disqualified_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "pipeline_stage IN ('discovered','enriched','scored','qualified','rejected',"
            "'in_sequence','touch_1_sent','touch_2_sent','touch_3_sent',"
            "'replied_interested','call_permission_sent','call_permission_granted',"
            "'call_attempted','booked','meeting_held','became_client',"
            "'nurture','closed_lost','unsubscribed')",
            name="ck_org_pipeline_stage",
        ),
        sa.UniqueConstraint("domain", name="uq_org_domain"),
        schema="crm",
    )

    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("first_name", sa.Text, nullable=True),
        sa.Column("last_name", sa.Text, nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("email_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("hunter_score", sa.Integer, nullable=True),
        sa.Column("phone", sa.Text, nullable=True),
        sa.Column("linkedin_url", sa.Text, nullable=True),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.UniqueConstraint("email", name="uq_contact_email"),
        sa.ForeignKeyConstraint(["org_id"], ["crm.organizations.id"], name="fk_contact_org", ondelete="SET NULL"),
        schema="crm",
    )

    op.create_table(
        "suppression_list",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("domain", sa.Text, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("source", sa.Text, nullable=False, server_default="manual"),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "source IN ('unsubscribe_reply', 'manual', 'bounce')",
            name="ck_suppression_source",
        ),
        sa.UniqueConstraint("email", name="uq_suppression_email"),
        schema="crm",
    )

    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_name", sa.Text, nullable=False),
        sa.Column("event_type", sa.Text, nullable=True),
        sa.Column("event_date", sa.Date, nullable=True),
        sa.Column("event_date_approximate", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("event_date_notes", sa.Text, nullable=True),
        sa.Column("estimated_attendees", sa.Text, nullable=True),
        sa.Column("registration_url", sa.Text, nullable=True),
        sa.Column("is_recurring", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("recurrence_period", sa.Text, nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "recurrence_period IS NULL OR recurrence_period IN ('annual', 'quarterly', 'biannual')",
            name="ck_event_recurrence_period",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["crm.organizations.id"], name="fk_event_org", ondelete="CASCADE"),
        schema="crm",
    )

    op.create_table(
        "email_sequences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("icp_profile_snapshot", sa.JSON, nullable=True),
        sa.Column("personalization_hook", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'completed', 'paused', 'cancelled')",
            name="ck_email_sequence_status",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["crm.organizations.id"], name="fk_seq_org", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["crm.contacts.id"], name="fk_seq_contact", ondelete="SET NULL"),
        schema="crm",
    )

    op.create_table(
        "email_touches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sequence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("touch_number", sa.Integer, nullable=False),
        sa.Column("scheduled_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subject", sa.Text, nullable=True),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=True),
        sa.Column("message_id", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("touch_number BETWEEN 1 AND 3", name="ck_email_touch_number"),
        sa.CheckConstraint(
            "status IS NULL OR status IN ('scheduled', 'sent', 'bounced', 'failed', 'cancelled')",
            name="ck_email_touch_status",
        ),
        sa.ForeignKeyConstraint(["sequence_id"], ["crm.email_sequences.id"], name="fk_touch_seq", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["crm.organizations.id"], name="fk_touch_org", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["crm.contacts.id"], name="fk_touch_contact", ondelete="SET NULL"),
        schema="crm",
    )

    op.create_table(
        "inbound_replies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("touch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reply_text", sa.Text, nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("classification", sa.Text, nullable=True),
        sa.Column("classification_reasoning", sa.Text, nullable=True),
        sa.Column("key_phrase", sa.Text, nullable=True),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recontact_date", sa.Date, nullable=True),
        sa.Column("recontact_note", sa.Text, nullable=True),
        sa.Column("actioned", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["org_id"], ["crm.organizations.id"], name="fk_reply_org", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["crm.contacts.id"], name="fk_reply_contact", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["touch_id"], ["crm.email_touches.id"], name="fk_reply_touch", ondelete="SET NULL"),
        schema="crm",
    )

    op.create_table(
        "call_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("call_permission_granted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("call_permission_granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elevenlabs_call_id", sa.Text, nullable=True),
        sa.Column("elevenlabs_agent_id", sa.Text, nullable=True),
        sa.Column("call_status", sa.Text, nullable=True),
        sa.Column("transcript", sa.Text, nullable=True),
        sa.Column("call_successful", sa.Boolean, nullable=True),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agreed_slot", sa.JSON, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["org_id"], ["crm.organizations.id"], name="fk_call_org", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["crm.contacts.id"], name="fk_call_contact", ondelete="SET NULL"),
        schema="crm",
    )

    op.create_table(
        "meetings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("call_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("google_event_id", sa.Text, nullable=True),
        sa.Column("html_link", sa.Text, nullable=True),
        sa.Column("meet_link", sa.Text, nullable=True),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="confirmed"),
        sa.Column("outcome_notes", sa.Text, nullable=True),
        sa.Column("confirmation_email_draft", sa.Text, nullable=True),
        sa.Column("event_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('confirmed', 'cancelled', 'completed', 'no_show')",
            name="ck_meeting_status",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["crm.organizations.id"], name="fk_meeting_org", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["crm.contacts.id"], name="fk_meeting_contact", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["call_record_id"], ["crm.call_records.id"], name="fk_meeting_call", ondelete="SET NULL"),
        schema="crm",
    )

    # ─── OBS Schema ──────────────────────────────────────────────────────────

    op.create_table(
        "agent_run_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.Text, nullable=True),
        sa.Column("agent_name", sa.Text, nullable=False),
        sa.Column("team_name", sa.Text, nullable=True),
        sa.Column("stage_number", sa.Integer, nullable=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("langfuse_trace_id", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("success", sa.Boolean, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("model_used", sa.Text, nullable=True),
        sa.Column("input_token_count", sa.Integer, nullable=True),
        sa.Column("output_token_count", sa.Integer, nullable=True),
        sa.Column("estimated_llm_cost_usd", sa.Numeric(10, 6), nullable=True),
        schema="obs",
    )
    op.create_index("ix_agent_run_log_org_id", "agent_run_log", ["org_id"], schema="obs")

    op.create_table(
        "api_cost_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("service", sa.Text, nullable=False),
        sa.Column("operation", sa.Text, nullable=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("units_used", sa.Integer, nullable=True),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("success", sa.Boolean, nullable=True),
        sa.ForeignKeyConstraint(["agent_run_id"], ["obs.agent_run_log.id"], name="fk_api_cost_run", ondelete="SET NULL"),
        schema="obs",
    )
    op.create_index("ix_api_cost_log_org_id", "api_cost_log", ["org_id"], schema="obs")

    # ─── IMPROVE Schema ──────────────────────────────────────────────────────

    op.create_table(
        "prompt_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("prompt_name", sa.Text, nullable=False),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("change_summary", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("prompt_name", "version", name="uq_prompt_versions_name_version"),
        schema="improve",
    )

    op.create_table(
        "improvement_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.Text, nullable=True),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("proposed_change", sa.JSON, nullable=True),
        sa.Column("supporting_evidence", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="pending_review"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("implementation_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending_review', 'approved', 'rejected', 'implemented')",
            name="ck_improvement_status",
        ),
        schema="improve",
    )

    op.create_table(
        "outcome_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sequence_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("call_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversion_event", sa.Text, nullable=True),
        sa.Column("icp_score_at_time", sa.Integer, nullable=True),
        sa.Column("prompt_versions_snapshot", sa.JSON, nullable=True),
        sa.Column("personalization_hook_used", sa.Text, nullable=True),
        sa.Column("email_touch_number", sa.Integer, nullable=True),
        sa.Column("days_since_first_touch", sa.Integer, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="improve",
    )


def downgrade() -> None:
    op.drop_index("ix_api_cost_log_org_id", table_name="api_cost_log", schema="obs")
    op.drop_index("ix_agent_run_log_org_id", table_name="agent_run_log", schema="obs")
    # Drop in reverse dependency order
    op.drop_table("outcome_feedback", schema="improve")
    op.drop_table("improvement_suggestions", schema="improve")
    op.drop_table("prompt_versions", schema="improve")
    op.drop_table("api_cost_log", schema="obs")
    op.drop_table("agent_run_log", schema="obs")
    op.drop_table("meetings", schema="crm")
    op.drop_table("call_records", schema="crm")
    op.drop_table("inbound_replies", schema="crm")
    op.drop_table("email_touches", schema="crm")
    op.drop_table("email_sequences", schema="crm")
    op.drop_table("events", schema="crm")
    op.drop_table("suppression_list", schema="crm")
    op.drop_table("contacts", schema="crm")
    op.drop_table("organizations", schema="crm")
