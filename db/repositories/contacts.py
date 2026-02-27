"""Contact repository — dedup and suppression checks."""
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Contact, SuppressionList

logger = logging.getLogger(__name__)


async def get_by_email(session: AsyncSession, email: str) -> Optional[Contact]:
    """Return the Contact with this email, or None."""
    result = await session.execute(
        select(Contact).where(Contact.email == email.lower().strip())
    )
    return result.scalar_one_or_none()


async def get_known_emails(session: AsyncSession) -> set[str]:
    """Return all known contact emails (used to skip in discovery runs)."""
    result = await session.execute(select(Contact.email))
    return {row[0] for row in result.all()}


async def upsert(session: AsyncSession, data: dict) -> Contact:
    """Insert or update a contact by email (dedup key).

    data dict keys: org_id, name, first_name, last_name, title, email,
    email_verified, hunter_score, phone, linkedin_url, is_primary, notes
    """
    data = {**data, "email": data["email"].lower().strip()}
    stmt = (
        pg_insert(Contact)
        .values(**data)
        .on_conflict_do_update(
            index_elements=["email"],
            set_={k: v for k, v in data.items() if k != "email"},
        )
        .returning(Contact)
    )
    result = await session.execute(stmt, execution_options={"populate_existing": True})
    await session.flush()
    contact = result.scalar_one()
    return contact


async def is_suppressed(session: AsyncSession, email: str) -> bool:
    """Return True if this email is on the suppression list."""
    email = email.lower().strip()
    result = await session.execute(
        select(SuppressionList.id).where(SuppressionList.email == email)
    )
    return result.scalar_one_or_none() is not None
