"""Email sequence and touch repositories."""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import EmailSequence, EmailTouch

logger = logging.getLogger(__name__)

_VALID_TOUCH_STATUSES = ("scheduled", "sent", "bounced", "failed", "cancelled")


async def create_sequence(
    session: AsyncSession,
    org_id: UUID,
    contact_id: UUID,
    touches: list[dict],
    hook: Optional[str] = None,
    icp_snapshot: Optional[dict] = None,
) -> EmailSequence:
    """Create an email sequence with 1-3 touches.

    touches: list of dicts, each with keys:
      touch_number (int 1-3), scheduled_date (datetime), subject (str), body (str)
    """
    sequence = EmailSequence(
        org_id=org_id,
        contact_id=contact_id,
        personalization_hook=hook,
        icp_profile_snapshot=icp_snapshot,
        status="active",
    )
    session.add(sequence)
    await session.flush()  # get sequence.id

    for touch_data in touches:
        touch = EmailTouch(
            sequence_id=sequence.id,
            org_id=org_id,
            contact_id=contact_id,
            touch_number=touch_data["touch_number"],
            scheduled_date=touch_data.get("scheduled_date"),
            subject=touch_data.get("subject"),
            body=touch_data.get("body"),
            status="scheduled",
        )
        session.add(touch)

    await session.flush()
    return sequence


async def get_pending_touches(session: AsyncSession) -> list[EmailTouch]:
    """Return touches scheduled for now or earlier that haven't been sent."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(EmailTouch)
        .where(EmailTouch.scheduled_date <= now)
        .where(EmailTouch.status == "scheduled")
        .order_by(EmailTouch.scheduled_date)
    )
    return list(result.scalars().all())


async def mark_touch_sent(
    session: AsyncSession,
    touch_id: UUID,
    message_id: str,
    sent_at: Optional[datetime] = None,
) -> Optional[EmailTouch]:
    """Mark a touch as sent with the provider message ID."""
    if sent_at is None:
        sent_at = datetime.now(timezone.utc)
    result = await session.execute(
        update(EmailTouch)
        .where(EmailTouch.id == touch_id)
        .values(status="sent", message_id=message_id, sent_at=sent_at)
        .returning(EmailTouch)
    )
    await session.flush()
    return result.scalar_one_or_none()


async def cancel_remaining_touches(
    session: AsyncSession, sequence_id: UUID
) -> int:
    """Cancel all unsent (scheduled) touches in a sequence.

    Returns the count of touches that were cancelled.
    Called when: UNSUBSCRIBE reply received, or sequence manually paused.
    """
    result = await session.execute(
        update(EmailTouch)
        .where(EmailTouch.sequence_id == sequence_id)
        .where(EmailTouch.status == "scheduled")
        .values(status="cancelled")
        .returning(EmailTouch.id)
    )
    await session.flush()
    cancelled_ids = result.fetchall()
    count = len(cancelled_ids)
    if count:
        logger.info("Cancelled %d touches for sequence %s", count, sequence_id)
    return count
