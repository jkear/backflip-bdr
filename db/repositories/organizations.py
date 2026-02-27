"""Organization repository — dedup and pipeline stage management."""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from dateutil.relativedelta import relativedelta
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import distinct as sa_distinct

from db.models import Contact, Event, Organization, SuppressionList

logger = logging.getLogger(__name__)


async def get_by_domain(session: AsyncSession, domain: str) -> Optional[Organization]:
    """Return the Organization with this domain, or None."""
    result = await session.execute(
        select(Organization).where(Organization.domain == domain)
    )
    return result.scalar_one_or_none()


async def get_known_domains(session: AsyncSession) -> set[str]:
    """Return all known org domains (used to skip in discovery runs)."""
    result = await session.execute(select(Organization.domain))
    return {row[0] for row in result.all()}


async def upsert(session: AsyncSession, data: dict) -> Organization:
    """Insert or update an organization by domain (dedup key).

    data dict keys: name, domain, website, description, org_type,
    employee_count_range, icp_score, icp_score_dimensions, pipeline_stage,
    why_fit, notes
    """
    stmt = (
        pg_insert(Organization)
        .values(**data)
        .on_conflict_do_update(
            index_elements=["domain"],
            set_={k: v for k, v in data.items() if k != "domain"},
        )
        .returning(Organization)
    )
    result = await session.execute(stmt, execution_options={"populate_existing": True})
    await session.flush()
    org = result.scalar_one()
    return org


async def update_stage(
    session: AsyncSession, org_id: UUID, stage: str
) -> Optional[Organization]:
    """Advance an organization to a new pipeline stage."""
    result = await session.execute(
        update(Organization)
        .where(Organization.id == org_id)
        .values(pipeline_stage=stage, updated_at=func.now())
        .returning(Organization)
    )
    await session.flush()
    return result.scalar_one_or_none()


async def get_in_event_window(
    session: AsyncSession,
    months_min: int = 4,
    months_max: int = 12,
) -> list[Organization]:
    """Return orgs that have events between months_min and months_max from today.

    months_min=4, months_max=12 means: events happening 4–12 months in the future.
    This corresponds to the model's outreach_window_open/close properties:
      - outreach_window_open  = event_date - 12 months (start outreach 12 months before)
      - outreach_window_close = event_date - 4 months  (last chance 4 months before)
    So today falls in the outreach window when: event_date is 4–12 months away.
    """
    today = datetime.now(timezone.utc).date()
    window_open = today + relativedelta(months=months_min)
    window_close = today + relativedelta(months=months_max)

    # Subquery: collect distinct org_ids that have events in the window.
    # Using a subquery avoids SELECT DISTINCT on JSON columns, which PostgreSQL
    # cannot compare for equality.
    org_ids_sq = (
        select(sa_distinct(Event.org_id))
        .where(Event.event_date >= window_open)
        .where(Event.event_date <= window_close)
        .scalar_subquery()
    )
    result = await session.execute(
        select(Organization)
        .where(Organization.id.in_(org_ids_sq))
        .where(Organization.disqualified == False)
    )
    return list(result.scalars().all())


async def get_due_for_outreach(session: AsyncSession) -> list[Organization]:
    """Return orgs where next_outreach_date <= now (due for follow-up)."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Organization)
        .where(Organization.next_outreach_date <= now)
        .where(Organization.disqualified == False)
    )
    return list(result.scalars().all())
