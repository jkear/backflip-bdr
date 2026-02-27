"""Outreach Strategy Team — Stage 2 of the Backflip Media pipeline.

Agents:
  1. ICPProfilerAgent       — builds Backflip Media's ICP + messaging framework (runs once)
  2. CompanyResearchAgent   — deep-dives each lead for personalization hooks
  3. EmailCopywriterAgent   — writes personalized 3-touch email sequences
  4. SequenceBuilderAgent   — assembles sequences into structured campaign JSON
"""
import json
import os
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent

from tools.exa_tools import exa_search_companies, exa_find_contact

from model_config import get_llm_model
CLAUDE_MODEL = get_llm_model()

# Load prompt files at import time so agents have full context
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

def _read_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    return path.read_text() if path.exists() else ""

ICP_CONTEXT = _read_prompt("icp_profiler.md")
EMAIL_COPYWRITER_SYSTEM = _read_prompt("email_copywriter.md")

# ---------------------------------------------------------------------------
# Agent 1: ICPProfilerAgent
# ---------------------------------------------------------------------------
icp_profiler_agent = LlmAgent(
    name="ICPProfilerAgent",
    model=CLAUDE_MODEL,
    tools=[exa_search_companies],
    output_key="icp_profile",
    instruction=f"""
You are a go-to-market strategist for Backflip Media.

WHAT YOU ALREADY KNOW ABOUT BACKFLIP MEDIA:
{ICP_CONTEXT}

YOUR TASK:
Augment the above with fresh research. Use exa_search_companies to search for:
1. "B2B event organizer digital advertising pain points LinkedIn Meta Google ads"
2. "industry association conference marketing digital ad strategy ROI"
3. "tradeshow expo paid advertising registration ticket sales conversion"

From the search results, extract and add:
- The 3 most common digital ad pain points for event organizers
- The 3 most common pain points for associations
- Key metrics these orgs care about (ROAS, cost-per-registration, membership growth rate)
- Platforms they most commonly use or should be using

Then write a complete ICP summary as a JSON object:
{{
  "company": "Backflip Media",
  "value_proposition": "...",
  "segment_a_pain_points": ["...", "...", "..."],
  "segment_b_pain_points": ["...", "...", "..."],
  "key_metrics": ["...", "..."],
  "platforms": ["LinkedIn Ads", "Meta Ads", "Google Ads", "..."],
  "tone": "confident, collaborative, peer-to-peer",
  "proof_points": ["...", "..."],
  "summary": "2-sentence summary of Backflip's positioning"
}}

SELF-CHECK:
- [ ] Both segments have pain points
- [ ] Output is valid JSON only
""",
)

# ---------------------------------------------------------------------------
# Agent 2: CompanyResearchAgent
# ---------------------------------------------------------------------------
company_research_agent = LlmAgent(
    name="CompanyResearchAgent",
    model=CLAUDE_MODEL,
    tools=[exa_search_companies, exa_find_contact],
    output_key="researched_leads",
    instruction="""
You are a sales researcher. For each lead in {scored_leads}.qualified_leads,
find a specific, concrete personalization hook.

FOR EACH LEAD:
1. Use exa_search_companies to search: "[company name] conference event 2025 2026"
2. Use exa_search_companies to search: "[company name] digital marketing advertising"
3. Use exa_find_contact to research the primary contact's background

From results, find ONE of these (in priority order):
  a) An upcoming or recently announced event (name + date if available)
  b) A growth signal (new hires, expanded event, new chapter/region)
  c) A visible pain point (hiring for marketing roles, poor ad presence, manual processes)
  d) A recent achievement worth referencing ("congrats on 20 years")

Set personalization_hook to a 1-sentence observation. Examples:
  "Saw your 2026 Annual Summit registration just opened — congrats on expanding to a second city."
  "You're running three regional expos this year — that's a lot of ad campaigns to coordinate."
  "Noticed you're hiring a Marketing Manager — looks like you're scaling the events team."

Return the full qualified_leads list with personalization_hook added to each:
{{
  "researched_leads": [
    {{
      "name": "...",
      "website": "...",
      "description": "...",
      "event_type": "...",
      "estimated_event_size": "...",
      "why_fit": "...",
      "contacts": [...],
      "score": 75,
      "score_dimensions": {{...}},
      "personalization_hook": "Specific observation about their events or situation."
    }}
  ]
}}

SELF-CHECK:
- [ ] Every lead has a personalization_hook (not null, not generic)
- [ ] Hooks reference the company by name or a specific event
- [ ] Output is valid JSON only
""",
)

# ---------------------------------------------------------------------------
# Agent 3: EmailCopywriterAgent
# ---------------------------------------------------------------------------
email_copywriter_agent = LlmAgent(
    name="EmailCopywriterAgent",
    model=CLAUDE_MODEL,
    tools=[],
    output_key="email_sequences",
    instruction=f"""
{EMAIL_COPYWRITER_SYSTEM}

---

ICP CONTEXT:
{{icp_profile}}

LEADS TO WRITE FOR:
{{researched_leads}}

(The researched_leads JSON above contains a "researched_leads" array. Iterate over each item in that array.)

YOUR TASK:
Write a 3-touch email sequence for each lead. Each sequence targets the PRIMARY
contact (first in the contacts list). Outreach is FROM Backflip Media; goal is
a discovery call with Declan (CEO).

TOUCH SPECIFICATIONS:
  Touch 1 (Day 1) — Cold intro:
    - Open with the lead's personalization_hook (1 sentence)
    - 1 sentence value prop tailored to their segment:
        Segment A (event organizer): "fill rooms / drive registrations with targeted digital ads"
        Segment B (association): "grow membership and drive event registrations from one strategy"
    - CTA: "Would it be worth 15 minutes to see if we can help?"
    - Subject: <7 words, specific to their world (no clickbait)
    - Max 100 words body

  Touch 2 (Day 5) — Value add:
    - Lead with a fresh insight about digital ads for their segment (not repeating Touch 1)
    - Restate offer from a different angle
    - Same CTA, different wording
    - Max 80 words body

  Touch 3 (Day 10) — Warm breakup:
    - Short, warm, no hard sell
    - Reference their specific upcoming event or situation
    - "Last note from me — if the timing ever makes sense, we'd love to help [Company]
       make [upcoming event / their next event] their biggest yet."
    - Max 60 words body

Return ONLY valid JSON:
{{
  "sequences": [
    {{
      "lead_id": "lead-001",
      "lead_name": "Company Name",
      "contacts": ["jane@example.com"],
      "emails": [
        {{
          "touch_number": 1,
          "send_day": 1,
          "subject": "Short subject here",
          "body": "Email body text..."
        }},
        {{
          "touch_number": 2,
          "send_day": 5,
          "subject": "...",
          "body": "..."
        }},
        {{
          "touch_number": 3,
          "send_day": 10,
          "subject": "...",
          "body": "..."
        }}
      ]
    }}
  ]
}}

SELF-CHECK:
- [ ] Touch 1 for every lead opens with THEIR personalization_hook
- [ ] Every lead has exactly 3 touches
- [ ] No two leads share the same Touch 1 opening sentence
- [ ] All subject lines are under 7 words
- [ ] Word counts are within limits (100/80/60)
- [ ] Output is valid JSON only
""",
)

# ---------------------------------------------------------------------------
# Agent 4: SequenceBuilderAgent
# ---------------------------------------------------------------------------
sequence_builder_agent = LlmAgent(
    name="SequenceBuilderAgent",
    model=CLAUDE_MODEL,
    tools=[],
    output_key="campaign_json",
    instruction="""
You are a campaign assembler. Take {email_sequences} and build the final campaign JSON.

YOUR TASK:
1. Validate the sequences:
   - Every lead has exactly 3 email touches
   - Every touch has: touch_number, send_day, subject, body
   - No empty subject or body fields
   - Report any validation errors in a "validation_errors" list

2. Enrich each sequence with:
   - send_schedule: {{"touch_1": 1, "touch_2": 5, "touch_3": 10}}
   - unsubscribe_footer: "To unsubscribe from these emails, reply with 'unsubscribe'."

3. Assemble final campaign object.

Return ONLY valid JSON:
{{
  "campaign_path": "output/campaign.json",
  "lead_count": N,
  "validation_errors": [],
  "sequences": [
    {{
      "lead_id": "...",
      "lead_name": "...",
      "contacts": ["..."],
      "send_schedule": {{"touch_1": 1, "touch_2": 5, "touch_3": 10}},
      "unsubscribe_footer": "To unsubscribe from these emails, reply with 'unsubscribe'.",
      "emails": [...]
    }}
  ]
}}

SELF-CHECK:
- [ ] lead_count matches the number of sequences
- [ ] validation_errors is empty (fix any issues found before responding)
- [ ] Every sequence has send_schedule and unsubscribe_footer
- [ ] Output is valid JSON only
""",
)

# ---------------------------------------------------------------------------
# Team: OutreachStrategyTeam (SequentialAgent)
# ---------------------------------------------------------------------------
outreach_strategy_team = SequentialAgent(
    name="OutreachStrategyTeam",
    sub_agents=[
        icp_profiler_agent,
        company_research_agent,
        email_copywriter_agent,
        sequence_builder_agent,
    ],
    description=(
        "Builds Backflip Media's ICP, researches each qualified lead for "
        "personalization hooks, writes 3-touch email sequences, and assembles "
        "a structured campaign JSON ready for sending."
    ),
)
