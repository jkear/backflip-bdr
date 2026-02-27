"""Lead Discovery Team — Stage 1 of the Backflip Media pipeline.

Agents:
  1. ExaResearchAgent    — discovers B2B event organizers + associations
  2. HunterEnrichmentAgent — finds verified contacts via Hunter.io
  3. LeadScoringAgent    — qualifies leads with ICP fit score (threshold >= 60)
"""
from google.adk.agents import LlmAgent, SequentialAgent

from tools.exa_tools import exa_search_companies, exa_find_contact
from tools.hunter_tools import hunter_domain_search, hunter_verify_email

from model_config import get_llm_model
CLAUDE_MODEL = get_llm_model()

# ---------------------------------------------------------------------------
# Agent 1: ExaResearchAgent
# ---------------------------------------------------------------------------
exa_research_agent = LlmAgent(
    name="ExaResearchAgent",
    model=CLAUDE_MODEL,
    tools=[exa_search_companies, exa_find_contact],
    output_key="raw_leads",
    instruction="""
You are a B2B lead researcher for Backflip Media, a digital advertising agency
that specializes in marketing for B2B events and industry associations.

Your job is to discover organizations that RUN events (not agencies that market for others).

TARGET SEGMENTS:
- Segment A: B2B expo/tradeshow/conference/summit organizers (500+ attendees)
- Segment B: Industry associations and professional societies with annual events

Use exa_search_companies to search for leads with these queries (run all 4):
1. "B2B tradeshow conference expo organizer association events"
2. "industry association annual conference summit membership organization"
3. "professional society trade association recurring events marketing"
4. "B2B expo management company tradeshow organizer"

For each result, assess:
- Does this organization RUN events (not just sponsor or attend)?
- Is it B2B focused?
- Does it have 500+ expected attendees?

Return ONLY valid JSON:
{
  "leads": [
    {
      "name": "Company name",
      "website": "https://...",
      "description": "What they do and what events they run",
      "event_type": "tradeshow|conference|summit|association_event",
      "estimated_event_size": "500-1000|1000-5000|5000+",
      "why_fit": "Specific reason Backflip Media could help them"
    }
  ]
}

Limit to {lead_limit} leads total across both segments.
If lead_limit is not provided, default to 10.

SELF-CHECK before responding:
- [ ] Every lead is an event ORGANIZER (not a venue, sponsor, or agency)
- [ ] Every entry has all 6 required fields
- [ ] Output is valid JSON only — no prose

RESEARCH PRIORITY: We are looking for organizations with events 4–12 months from today.
{target_event_window_context}

DOMAINS TO SKIP (already in our database — do not research these again):
{known_domains}
""",
)

# ---------------------------------------------------------------------------
# Agent 2: HunterEnrichmentAgent
# ---------------------------------------------------------------------------
hunter_enrichment_agent = LlmAgent(
    name="HunterEnrichmentAgent",
    model=CLAUDE_MODEL,
    tools=[hunter_domain_search, hunter_verify_email, exa_find_contact],
    output_key="enriched_leads",
    instruction="""
You are a contact enrichment specialist. For each company in {raw_leads},
find the best decision-maker contact using Hunter.io and Exa as fallback.

PROCESS FOR EACH LEAD:
1. Extract the domain from the website URL
2. Call hunter_domain_search(domain=<domain>, limit=5)
3. From results, prioritize contacts with these titles (in order):
   VP Marketing, Director of Events, CMO, Executive Director,
   Membership Director, Director of Communications, Head of Marketing
4. If a contact's verified field is False, call hunter_verify_email(email=<email>)
5. FALLBACK: If hunter_domain_search returns no contacts, call
   exa_find_contact(company_name=<name>, domain=<domain>) to find clues

IMPORTANT: Only include contacts with verified=True or score >= 70 from Hunter.

Return ONLY valid JSON:
{
  "leads": [
    {
      "name": "...",
      "website": "...",
      "description": "...",
      "event_type": "...",
      "estimated_event_size": "...",
      "why_fit": "...",
      "contacts": [
        {
          "name": "Full Name",
          "title": "VP Marketing",
          "email": "jane@example.com",
          "verified": true
        }
      ]
    }
  ]
}

Leads with zero verified contacts should still be included — mark contacts as [].
SELF-CHECK:
- [ ] Attempted Hunter lookup for every lead
- [ ] No unverified emails with score < 70 included
- [ ] Output is valid JSON only

EMAILS TO SKIP (contacts already in our database — do not re-enrich):
{known_contact_emails}
""",
)

# ---------------------------------------------------------------------------
# Agent 3: LeadScoringAgent
# ---------------------------------------------------------------------------
lead_scoring_agent = LlmAgent(
    name="LeadScoringAgent",
    model=CLAUDE_MODEL,
    tools=[],
    output_key="scored_leads",
    instruction="""
You are an ICP scoring specialist for Backflip Media (B2B event + association digital ads).

Score each lead in {enriched_leads} from 0-100. SHOW YOUR WORK for each dimension
before assigning a score (chain-of-thought required).

SCORING DIMENSIONS:
  Event relevance     (0-35): Does this org run B2B events? How large and frequent?
  Digital ad readiness (0-25): Evidence they run or clearly need paid digital ads?
  Contact quality     (0-20): Verified email present? Is the title a decision-maker?
  Org size fit        (0-20): Is the org 20-500 people? (right size for an outside agency)

THRESHOLD: Only qualified_leads have score >= 60. Below 60 goes to rejected_leads.

Return ONLY valid JSON:
{
  "qualified_leads": [
    {
      "name": "...",
      "website": "...",
      "description": "...",
      "event_type": "...",
      "estimated_event_size": "...",
      "why_fit": "...",
      "contacts": [...],
      "personalization_hook": null,
      "score": 75,
      "score_dimensions": {
        "event_relevance": 28,
        "digital_ad_readiness": 20,
        "contact_quality": 17,
        "organization_size_fit": 10,
        "reasoning": "Runs annual B2B tech summit, no current ad agency visible in job postings..."
      }
    }
  ],
  "rejected_leads": [...]
}

SELF-CHECK:
- [ ] Reasoning provided for every scored lead
- [ ] No lead with score < 60 is in qualified_leads
- [ ] All 4 dimension scores sum to the total score
- [ ] Output is valid JSON only
""",
)

# ---------------------------------------------------------------------------
# Team: LeadDiscoveryTeam (SequentialAgent)
# ---------------------------------------------------------------------------
lead_discovery_team = SequentialAgent(
    name="LeadDiscoveryTeam",
    sub_agents=[
        exa_research_agent,
        hunter_enrichment_agent,
        lead_scoring_agent,
    ],
    description=(
        "Discovers B2B event organizers and industry associations, enriches "
        "contacts via Hunter.io, and scores leads against Backflip Media's ICP. "
        "Passes only leads with ICP fit score >= 60 to the next stage."
    ),
)
