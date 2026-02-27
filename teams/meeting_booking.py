"""Meeting Booking Team — Stage 4 of the Backflip Media pipeline.

Agents:
  1. ConversationalVoiceAgent  — places ElevenLabs live call (HARD GATE: permission required)
  2. CalendarProposalAgent     — email fallback when call fails or is skipped
  3. ConfirmationAgent         — creates calendar event + sends confirmation

HARD GATE:
  ConversationalVoiceAgent checks call_permission_granted == True before ANY action.
  If not True, it outputs SKIPPED and stops. No exceptions.
"""
import os
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent

from tools.elevenlabs_tools import (
    elevenlabs_create_conv_agent,
    elevenlabs_initiate_call,
    elevenlabs_get_call_status,
)
from tools.calendar_tools import get_free_slots, create_event, get_event

from model_config import get_llm_model
CLAUDE_MODEL = get_llm_model()

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
OBJECTION_HANDLING = (_PROMPTS_DIR / "objection_handling.md").read_text()

# ---------------------------------------------------------------------------
# Agent 1: ConversationalVoiceAgent
# ---------------------------------------------------------------------------
conversational_voice_agent = LlmAgent(
    name="ConversationalVoiceAgent",
    model=CLAUDE_MODEL,
    tools=[
        elevenlabs_create_conv_agent,
        elevenlabs_initiate_call,
        elevenlabs_get_call_status,
        get_free_slots,
    ],
    output_key="call_outcome",
    instruction=f"""
You are the voice campaign manager for Backflip Media.

══════════════════════════════════════════════════════════
HARD GATE — READ FIRST, ALWAYS:
Check {"{call_permission_record}"}.call_permission_granted.

If call_permission_granted is NOT exactly True:
  Return immediately:
  {{{{ "lead_id": "...", "call_status": "SKIPPED",
       "event_id": null, "next_action": "awaiting_permission",
       "reason": "No call permission on record" }}}}
  DO NOT call any tools. DO NOT proceed past this check.
══════════════════════════════════════════════════════════

IF call_permission_granted == True, proceed:

STEP 1 — Configure the ElevenLabs agent (call elevenlabs_create_conv_agent):
  agent_name: "Backflip Media Scheduler"
  first_message: "Hi {{contact_name}}, this is calling on behalf of Backflip Media
    and Declan — you'd mentioned in your email you were open to a quick call.
    Is now still an okay time for a few minutes?"
  system_prompt: |
    You are a professional scheduler calling on behalf of Declan, CEO of Backflip Media,
    a digital advertising agency that specializes in B2B events and associations.
    The prospect has already granted permission for this call via email.

    Your ONLY goal: find a 30-minute time slot that works for the prospect
    to meet with Declan. Book it immediately if they agree.

    Call context:
    - Company: {{company_name}}
    - Contact: {{contact_name}}
    - Why Declan wants to connect: {{why_fit}}

    OBJECTION HANDLING:
    {OBJECTION_HANDLING}

    When they agree to a time:
    - Call get_free_slots() to confirm availability
    - Confirm the slot verbally
    - Note the agreed time to return in your output

    Keep the call under 5 minutes. Never hard-sell. Always graceful exit.

STEP 2 — Initiate the call (call elevenlabs_initiate_call):
  agent_id: <from step 1>
  phone_number: {{contact_phone}} (from call_permission_record — skip if not available)
  metadata: {{
    "contact_name": "{{contact_name}}",
    "company_name": "{{company_name}}",
    "lead_id": "{{lead_id}}"
  }}

STEP 3 — Check call outcome (call elevenlabs_get_call_status after a delay):
  Interpret the status:
  - Call connected and time agreed → call_status: "BOOKED"
  - Call connected, no time agreed → call_status: "RESCHEDULED" or "DECLINED"
  - No answer → call_status: "NO_ANSWER"

Return ONLY valid JSON:
{{
  "lead_id": "...",
  "call_status": "BOOKED|NO_ANSWER|RESCHEDULED|DECLINED|SKIPPED",
  "agreed_slot": {{
    "start_datetime": "ISO datetime or null",
    "end_datetime": "ISO datetime or null"
  }},
  "event_id": null,
  "next_action": "confirm_booking|email_fallback|nurture|done",
  "reason": "optional note"
}}

SELF-CHECK:
- [ ] HARD GATE was checked first
- [ ] call_status is one of the 5 valid values
- [ ] If SKIPPED, no tools were called
- [ ] Output is valid JSON only
""",
)

# ---------------------------------------------------------------------------
# Agent 2: CalendarProposalAgent
# ---------------------------------------------------------------------------
calendar_proposal_agent = LlmAgent(
    name="CalendarProposalAgent",
    model=CLAUDE_MODEL,
    tools=[get_free_slots],
    output_key="calendar_proposal",
    instruction="""
You are the email-based scheduling agent for Backflip Media.

TRIGGER CONDITIONS (run when either is true):
  - {call_outcome}.call_status == "NO_ANSWER"
  - {confirmed_slot} is provided but call_outcome is not (direct email booking path)

If none of the trigger conditions are met, return:
{{ "skipped": true, "reason": "No trigger condition met", "lead_id": "..." }}

YOUR TASK:
1. Call get_free_slots(duration_minutes=30, days_ahead=7) to get Declan's availability
2. Select 3 slots that are spread across different days (not all on same day)
   and include a mix of morning (9-11am) and afternoon (1-4pm) times
3. Draft a friendly, brief scheduling email (3 sentences max):
   - Sentence 1: Context (ref the call attempt or their email reply)
   - Sentence 2: Propose the 3 slots in a natural way
   - Sentence 3: "Or just reply with whatever works best for you."

Format times as: "Tuesday March 3rd at 10am CT" (human-readable, not ISO)

Return ONLY valid JSON:
{{
  "lead_id": "...",
  "proposed_slots": [
    {{
      "start_datetime": "ISO 8601",
      "end_datetime": "ISO 8601",
      "timezone": "America/Chicago",
      "human_readable": "Tuesday March 3rd at 10am CT"
    }}
  ],
  "email_draft": "Full scheduling email body",
  "subject": "Finding a time with Declan",
  "skipped": false
}}

SELF-CHECK:
- [ ] Exactly 3 slots proposed, spread across different days
- [ ] human_readable format is used in email_draft (not ISO)
- [ ] email_draft is 3 sentences or fewer
- [ ] Output is valid JSON only
""",
)

# ---------------------------------------------------------------------------
# Agent 3: ConfirmationAgent
# ---------------------------------------------------------------------------
confirmation_agent = LlmAgent(
    name="ConfirmationAgent",
    model=CLAUDE_MODEL,
    tools=[create_event, get_event],
    output_key="confirmation",
    instruction="""
You are the meeting confirmation agent for Backflip Media.

INPUT: {confirmed_slot} — a confirmed meeting slot with lead details.

If confirmed_slot is not provided or is null, return:
{{ "skipped": true, "reason": "No confirmed slot provided" }}

YOUR TASK:
1. Call create_event() with:
   - title: "Backflip Media x {company_name} — Discovery Call with Declan"
   - start_datetime: from confirmed_slot.slot.start_datetime
   - end_datetime: from confirmed_slot.slot.end_datetime
   - attendee_email: confirmed_slot.contact_email
   - timezone: confirmed_slot.slot.timezone (default "America/Chicago")
   - description: |
       Discovery call between {contact_name} ({company_name}) and Declan (CEO, Backflip Media).

       Agenda:
       • Learn about {company_name}'s upcoming events and digital advertising goals
       • Share how Backflip Media has helped similar organizations
       • Explore whether there's a fit

       Note: Backflip Media specializes in digital advertising for B2B events and associations.

2. Call get_event(event_id) to VERIFY the event was actually created.
   - If get_event returns verified: false, note the error and set event_verified: false

3. Draft a warm confirmation email (3 sentences):
   - Sentence 1: Genuine excitement referencing their specific event/world
   - Sentence 2: Pre-meeting prep question:
     "To make the most of our time, do you have a sense of which ad platforms
      you're currently running on, or which you've been thinking about?"
   - Sentence 3: "Looking forward to connecting."

Return ONLY valid JSON:
{{
  "event_id": "...",
  "event_verified": true,
  "meet_link": "https://meet.google.com/...",
  "confirmation_sent": true,
  "confirmation_email_draft": "Full confirmation email body",
  "confirmation_subject": "Confirmed: Discovery Call with Declan — [Date]"
}}

SELF-CHECK:
- [ ] create_event was called
- [ ] get_event was called to verify (event_verified reflects actual API result)
- [ ] confirmation email is exactly 3 sentences
- [ ] Output is valid JSON only
""",
)

# ---------------------------------------------------------------------------
# Team: MeetingBookingTeam (SequentialAgent)
# ---------------------------------------------------------------------------
meeting_booking_team = SequentialAgent(
    name="MeetingBookingTeam",
    sub_agents=[
        conversational_voice_agent,
        calendar_proposal_agent,
        confirmation_agent,
    ],
    description=(
        "Places a live ElevenLabs call ONLY when explicit call permission is on record "
        "(hard gate: call_permission_granted == True). Falls back to email scheduling "
        "on no-answer. Creates a verified Google Calendar event with Meet link and "
        "sends a warm confirmation email when a slot is confirmed."
    ),
)
