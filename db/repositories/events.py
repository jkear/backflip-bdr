"""Event repository — outreach window queries."""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Event

logger = logging.getLogger(__name__)


async def upsert(
    session: AsyncSession, org_id: UUID, event_data: dict
) -> Event:
    """Insert or update an event for an org.

    Dedup key: (org_id, event_name). If an event with the same name
    already exists for this org, update it.

    event_data keys: event_name, event_type, event_date, event_date_approximate,
    event_date_notes, estimated_attendees, registration_url, is_recurring,
    recurrence_period
    """
    data = {"org_id": org_id, **event_data}
    stmt = (
        pg_insert(Event)
        .values(**data)
        .on_conflict_do_update(
            index_elements=["org_id", "event_name"],
            set_={k: v for k, v in data.items() if k not in ("org_id", "event_name")},
        )
        .returning(Event)
    )
    result = await session.execute(stmt, execution_options={"populate_existing": True})
    await session.flush()
    event = result.scalar_one()
    return event


async def get_upcoming_events(
    session: AsyncSession,
    months_min: int = 4,
    months_max: int = 12,
) -> list[Event]:
    """Return events with event_date between months_min and months_max from today.

    months_min=4, months_max=12 means: events happening 4–12 months in the future.
    This corresponds to the model's outreach_window_open/close properties:
      - outreach_window_open  = event_date - 12 months (start outreach 12 months before)
      - outreach_window_close = event_date - 4 months  (last chance 4 months before)
    So today falls in the outreach window when: event_date is 4–12 months away.
    """
    today = datetime.now(timezone.utc).date()
    window_open = today + relativedelta(months=months_min)
    window_close = today + relativedelta(months=months_max)

    result = await session.execute(
        select(Event)
        .where(Event.event_date >= window_open)
        .where(Event.event_date <= window_close)
        .order_by(Event.event_date)
    )
    return list(result.scalars().all())


async def get_by_org(session: AsyncSession, org_id: UUID) -> list[Event]:
    """Return all events for an organization."""
    result = await session.execute(
        select(Event).where(Event.org_id == org_id).order_by(Event.event_date)
    )
    return list(result.scalars().all())
