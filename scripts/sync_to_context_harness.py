"""Sync PostgreSQL CRM data to context_harness_sync/ Markdown files.

Run after pipeline stages to keep the context-harness index fresh:

    uv run python scripts/sync_to_context_harness.py

Reads from PostgreSQL via existing SQLAlchemy repos and writes Markdown
files that `ctx sync` will ingest into the FTS5 SQLite store.

CTX_SYNC_DIR controls the output directory (default: ./context_harness_sync).
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

# Resolve project root so imports work when run from any cwd
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from sqlalchemy import select

from db.connection import get_db
from db.models import (
    EmailSequence,
    EmailTouch,
    Organization,
    OutcomeFeedback,
)
import db.repositories.pipeline as pipeline_repo

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SYNC_DIR = Path(os.environ.get("CTX_SYNC_DIR", str(_ROOT / "context_harness_sync")))


def _safe_name(s: str) -> str:
    """Slugify a string for use as a filename component."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s).strip("_.")


async def _sync_sequences(sync_dir: Path) -> int:
    """Write one Markdown file per org containing all email touches."""
    seq_dir = sync_dir / "sequences"
    seq_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    async with get_db() as session:
        # Load all orgs that have at least one sequence
        org_ids_result = await session.execute(
            select(EmailSequence.org_id).where(EmailSequence.org_id.isnot(None)).distinct()
        )
        org_ids = [row[0] for row in org_ids_result.all()]

        orgs_result = await session.execute(
            select(Organization).where(Organization.id.in_(org_ids))
        )
        orgs = list(orgs_result.scalars().all())

        for org in orgs:
            seq_result = await session.execute(
                select(EmailSequence)
                .where(EmailSequence.org_id == org.id)
                .order_by(EmailSequence.created_at)
            )
            sequences = list(seq_result.scalars().all())

            lines = [
                f"# Email Sequence: {org.name} ({org.domain})",
                f"ICP Score: {org.icp_score or 'N/A'} | Stage: {org.pipeline_stage}",
                "",
            ]

            for seq in sequences:
                if seq.personalization_hook:
                    lines.append(f"Personalization Hook: {seq.personalization_hook}")
                    lines.append("")

                touch_result = await session.execute(
                    select(EmailTouch)
                    .where(EmailTouch.sequence_id == seq.id)
                    .order_by(EmailTouch.touch_number)
                )
                touches = list(touch_result.scalars().all())

                for touch in touches:
                    subject = touch.subject or "(no subject)"
                    body = touch.body or "(no body)"
                    lines.append(f"## Touch {touch.touch_number} — Subject: {subject}")
                    lines.append(body)
                    lines.append("")

            filename = seq_dir / f"{_safe_name(org.domain)}.md"
            filename.write_text("\n".join(lines), encoding="utf-8")
            written += 1

    return written


async def _sync_replies(sync_dir: Path) -> int:
    """Write one Markdown file per org containing all classified replies."""
    replies_dir = sync_dir / "replies"
    replies_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    async with get_db() as session:
        orgs_result = await session.execute(select(Organization))
        orgs = list(orgs_result.scalars().all())

        for org in orgs:
            history = await pipeline_repo.get_org_history(session, org.id)
            replies = history.get("replies", [])
            if not replies:
                continue

            lines = [
                f"# Reply History: {org.name} ({org.domain})",
                f"Stage: {org.pipeline_stage}",
                "",
            ]

            for reply in replies:
                classification = reply.get("classification", "UNKNOWN")
                text = reply.get("reply_text", "")
                key_phrase = reply.get("key_phrase", "")
                reasoning = reply.get("classification_reasoning", "")
                received = reply.get("received_at", "")

                lines.append(f"## Reply [{classification}] — {received}")
                lines.append(f"Text: {text}")
                if key_phrase:
                    lines.append(f"Key Phrase: {key_phrase}")
                if reasoning:
                    lines.append(f"Reasoning: {reasoning}")
                lines.append("")

            filename = replies_dir / f"{_safe_name(org.domain)}.md"
            filename.write_text("\n".join(lines), encoding="utf-8")
            written += 1

    return written


async def _sync_outcomes(sync_dir: Path) -> int:
    """Write outcomes/feedback.md with all conversion feedback."""
    outcomes_dir = sync_dir / "outcomes"
    outcomes_dir.mkdir(parents=True, exist_ok=True)

    async with get_db() as session:
        result = await session.execute(
            select(OutcomeFeedback, Organization)
            .join(Organization, OutcomeFeedback.org_id == Organization.id, isouter=True)
            .order_by(OutcomeFeedback.recorded_at)
        )
        rows = result.all()

    if not rows:
        return 0

    lines = [
        "# Conversion Outcomes and Feedback",
        "Hooks and strategies that led to booked meetings.",
        "",
    ]

    for feedback, org in rows:
        org_name = org.name if org else "Unknown"
        org_domain = org.domain if org else "unknown"
        lines.append(
            f"## Outcome: {feedback.conversion_event or 'N/A'} — {org_name} ({org_domain})"
        )
        lines.append(f"Recorded: {feedback.recorded_at}")
        if feedback.personalization_hook_used:
            lines.append(f"Hook Used: {feedback.personalization_hook_used}")
        if feedback.icp_score_at_time:
            lines.append(f"ICP Score: {feedback.icp_score_at_time}")
        if feedback.email_touch_number:
            lines.append(f"Converted on Touch: {feedback.email_touch_number}")
        if feedback.days_since_first_touch is not None:
            lines.append(f"Days Since First Touch: {feedback.days_since_first_touch}")
        if feedback.notes:
            lines.append(f"Notes: {feedback.notes}")
        lines.append("")

    feedback_path = outcomes_dir / "feedback.md"
    feedback_path.write_text("\n".join(lines), encoding="utf-8")
    return 1


async def _sync_icp_snapshots(sync_dir: Path) -> int:
    """Write one ICP snapshot Markdown file per org (first sequence with a snapshot)."""
    icp_dir = sync_dir / "icp_snapshots"
    icp_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    async with get_db() as session:
        result = await session.execute(
            select(EmailSequence, Organization)
            .join(Organization, EmailSequence.org_id == Organization.id)
            .where(EmailSequence.icp_profile_snapshot.isnot(None))
            .order_by(Organization.id, EmailSequence.created_at)
        )
        rows = result.all()

    seen_org_ids: set = set()
    for seq, org in rows:
        if org.id in seen_org_ids:
            continue
        seen_org_ids.add(org.id)

        snapshot = seq.icp_profile_snapshot or {}
        lines = [
            f"# ICP Snapshot: {org.name} ({org.domain})",
            f"Stage: {org.pipeline_stage} | Score: {org.icp_score or 'N/A'}",
            "",
        ]

        vp = snapshot.get("value_proposition", "")
        if vp:
            lines.append(f"## Value Proposition\n{vp}\n")

        for key, label in (
            ("segment_a_pain_points", "Segment A Pain Points"),
            ("segment_b_pain_points", "Segment B Pain Points"),
        ):
            points = snapshot.get(key, [])
            if points:
                lines.append(f"## {label}")
                for pt in points:
                    lines.append(f"- {pt}")
                lines.append("")

        summary = snapshot.get("summary", "")
        if summary:
            lines.append(f"## Summary\n{summary}\n")

        filename = icp_dir / f"{_safe_name(org.domain)}.md"
        filename.write_text("\n".join(lines), encoding="utf-8")
        written += 1

    return written


async def main() -> None:
    SYNC_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Syncing to %s ...", SYNC_DIR.resolve())

    seq_count = await _sync_sequences(SYNC_DIR)
    logger.info("  sequences/: %d files written", seq_count)

    replies_count = await _sync_replies(SYNC_DIR)
    logger.info("  replies/: %d files written", replies_count)

    outcomes_count = await _sync_outcomes(SYNC_DIR)
    logger.info("  outcomes/: %d files written", outcomes_count)

    icp_count = await _sync_icp_snapshots(SYNC_DIR)
    logger.info("  icp_snapshots/: %d files written", icp_count)

    total = seq_count + replies_count + outcomes_count + icp_count
    logger.info("Done. Total files written: %d", total)


if __name__ == "__main__":
    asyncio.run(main())
