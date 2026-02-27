"""Self-improvement repository — outcome tracking and suggestions."""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ImprovementSuggestion, OutcomeFeedback

logger = logging.getLogger(__name__)


async def record_outcome(
    session: AsyncSession,
    conversion_event: str,
    *,
    org_id: Optional[UUID] = None,
    sequence_id: Optional[UUID] = None,
    call_record_id: Optional[UUID] = None,
    meeting_id: Optional[UUID] = None,
    icp_score_at_time: Optional[int] = None,
    prompt_versions_snapshot: Optional[dict] = None,
    personalization_hook_used: Optional[str] = None,
    email_touch_number: Optional[int] = None,
    days_since_first_touch: Optional[int] = None,
    notes: Optional[str] = None,
) -> OutcomeFeedback:
    """Record a pipeline conversion event for future analysis."""
    feedback = OutcomeFeedback(
        org_id=org_id,
        sequence_id=sequence_id,
        call_record_id=call_record_id,
        meeting_id=meeting_id,
        conversion_event=conversion_event,
        icp_score_at_time=icp_score_at_time,
        prompt_versions_snapshot=prompt_versions_snapshot,
        personalization_hook_used=personalization_hook_used,
        email_touch_number=email_touch_number,
        days_since_first_touch=days_since_first_touch,
        notes=notes,
    )
    session.add(feedback)
    await session.flush()
    return feedback


async def add_suggestion(
    session: AsyncSession,
    category: str,
    description: str,
    *,
    source: Optional[str] = None,
    proposed_change: Optional[dict] = None,
    supporting_evidence: Optional[str] = None,
) -> ImprovementSuggestion:
    """Record an agent-proposed improvement suggestion for human review."""
    suggestion = ImprovementSuggestion(
        source=source,
        category=category,
        description=description,
        proposed_change=proposed_change,
        supporting_evidence=supporting_evidence,
        status="pending_review",
    )
    session.add(suggestion)
    await session.flush()
    return suggestion
