"""Integration tests for core repository methods."""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

# DATABASE_URL must be set in the environment before running tests.
# Example: export DATABASE_URL="postgresql+asyncpg://backflip:<password>@<host>:5432/backflip_sdr"
# See .env.example for configuration details.

from db import get_db
from db.repositories import contacts as contacts_repo
from db.repositories import events as events_repo
from db.repositories import organizations as orgs_repo
from db.repositories.pipeline import add_suppression as _add_suppression


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_upsert_and_dedup():
    """Inserting the same domain twice returns the existing org, not a new one."""
    domain = f"test-{uuid.uuid4().hex[:8]}.com"
    async with get_db() as session:
        org1 = await orgs_repo.upsert(session, {
            "name": "Test Org",
            "domain": domain,
            "pipeline_stage": "discovered",
        })
        org2 = await orgs_repo.upsert(session, {
            "name": "Test Org Updated",
            "domain": domain,
            "pipeline_stage": "enriched",
        })
    assert org1.id == org2.id, "Upsert on same domain must return same org"
    assert org2.name == "Test Org Updated", "Name should be updated on conflict"


@pytest.mark.asyncio
async def test_get_known_domains():
    """get_known_domains returns the domain we just inserted."""
    domain = f"known-{uuid.uuid4().hex[:8]}.com"
    async with get_db() as session:
        await orgs_repo.upsert(session, {
            "name": "Known Org",
            "domain": domain,
            "pipeline_stage": "discovered",
        })
    async with get_db() as session:
        domains = await orgs_repo.get_known_domains(session)
    assert domain in domains


@pytest.mark.asyncio
async def test_event_window_filter():
    """get_in_event_window returns org with event in window, not org with event outside."""
    domain_in = f"in-window-{uuid.uuid4().hex[:8]}.com"
    domain_out = f"out-window-{uuid.uuid4().hex[:8]}.com"

    async with get_db() as session:
        org_in = await orgs_repo.upsert(session, {
            "name": "In Window Org",
            "domain": domain_in,
            "pipeline_stage": "discovered",
        })
        org_out = await orgs_repo.upsert(session, {
            "name": "Out Window Org",
            "domain": domain_out,
            "pipeline_stage": "discovered",
        })
        # Event 6 months out (within 4-12 month window)
        event_date_in = date.today() + timedelta(days=6 * 30)
        await events_repo.upsert(session, org_in.id, {
            "event_name": "In-Window Conference",
            "event_date": event_date_in,
        })
        # Event 2 months out (outside 4-12 month window)
        event_date_out = date.today() + timedelta(days=2 * 30)
        await events_repo.upsert(session, org_out.id, {
            "event_name": "Out-Window Conference",
            "event_date": event_date_out,
        })

    async with get_db() as session:
        in_window = await orgs_repo.get_in_event_window(session)
    ids_in_window = {org.id for org in in_window}
    assert org_in.id in ids_in_window, "Org with event in window should be returned"
    assert org_out.id not in ids_in_window, "Org with event outside window should not be returned"


@pytest.mark.asyncio
async def test_suppression_check():
    """is_suppressed returns True for suppressed email, False for clean email."""
    suppressed_email = f"suppressed-{uuid.uuid4().hex[:8]}@example.com"
    clean_email = f"clean-{uuid.uuid4().hex[:8]}@example.com"

    async with get_db() as session:
        await _add_suppression(
            session,
            email=suppressed_email,
            domain="example.com",
            reason="Test suppression",
            source="manual",
        )

    async with get_db() as session:
        assert await contacts_repo.is_suppressed(session, suppressed_email) is True
        assert await contacts_repo.is_suppressed(session, clean_email) is False


@pytest.mark.asyncio
async def test_cancel_remaining_touches():
    """cancel_remaining_touches cancels only scheduled touches, not sent ones."""
    from db.repositories.sequences import create_sequence, cancel_remaining_touches
    from db.repositories.sequences import mark_touch_sent
    from db.repositories.organizations import upsert as org_upsert
    from db.repositories.contacts import upsert as contact_upsert

    domain = f"cancel-test-{uuid.uuid4().hex[:8]}.com"
    email = f"cancel-{uuid.uuid4().hex[:8]}@example.com"

    async with get_db() as session:
        org = await org_upsert(session, {"name": "Cancel Test Org", "domain": domain, "pipeline_stage": "discovered"})
        contact = await contact_upsert(session, {"email": email, "org_id": org.id})
        seq = await create_sequence(
            session, org.id, contact.id,
            touches=[
                {"touch_number": 1, "scheduled_date": datetime.now(timezone.utc) - timedelta(days=1), "subject": "T1", "body": "Body1"},
                {"touch_number": 2, "scheduled_date": datetime.now(timezone.utc) + timedelta(days=4), "subject": "T2", "body": "Body2"},
                {"touch_number": 3, "scheduled_date": datetime.now(timezone.utc) + timedelta(days=9), "subject": "T3", "body": "Body3"},
            ],
        )
        # Mark touch 1 as sent
        from db.models import EmailTouch
        from sqlalchemy import select as sa_select
        touches_result = await session.execute(sa_select(EmailTouch).where(EmailTouch.sequence_id == seq.id).order_by(EmailTouch.touch_number))
        touches = list(touches_result.scalars().all())
        await mark_touch_sent(session, touches[0].id, message_id="msg-001")

        # Cancel remaining (touches 2 and 3 are still scheduled)
        cancelled = await cancel_remaining_touches(session, seq.id)

    assert cancelled == 2, f"Expected 2 cancelled, got {cancelled}"


@pytest.mark.asyncio
async def test_add_suppression_idempotent():
    """add_suppression called twice for the same email does not raise."""
    from db.repositories.pipeline import add_suppression

    email = f"idempotent-{uuid.uuid4().hex[:8]}@example.com"
    async with get_db() as session:
        s1 = await add_suppression(session, email=email, source="manual")
    async with get_db() as session:
        s2 = await add_suppression(session, email=email, source="manual")

    assert s1.id == s2.id, "Second suppression call must return the existing row"
