"""SQLAlchemy 2.0 ORM models for the Backflip SDR pipeline.

Covers 14 tables across 3 schemas:
  - crm: organizations, events, contacts, suppression_list,
         email_sequences, email_touches, inbound_replies, call_records, meetings
  - obs: agent_run_log, api_cost_log
  - improve: prompt_versions, improvement_suggestions, outcome_feedback
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy import (
    UUID,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Integer,
    JSON,
    Numeric,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Pipeline stage values used in the CRM CHECK constraint
# ---------------------------------------------------------------------------

_PIPELINE_STAGES = (
    "discovered",
    "enriched",
    "scored",
    "qualified",
    "rejected",
    "in_sequence",
    "touch_1_sent",
    "touch_2_sent",
    "touch_3_sent",
    "replied_interested",
    "call_permission_sent",
    "call_permission_granted",
    "call_attempted",
    "booked",
    "meeting_held",
    "became_client",
    "nurture",
    "closed_lost",
    "unsubscribed",
)

_PIPELINE_STAGE_CHECK = (
    "pipeline_stage IN ("
    + ", ".join(f"'{s}'" for s in _PIPELINE_STAGES)
    + ")"
)


# ===========================================================================
# Schema: crm
# ===========================================================================


class Organization(Base):
    """crm.organizations — core account / target company record."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            _PIPELINE_STAGE_CHECK,
            name="ck_org_pipeline_stage",
        ),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    website: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    org_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    employee_count_range: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icp_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    icp_score_dimensions: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    pipeline_stage: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="discovered"
    )
    why_fit: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_outreach_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_outreach_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    disqualified: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    disqualified_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    events: Mapped[list["Event"]] = relationship(
        "Event", back_populates="organization", cascade="all, delete-orphan"
    )
    contacts: Mapped[list["Contact"]] = relationship(
        "Contact", back_populates="organization"
    )
    email_sequences: Mapped[list["EmailSequence"]] = relationship(
        "EmailSequence", back_populates="organization"
    )
    email_touches: Mapped[list["EmailTouch"]] = relationship(
        "EmailTouch", back_populates="organization"
    )
    inbound_replies: Mapped[list["InboundReply"]] = relationship(
        "InboundReply", back_populates="organization"
    )
    call_records: Mapped[list["CallRecord"]] = relationship(
        "CallRecord", back_populates="organization"
    )
    meetings: Mapped[list["Meeting"]] = relationship(
        "Meeting", back_populates="organization"
    )


class Event(Base):
    """crm.events — industry/conference events linked to an organization."""

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "recurrence_period IS NULL OR recurrence_period IN ('annual', 'quarterly', 'biannual')",
            name="ck_event_recurrence_period",
        ),
        UniqueConstraint("org_id", "event_name", name="uq_event_org_name"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.organizations.id"),
        nullable=False,
    )
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    event_date_approximate: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    event_date_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    estimated_attendees: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    registration_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_recurring: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    recurrence_period: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="events"
    )

    # ------------------------------------------------------------------
    # Computed outreach window (Python only — not DB-generated columns)
    # ------------------------------------------------------------------

    @property
    def outreach_window_open(self) -> Optional[date]:
        """Earliest date to begin outreach: event_date minus 12 months."""
        if self.event_date is None:
            return None
        return self.event_date - relativedelta(months=12)

    @property
    def outreach_window_close(self) -> Optional[date]:
        """Latest date to begin outreach: event_date minus 4 months."""
        if self.event_date is None:
            return None
        return self.event_date - relativedelta(months=4)


class Contact(Base):
    """crm.contacts — individual people at target organizations."""

    __tablename__ = "contacts"
    __table_args__ = {"schema": "crm"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.organizations.id"),
        nullable=True,
    )
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    hunter_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="contacts"
    )
    email_sequences: Mapped[list["EmailSequence"]] = relationship(
        "EmailSequence", back_populates="contact"
    )
    email_touches: Mapped[list["EmailTouch"]] = relationship(
        "EmailTouch", back_populates="contact"
    )
    inbound_replies: Mapped[list["InboundReply"]] = relationship(
        "InboundReply", back_populates="contact"
    )
    call_records: Mapped[list["CallRecord"]] = relationship(
        "CallRecord", back_populates="contact"
    )
    meetings: Mapped[list["Meeting"]] = relationship(
        "Meeting", back_populates="contact"
    )


class SuppressionList(Base):
    """crm.suppression_list — permanent do-not-contact registry."""

    __tablename__ = "suppression_list"
    __table_args__ = (
        CheckConstraint(
            "source IN ('unsubscribe_reply', 'manual', 'bounce')",
            name="ck_suppression_source",
        ),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    domain: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="manual"
    )
    suppressed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmailSequence(Base):
    """crm.email_sequences — a drip sequence for one org/contact pair."""

    __tablename__ = "email_sequences"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'completed', 'paused', 'cancelled')",
            name="ck_email_sequence_status",
        ),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.organizations.id"),
        nullable=True,
    )
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.contacts.id"),
        nullable=True,
    )
    icp_profile_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    personalization_hook: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="email_sequences"
    )
    contact: Mapped[Optional["Contact"]] = relationship(
        "Contact", back_populates="email_sequences"
    )
    email_touches: Mapped[list["EmailTouch"]] = relationship(
        "EmailTouch", back_populates="email_sequence"
    )


class EmailTouch(Base):
    """crm.email_touches — individual send within a sequence (touch 1–3)."""

    __tablename__ = "email_touches"
    __table_args__ = (
        CheckConstraint(
            "touch_number BETWEEN 1 AND 3",
            name="ck_email_touch_number",
        ),
        CheckConstraint(
            "status IS NULL OR status IN ('scheduled', 'sent', 'bounced', 'failed', 'cancelled')",
            name="ck_email_touch_status",
        ),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.email_sequences.id"),
        nullable=False,
    )
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.organizations.id"),
        nullable=True,
    )
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.contacts.id"),
        nullable=True,
    )
    touch_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    email_sequence: Mapped["EmailSequence"] = relationship(
        "EmailSequence", back_populates="email_touches"
    )
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="email_touches"
    )
    contact: Mapped[Optional["Contact"]] = relationship(
        "Contact", back_populates="email_touches"
    )
    inbound_replies: Mapped[list["InboundReply"]] = relationship(
        "InboundReply", back_populates="touch"
    )


class InboundReply(Base):
    """crm.inbound_replies — replies received from prospects."""

    __tablename__ = "inbound_replies"
    __table_args__ = (
        CheckConstraint(
            "classification IS NULL OR classification IN ('INTERESTED', 'NURTURE', 'NOT_FIT', 'UNSUBSCRIBE')",
            name="ck_reply_classification",
        ),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.organizations.id"),
        nullable=True,
    )
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.contacts.id"),
        nullable=True,
    )
    touch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.email_touches.id"),
        nullable=True,
    )
    reply_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    classification: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    classification_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_phrase: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    classified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recontact_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    recontact_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actioned: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="inbound_replies"
    )
    contact: Mapped[Optional["Contact"]] = relationship(
        "Contact", back_populates="inbound_replies"
    )
    touch: Mapped[Optional["EmailTouch"]] = relationship(
        "EmailTouch", back_populates="inbound_replies"
    )


class CallRecord(Base):
    """crm.call_records — ElevenLabs AI voice call records."""

    __tablename__ = "call_records"
    __table_args__ = {"schema": "crm"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.organizations.id"),
        nullable=True,
    )
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.contacts.id"),
        nullable=True,
    )
    call_permission_granted: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    call_permission_granted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    elevenlabs_call_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    elevenlabs_agent_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    call_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    call_successful: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    initiated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    agreed_slot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="call_records"
    )
    contact: Mapped[Optional["Contact"]] = relationship(
        "Contact", back_populates="call_records"
    )
    meetings: Mapped[list["Meeting"]] = relationship(
        "Meeting", back_populates="call_record"
    )


class Meeting(Base):
    """crm.meetings — Google Calendar meeting bookings."""

    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('confirmed', 'cancelled', 'completed', 'no_show')",
            name="ck_meeting_status",
        ),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.organizations.id"),
        nullable=True,
    )
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.contacts.id"),
        nullable=True,
    )
    call_record_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm.call_records.id"),
        nullable=True,
    )
    google_event_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    html_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meet_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scheduled_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    timezone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="confirmed")
    outcome_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirmation_email_draft: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_verified: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="meetings"
    )
    contact: Mapped[Optional["Contact"]] = relationship(
        "Contact", back_populates="meetings"
    )
    call_record: Mapped[Optional["CallRecord"]] = relationship(
        "CallRecord", back_populates="meetings"
    )


# ===========================================================================
# Schema: obs
# ===========================================================================


class AgentRunLog(Base):
    """obs.agent_run_log — execution log for each agent invocation."""

    __tablename__ = "agent_run_log"
    __table_args__ = {"schema": "obs"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    team_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stage_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Loose UUID reference — no FK enforced
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    langfuse_trace_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_llm_cost_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 6), nullable=True
    )

    # Relationship
    api_cost_logs: Mapped[list["ApiCostLog"]] = relationship(
        "ApiCostLog", back_populates="agent_run"
    )


class ApiCostLog(Base):
    """obs.api_cost_log — per-API-call cost tracking."""

    __tablename__ = "api_cost_log"
    __table_args__ = {"schema": "obs"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    service: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Loose UUID reference — no FK enforced
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    agent_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("obs.agent_run_log.id"),
        nullable=True,
    )
    estimated_cost_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    units_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Relationship
    agent_run: Mapped[Optional["AgentRunLog"]] = relationship(
        "AgentRunLog", back_populates="api_cost_logs"
    )


# ===========================================================================
# Schema: improve
# ===========================================================================


class PromptVersion(Base):
    """improve.prompt_versions — versioned prompt content registry."""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("prompt_name", "version", name="uq_prompt_versions_name_version"),
        {"schema": "improve"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    prompt_name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    change_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deprecated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ImprovementSuggestion(Base):
    """improve.improvement_suggestions — AI-generated improvement proposals."""

    __tablename__ = "improvement_suggestions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_review', 'approved', 'rejected', 'implemented')",
            name="ck_improvement_status",
        ),
        {"schema": "improve"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proposed_change: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    supporting_evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending_review"
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    implementation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OutcomeFeedback(Base):
    """improve.outcome_feedback — records conversion outcomes for model improvement."""

    __tablename__ = "outcome_feedback"
    __table_args__ = {"schema": "improve"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Loose UUID references — no FK enforced
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    sequence_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    call_record_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    meeting_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    conversion_event: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icp_score_at_time: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prompt_versions_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    personalization_hook_used: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email_touch_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    days_since_first_touch: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "Base",
    # crm
    "Organization",
    "Event",
    "Contact",
    "SuppressionList",
    "EmailSequence",
    "EmailTouch",
    "InboundReply",
    "CallRecord",
    "Meeting",
    # obs
    "AgentRunLog",
    "ApiCostLog",
    # improve
    "PromptVersion",
    "ImprovementSuggestion",
    "OutcomeFeedback",
]
