"""Backflip Media — Lead-to-Meeting Pipeline Orchestrator.

Entry point for the full pipeline. Wires all four teams in sequence:
  Stage 1: LeadDiscoveryTeam
  Stage 2: OutreachStrategyTeam
  Stage 3: ResponseHandlingTeam    (triggered per inbound reply)
  Stage 4: MeetingBookingTeam      (triggered after call permission granted)

Usage:
  # Discover and build outreach campaign
  python agent.py discover --limit 10

  # Process an inbound reply
  python agent.py reply --lead-id lead-001 --reply "Sure, happy to chat!"

  # Confirm a meeting slot (requires --start and --end ISO datetimes)
  python agent.py confirm --lead-id lead-001 --contact-name "Jane Smith" \
      --contact-email jane@example.com --company "Acme Corp" \
      --start "2026-03-03T10:00:00" --end "2026-03-03T10:30:00"
"""
import argparse
import asyncio
import json
import logging
import os
import sys
import urllib.parse
import uuid
from datetime import date
from pathlib import Path

from dateutil.relativedelta import relativedelta

# Must run before any LlmAgent is instantiated
from vertex_ai_init import init_vertex_ai

init_vertex_ai()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from teams.lead_discovery import lead_discovery_team
from teams.outreach_strategy import outreach_strategy_team
from teams.response_handling import response_handling_team
from teams.meeting_booking import meeting_booking_team

import db.repositories.organizations as org_repo
import db.repositories.contacts as contact_repo
import db.repositories.events as event_repo
import db.repositories.sequences as seq_repo
import db.repositories.pipeline as pipeline_repo
from db.connection import get_db

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


async def run_agent(team, session_id: str, message: str) -> dict:
    """Run a team and return the final session state."""
    session_service = InMemorySessionService()
    app_name = f"backflip_{team.name.lower()}"
    await session_service.create_session(
        app_name=app_name,
        user_id="backflip_pipeline",
        session_id=session_id,
    )
    runner = Runner(
        agent=team,
        app_name=app_name,
        session_service=session_service,
    )
    content = Content(role="user", parts=[Part(text=message)])
    final_response = ""
    async for event in runner.run_async(
        user_id="backflip_pipeline",
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response += part.text

    session = await session_service.get_session(
        app_name=app_name,
        user_id="backflip_pipeline",
        session_id=session_id,
    )
    return dict(session.state) if session else {}


async def run_discovery(lead_limit: int = 10) -> dict:
    """Stage 1 + 2: Discover leads and build email campaign."""

    # --- Pre-flight: query DB for known domains/emails and build event window ---
    known_domains: set[str] = set()
    known_emails: set[str] = set()
    try:
        async with get_db() as session:
            known_domains = await org_repo.get_known_domains(session)
            known_emails = await contact_repo.get_known_emails(session)
    except Exception as e:
        logger.warning("DB pre-flight query failed (pipeline continues): %s", e, exc_info=True)

    today = date.today()
    window_open = today + relativedelta(months=4)
    window_close = today + relativedelta(months=12)
    target_event_window_context = (
        f"Today is {today}. Target organizations with events scheduled between "
        f"{window_open} (4 months out) and {window_close} (12 months out)."
    )

    print(f"\n[Stage 1] Discovering up to {lead_limit} B2B event organizers and associations...")
    discovery_state = await run_agent(
        lead_discovery_team,
        session_id=f"discovery_{uuid.uuid4().hex[:8]}",
        message=json.dumps({
            "lead_limit": lead_limit,
            "known_domains": "\n".join(sorted(known_domains)) if known_domains else "(none yet)",
            "known_contact_emails": "\n".join(sorted(known_emails)) if known_emails else "(none yet)",
            "target_event_window_context": target_event_window_context,
        }),
    )

    scored = discovery_state.get("scored_leads", {})
    qualified = scored.get("qualified_leads", []) if isinstance(scored, dict) else []
    print(f"  Found {len(qualified)} qualified leads (ICP score >= 60)")

    if not qualified:
        print("  No qualified leads found. Adjust search queries or ICP threshold.")
        return discovery_state

    # --- Persist Stage 1 results: orgs, contacts, events ---
    try:
        async with get_db() as session:
            for lead in qualified:
                website = lead.get("website", "")
                parsed = urllib.parse.urlparse(website)
                netloc = parsed.netloc or website  # fallback for scheme-less URLs
                domain = netloc.removeprefix("www.")
                if not domain:
                    logger.warning("Lead %r has no parseable domain — skipping", lead.get("name"))
                    continue

                org_data = {
                    "name": lead.get("name", ""),
                    "domain": domain,
                    "website": website,
                    "description": lead.get("description", ""),
                    "icp_score": lead.get("score"),
                    "icp_score_dimensions": lead.get("score_dimensions"),
                    "why_fit": lead.get("why_fit", ""),
                    "pipeline_stage": "scored",
                }
                org = await org_repo.upsert(session, org_data)

                for contact in lead.get("contacts", []):
                    contact_data = {
                        "org_id": org.id,
                        "name": contact.get("name", ""),
                        "title": contact.get("title", ""),
                        "email": contact.get("email", ""),
                        "email_verified": contact.get("verified", False),
                    }
                    await contact_repo.upsert(session, contact_data)

                event_type = lead.get("event_type")
                if event_type:
                    event_data = {
                        "event_type": event_type,
                        "event_name": lead.get("name", event_type),
                    }
                    await event_repo.upsert(session, org.id, event_data)

        logger.info("Persisted %d qualified leads (orgs/contacts/events)", len(qualified))
    except Exception as e:
        logger.warning("DB write failed after Stage 1 (pipeline continues): %s", e, exc_info=True)

    print("\n[Stage 2] Building personalized email sequences...")
    outreach_state = await run_agent(
        outreach_strategy_team,
        session_id=f"outreach_{uuid.uuid4().hex[:8]}",
        message=json.dumps({"scored_leads": scored}),
    )

    campaign = outreach_state.get("campaign_json", {})
    campaign_path = OUTPUT_DIR / "campaign.json"
    campaign_path.write_text(json.dumps(campaign, indent=2))
    print(f"  Campaign written to {campaign_path}")
    print(f"  Sequences built: {campaign.get('lead_count', 0)}")

    # --- Persist Stage 2 results: email sequences ---
    sequences = campaign.get("sequences", []) if isinstance(campaign, dict) else []
    if sequences:
        try:
            async with get_db() as session:
                # Build lookup of domain -> org for matching sequences to orgs
                persisted_orgs: dict[str, object] = {}
                for lead in qualified:
                    website = lead.get("website", "")
                    parsed = urllib.parse.urlparse(website)
                    netloc = parsed.netloc or website  # fallback for scheme-less URLs
                    domain = netloc.removeprefix("www.")
                    if domain:
                        org = await org_repo.get_by_domain(session, domain)
                        if org:
                            persisted_orgs[lead.get("name", "").lower()] = org

                for seq in sequences:
                    lead_name = seq.get("lead_name", "")
                    emails = seq.get("emails", [])

                    # Resolve org by lead name (case-insensitive match)
                    org = persisted_orgs.get(lead_name.lower())
                    if org is None:
                        logger.warning(
                            "No org found for sequence lead_name=%r — skipping sequence persist",
                            lead_name,
                        )
                        continue

                    # Resolve primary contact from the sequence contacts list
                    contact_email = None
                    seq_contacts = seq.get("contacts", [])
                    if seq_contacts:
                        contact_email = seq_contacts[0]

                    contact = None
                    if contact_email:
                        contact = await contact_repo.get_by_email(session, contact_email)

                    # Build touch dicts expected by create_sequence
                    touches = []
                    for em in emails:
                        touches.append({
                            "touch_number": em.get("touch_number"),
                            "scheduled_date": None,  # send_day offset — no absolute date yet
                            "subject": em.get("subject", ""),
                            "body": em.get("body", ""),
                        })

                    # Derive personalization hook from the first touch of the matching lead
                    hook = None
                    for candidate in qualified:
                        if candidate.get("name", "").lower() == lead_name.lower():
                            hook = candidate.get("personalization_hook")
                            break

                    icp_raw = outreach_state.get("icp_profile")
                    if isinstance(icp_raw, str):
                        try:
                            icp_snapshot = json.loads(icp_raw)
                        except json.JSONDecodeError:
                            logger.warning(
                                "icp_profile in session state is not valid JSON — icp_snapshot will not be persisted"
                            )
                            icp_snapshot = None
                    elif isinstance(icp_raw, dict):
                        icp_snapshot = icp_raw
                    else:
                        icp_snapshot = None

                    await seq_repo.create_sequence(
                        session,
                        org_id=org.id,
                        contact_id=contact.id if contact else None,
                        touches=touches,
                        hook=hook,
                        icp_snapshot=icp_snapshot,
                    )

            logger.info("Persisted %d email sequences", len(sequences))
        except Exception as e:
            logger.warning("DB write failed after Stage 2 (pipeline continues): %s", e, exc_info=True)

    return {**discovery_state, **outreach_state}


async def run_reply_handler(lead_id: str, reply_text: str, contact_email: str = "") -> dict:
    """Stage 3: Classify an inbound reply and draft next action."""
    print(f"\n[Stage 3] Classifying reply from lead {lead_id}...")
    state = await run_agent(
        response_handling_team,
        session_id=f"reply_{lead_id}",
        message=json.dumps({
            "inbound_reply": reply_text,
            "lead_id": lead_id,
        }),
    )

    classification_data = state.get("reply_classification", {})
    classification = classification_data.get("classification", "UNKNOWN")

    print(f"  Classification: {classification}")
    print(f"  Key phrase: \"{classification_data.get('key_phrase', '')}\"")

    perm_email = state.get("call_permission_email", {})
    if perm_email and not perm_email.get("skipped"):
        print(f"  Call permission email drafted (awaiting reply): {perm_email.get('subject', '')}")

    nurture = state.get("nurture_schedule", {})
    if nurture and not nurture.get("skipped"):
        print(f"  Nurture scheduled for: {nurture.get('recontact_date', '')}")

    # --- Resolve org/contact IDs from email if provided ---
    _reply_org_id = None
    _reply_contact_id = None
    if contact_email:
        try:
            async with get_db() as session:
                _contact = await contact_repo.get_by_email(session, contact_email)
                _reply_org_id = _contact.org_id if _contact else None
                _reply_contact_id = _contact.id if _contact else None
        except Exception as e:
            logger.warning(
                "DB lookup for contact_email=%r in Stage 3 failed: %s", contact_email, e, exc_info=True
            )

    # --- Persist reply + classification ---
    try:
        async with get_db() as session:
            await pipeline_repo.record_reply(
                session,
                org_id=_reply_org_id,
                contact_id=_reply_contact_id,
                touch_id=None,
                reply_text=reply_text,
                classification=classification,
                classification_reasoning=classification_data.get("reasoning"),
                key_phrase=classification_data.get("key_phrase"),
                recontact_date=classification_data.get("recontact_date"),
                recontact_note=classification_data.get("recontact_note"),
            )

            if classification == "UNSUBSCRIBE":
                email = classification_data.get("email", "")
                if email:
                    await pipeline_repo.add_suppression(
                        session,
                        email=email,
                        reason="unsubscribed via reply",
                        source="unsubscribe_reply",
                    )
                    logger.info("Added suppression for %s (lead_id=%s)", email, lead_id)
                else:
                    logger.warning(
                        "UNSUBSCRIBE classification for lead_id=%s but no email in "
                        "classification_data — skipping suppression",
                        lead_id,
                    )

        logger.info("Persisted reply classification=%s for lead_id=%s", classification, lead_id)
    except Exception as e:
        logger.warning("DB write failed after Stage 3 (pipeline continues): %s", e, exc_info=True)

    result_path = OUTPUT_DIR / f"reply_{lead_id}.json"
    result_path.write_text(json.dumps(state, indent=2))
    print(f"  Result saved to {result_path}")
    return state


async def run_meeting_booking(
    lead_id: str,
    contact_name: str,
    contact_email: str,
    company_name: str,
    why_fit: str,
    call_permission_granted: bool,
    contact_phone: str = "",
    confirmed_slot: dict = None,
) -> dict:
    """Stage 4: Place call (if permitted) or propose slots by email."""
    print(f"\n[Stage 4] Meeting booking for {company_name} ({lead_id})...")
    print(f"  Call permission granted: {call_permission_granted}")

    call_permission_record = {
        "lead_id": lead_id,
        "contact_email": contact_email,
        "contact_name": contact_name,
        "company_name": company_name,
        "call_permission_granted": call_permission_granted,
        "contact_phone": contact_phone,
        "why_fit": why_fit,
    }

    payload = {"call_permission_record": call_permission_record}
    if confirmed_slot:
        payload["confirmed_slot"] = confirmed_slot

    state = await run_agent(
        meeting_booking_team,
        session_id=f"booking_{lead_id}",
        message=json.dumps(payload),
    )

    call_outcome = state.get("call_outcome", {})
    print(f"  Call status: {call_outcome.get('call_status', 'N/A')}")

    confirmation = state.get("confirmation", {})
    if confirmation and not confirmation.get("skipped"):
        print(f"  Event created: {confirmation.get('event_id', '')}")
        print(f"  Event verified: {confirmation.get('event_verified', False)}")
        print(f"  Meet link: {confirmation.get('meet_link', '')}")

    # --- Resolve org/contact IDs from contact_email ---
    _booking_org_id = None
    _booking_contact_id = None
    if contact_email:
        try:
            async with get_db() as session:
                _contact = await contact_repo.get_by_email(session, contact_email)
                _booking_org_id = _contact.org_id if _contact else None
                _booking_contact_id = _contact.id if _contact else None
        except Exception as e:
            logger.warning(
                "DB lookup for contact_email=%r in Stage 4 failed: %s", contact_email, e, exc_info=True
            )

    # --- Persist call record and meeting ---
    try:
        async with get_db() as session:
            call_record = await pipeline_repo.record_call(
                session,
                org_id=_booking_org_id,
                contact_id=_booking_contact_id,
                call_permission_granted=call_permission_granted,
                elevenlabs_call_id=call_outcome.get("call_id"),
                elevenlabs_agent_id=call_outcome.get("agent_id"),
                call_status=call_outcome.get("call_status"),
                transcript=call_outcome.get("transcript"),
                call_successful=call_outcome.get("call_successful"),
                agreed_slot=call_outcome.get("agreed_slot"),
                notes=call_outcome.get("notes"),
            )

            if confirmation and not confirmation.get("skipped"):
                await pipeline_repo.record_meeting(
                    session,
                    org_id=_booking_org_id,
                    contact_id=_booking_contact_id,
                    call_record_id=call_record.id,
                    google_event_id=confirmation.get("event_id"),
                    html_link=confirmation.get("html_link"),
                    meet_link=confirmation.get("meet_link"),
                    scheduled_start=confirmation.get("start_time"),
                    scheduled_end=confirmation.get("end_time"),
                    timezone_str=confirmation.get("timezone"),
                    confirmation_email_draft=confirmation.get("confirmation_email_draft"),
                    event_verified=bool(confirmation.get("event_verified", False)),
                )

        logger.info(
            "Persisted call record and meeting for lead_id=%s call_status=%s",
            lead_id,
            call_outcome.get("call_status"),
        )
    except Exception as e:
        logger.warning("DB write failed after Stage 4 (pipeline continues): %s", e, exc_info=True)

    result_path = OUTPUT_DIR / f"booking_{lead_id}.json"
    result_path.write_text(json.dumps(state, indent=2))
    print(f"  Result saved to {result_path}")
    return state


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backflip Media Lead-to-Meeting Pipeline"
    )
    sub = parser.add_subparsers(dest="command")

    discover = sub.add_parser("discover", help="Run lead discovery + outreach campaign")
    discover.add_argument("--limit", type=int, default=10, help="Max leads to discover")

    reply = sub.add_parser("reply", help="Process an inbound reply")
    reply.add_argument("--lead-id", required=True)
    reply.add_argument("--reply", required=True, help="The reply text from the prospect")
    reply.add_argument("--contact-email", default="", help="Contact email to resolve org/contact IDs (optional)")

    book = sub.add_parser("book", help="Trigger meeting booking for a lead")
    book.add_argument("--lead-id", required=True)
    book.add_argument("--contact-name", required=True)
    book.add_argument("--contact-email", required=True)
    book.add_argument("--company", required=True)
    book.add_argument("--why-fit", default="B2B event organizer needing digital ads")
    book.add_argument("--phone", default="", help="E.164 phone number (optional)")
    book.add_argument(
        "--permission",
        action="store_true",
        default=False,
        help="Set when call permission has been granted",
    )

    confirm = sub.add_parser("confirm", help="Confirm a specific meeting slot for a lead")
    confirm.add_argument("--lead-id", required=True)
    confirm.add_argument("--contact-name", required=True)
    confirm.add_argument("--contact-email", required=True)
    confirm.add_argument("--company", required=True)
    confirm.add_argument("--start", required=True, help="Meeting start datetime in ISO 8601 format (e.g. 2026-03-03T10:00:00)")
    confirm.add_argument("--end", required=True, help="Meeting end datetime in ISO 8601 format (e.g. 2026-03-03T10:30:00)")
    confirm.add_argument("--timezone", default="America/Chicago", help="IANA timezone name (default: America/Chicago)")
    confirm.add_argument("--why-fit", default="B2B event organizer needing digital ads")

    return parser


if __name__ == "__main__":
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.command == "discover":
        asyncio.run(run_discovery(lead_limit=args.limit))

    elif args.command == "reply":
        asyncio.run(run_reply_handler(
            lead_id=args.lead_id,
            reply_text=args.reply,
            contact_email=getattr(args, "contact_email", ""),
        ))

    elif args.command == "book":
        asyncio.run(run_meeting_booking(
            lead_id=args.lead_id,
            contact_name=args.contact_name,
            contact_email=args.contact_email,
            company_name=args.company,
            why_fit=args.why_fit,
            call_permission_granted=args.permission,
            contact_phone=args.phone,
        ))

    elif args.command == "confirm":
        confirmed_slot = {
            "slot": {
                "start_datetime": args.start,
                "end_datetime": args.end,
                "timezone": args.timezone,
            },
            "contact_name": args.contact_name,
            "contact_email": args.contact_email,
            "company_name": args.company,
            "lead_id": args.lead_id,
        }
        asyncio.run(run_meeting_booking(
            lead_id=args.lead_id,
            contact_name=args.contact_name,
            contact_email=args.contact_email,
            company_name=args.company,
            why_fit=args.why_fit,
            call_permission_granted=False,
            confirmed_slot=confirmed_slot,
        ))

    else:
        parser.print_help()
        sys.exit(1)
