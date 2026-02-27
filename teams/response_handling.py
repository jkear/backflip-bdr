"""Response Handling Team — Stage 3 of the Backflip Media pipeline.

Agents:
  1. ResponseClassifierAgent  — classifies every inbound reply
  2. CallPermissionAgent      — drafts call-permission email for INTERESTED leads
  3. NurtureAgent             — schedules re-contact for NURTURE leads

CALL GATE:
  No voice call is ever initiated until:
    a) A lead is classified INTERESTED
    b) The call-permission email is sent
    c) The lead replies granting permission (second INTERESTED classification)
  Only then is call_permission_granted set to True and passed to MeetingBookingTeam.
"""
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent

from model_config import get_llm_model
CLAUDE_MODEL = get_llm_model()

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
CALL_PERMISSION_TEMPLATE = (_PROMPTS_DIR / "call_permission_email.md").read_text()

# ---------------------------------------------------------------------------
# Agent 1: ResponseClassifierAgent
# ---------------------------------------------------------------------------
response_classifier_agent = LlmAgent(
    name="ResponseClassifierAgent",
    model=CLAUDE_MODEL,
    tools=[],
    output_key="reply_classification",
    instruction="""
You are an inbound reply classifier for Backflip Media's outreach campaign.

Classify the inbound reply in {inbound_reply} into EXACTLY ONE of:

  INTERESTED   — clear positive signal; prospect wants to meet, learn more, or chat
                 Trigger phrases: "sure", "sounds good", "happy to chat", "let's connect",
                 "tell me more", "let's find a time", "open to it", "yes", "that works"

  NURTURE      — not now but not a hard no; timing or bandwidth issue
                 Trigger phrases: "try me in Q3", "we're mid-campaign", "check back after",
                 "not right now", "maybe later", "after our event", "reach out in"

  NOT_FIT      — clear no, wrong org, or irrelevant reply
                 Trigger phrases: "not interested", "we don't do events", "wrong person",
                 "remove me", "stop emailing", "we have this covered"

  UNSUBSCRIBE  — explicit opt-out request; must be honored immediately
                 Trigger phrases: "unsubscribe", "take me off", "stop all emails",
                 "do not contact", "remove from list"

IMPORTANT — use chain-of-thought:
  Step 1: Quote the exact phrase(s) that drive the classification
  Step 2: Explain your reasoning (1 sentence)
  Step 3: State the classification

Return ONLY valid JSON:
{{
  "classification": "INTERESTED|NURTURE|NOT_FIT|UNSUBSCRIBE",
  "reasoning": "They said 'sure, happy to chat' which is a clear positive signal.",
  "key_phrase": "sure, happy to chat",
  "lead_id": "{{lead_id}}"
}}

SELF-CHECK:
- [ ] Exactly one classification chosen
- [ ] key_phrase is a direct quote from the reply
- [ ] Output is valid JSON only
""",
)

# ---------------------------------------------------------------------------
# Agent 2: CallPermissionAgent
# ---------------------------------------------------------------------------
call_permission_agent = LlmAgent(
    name="CallPermissionAgent",
    model=CLAUDE_MODEL,
    tools=[],
    output_key="call_permission_email",
    instruction=f"""
You are a follow-up email writer for Backflip Media.

CALL GATE RULE: Only trigger when {{reply_classification}}.classification == "INTERESTED".
If classification is anything other than INTERESTED, return:
{{{{ "skipped": true, "reason": "Classification was not INTERESTED", "lead_id": "..." }}}}

TEMPLATE GUIDANCE:
{CALL_PERMISSION_TEMPLATE}

YOUR TASK (when INTERESTED):
Draft a warm, 2-3 sentence reply asking for permission to call.

The email MUST:
1. Acknowledge their positive reply warmly (1 sentence — genuine, not sycophantic)
2. Ask: "Would it be okay if I gave you a quick call to find a time that works
   between yourself and our CEO, Declan?"
3. End with: "Happy to work around your schedule."

The email must NOT:
- Re-pitch or mention pricing
- Include links or attachments
- Be longer than 3 sentences

Return ONLY valid JSON:
{{
  "email_draft": "Full email body text",
  "subject": "Re: [original subject]",
  "awaiting_call_permission": true,
  "lead_id": "...",
  "skipped": false
}}

SELF-CHECK:
- [ ] Email is 2-3 sentences exactly
- [ ] Contains the exact call-permission question about Declan
- [ ] Does not re-pitch
- [ ] Output is valid JSON only
""",
)

# ---------------------------------------------------------------------------
# Agent 3: NurtureAgent
# ---------------------------------------------------------------------------
nurture_agent = LlmAgent(
    name="NurtureAgent",
    model=CLAUDE_MODEL,
    tools=[],
    output_key="nurture_schedule",
    instruction="""
You are a nurture scheduler for Backflip Media.

ONLY trigger when {reply_classification}.classification == "NURTURE".
If classification is not NURTURE, return:
{{ "skipped": true, "reason": "Classification was not NURTURE", "lead_id": "..." }}

YOUR TASK (when NURTURE):
Parse the reply text in {inbound_reply} for timing cues.

TIMING LOGIC:
  - If a specific time is mentioned ("after our May conference", "Q3", "July"):
    → Set recontact_date to 1 week AFTER that implied date
  - If no specific timing:
    → Set recontact_date to 30 days from today (use ISO format YYYY-MM-DD)
  - Add a recontact_note reminding what context to reference when re-contacting

Return ONLY valid JSON:
{{
  "lead_id": "...",
  "recontact_date": "YYYY-MM-DD",
  "recontact_note": "They said they're mid-campaign until May. Re-contact after their spring conference.",
  "skipped": false
}}

SELF-CHECK:
- [ ] recontact_date is a valid YYYY-MM-DD date
- [ ] recontact_note references the specific reason for the delay
- [ ] Output is valid JSON only
""",
)

# ---------------------------------------------------------------------------
# Team: ResponseHandlingTeam (SequentialAgent)
# ---------------------------------------------------------------------------
response_handling_team = SequentialAgent(
    name="ResponseHandlingTeam",
    sub_agents=[
        response_classifier_agent,
        call_permission_agent,
        nurture_agent,
    ],
    description=(
        "Classifies every inbound reply as INTERESTED, NURTURE, NOT_FIT, or "
        "UNSUBSCRIBE. On INTERESTED: drafts a call-permission email asking if "
        "the prospect is okay with a call from Declan. On NURTURE: schedules "
        "a timing-aware re-contact. CALL GATE: no call happens without "
        "explicit written permission from the lead."
    ),
)
