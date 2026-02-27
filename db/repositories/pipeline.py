"""Pipeline event recording — replies, calls, meetings, suppressions."""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import CallRecord, InboundReply, Meeting, SuppressionList

logger = logging.getLogger(__name__)


async def record_reply(
    session: AsyncSession,
    org_id: Optional[UUID],
    contact_id: Optional[UUID],
    touch_id: Optional[UUID],
    reply_text: str,
    classification: str,
    classification_reasoning: Optional[str] = None,
    key_phrase: Optional[str] = None,
    recontact_date=None,
    recontact_note: Optional[str] = None,
) -> InboundReply:
    """Persist an inbound reply with its LLM classification."""
    reply = InboundReply(
        org_id=org_id,
        contact_id=contact_id,
        touch_id=touch_id,
        reply_text=reply_text,
        classification=classification,
        classification_reasoning=classification_reasoning,
        key_phrase=key_phrase,
        classified_at=datetime.now(timezone.utc),
        recontact_date=recontact_date,
        recontact_note=recontact_note,
    )
    session.add(reply)
    await session.flush()
    return reply


async def record_call(
    session: AsyncSession,
    org_id: Optional[UUID],
    contact_id: Optional[UUID],
    call_permission_granted: bool = False,
    elevenlabs_call_id: Optional[str] = None,
    elevenlabs_agent_id: Optional[str] = None,
    call_status: Optional[str] = None,
    transcript: Optional[str] = None,
    call_successful: Optional[bool] = None,
    agreed_slot: Optional[dict] = None,
    notes: Optional[str] = None,
) -> CallRecord:
    """Persist a call record (pre- or post-call)."""
    call = CallRecord(
        org_id=org_id,
        contact_id=contact_id,
        call_permission_granted=call_permission_granted,
        call_permission_granted_at=datetime.now(timezone.utc) if call_permission_granted else None,
        elevenlabs_call_id=elevenlabs_call_id,
        elevenlabs_agent_id=elevenlabs_agent_id,
        call_status=call_status,
        transcript=transcript,
        call_successful=call_successful,
        agreed_slot=agreed_slot,
        notes=notes,
    )
    session.add(call)
    await session.flush()
    return call


async def record_meeting(
    session: AsyncSession,
    org_id: Optional[UUID],
    contact_id: Optional[UUID],
    call_record_id: Optional[UUID] = None,
    google_event_id: Optional[str] = None,
    html_link: Optional[str] = None,
    meet_link: Optional[str] = None,
    scheduled_start: Optional[datetime] = None,
    scheduled_end: Optional[datetime] = None,
    timezone_str: Optional[str] = None,
    confirmation_email_draft: Optional[str] = None,
    event_verified: bool = False,
) -> Meeting:
    """Persist a booked meeting."""
    meeting = Meeting(
        org_id=org_id,
        contact_id=contact_id,
        call_record_id=call_record_id,
        google_event_id=google_event_id,
        html_link=html_link,
        meet_link=meet_link,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        timezone=timezone_str,
        confirmation_email_draft=confirmation_email_draft,
        event_verified=event_verified,
        status="confirmed",
    )
    session.add(meeting)
    await session.flush()
    return meeting


async def add_suppression(
    session: AsyncSession,
    email: str,
    domain: Optional[str] = None,
    reason: Optional[str] = None,
    source: str = "manual",
) -> SuppressionList:
    """Add an email to the suppression list. Idempotent — safe to call twice.

    source must be one of: 'unsubscribe_reply', 'manual', 'bounce'
    """
    email = email.lower().strip()
    stmt = (
        pg_insert(SuppressionList)
        .values(email=email, domain=domain, reason=reason, source=source)
        .on_conflict_do_nothing(index_elements=["email"])
        .returning(SuppressionList)
    )
    result = await session.execute(stmt)
    await session.flush()
    row = result.scalar_one_or_none()
    if row is None:
        # Already suppressed — fetch the existing row
        existing = await session.execute(
            select(SuppressionList).where(SuppressionList.email == email)
        )
        row = existing.scalar_one()
    return row


async def get_org_history(session: AsyncSession, org_id: UUID) -> dict:
    """Return full context for an org: replies, calls, meetings.

    Used by agents that need full conversation history before acting.
    """
    replies_result = await session.execute(
        select(InboundReply)
        .where(InboundReply.org_id == org_id)
        .order_by(InboundReply.received_at)
    )
    calls_result = await session.execute(
        select(CallRecord)
        .where(CallRecord.org_id == org_id)
        .order_by(CallRecord.created_at)
    )
    meetings_result = await session.execute(
        select(Meeting)
        .where(Meeting.org_id == org_id)
        .order_by(Meeting.created_at)
    )

    def _to_dict(obj) -> dict:
        """Convert ORM object to JSON-serializable dict."""
        import uuid as _uuid
        from datetime import date as _date, datetime as _datetime
        out = {}
        for c in obj.__mapper__.columns:
            val = getattr(obj, c.key)
            if isinstance(val, _uuid.UUID):
                val = str(val)
            elif isinstance(val, _datetime):
                val = val.isoformat()
            elif isinstance(val, _date):
                val = val.isoformat()
            out[c.key] = val
        return out

    return {
        "replies": [_to_dict(r) for r in replies_result.scalars().all()],
        "calls": [_to_dict(c) for c in calls_result.scalars().all()],
        "meetings": [_to_dict(m) for m in meetings_result.scalars().all()],
    }
