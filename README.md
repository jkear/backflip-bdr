# Backflip Media — Lead-to-Meeting Pipeline

An autonomous multi-agent pipeline that discovers B2B event organizers and industry associations, researches and qualifies them, reaches out via personalized email sequences, and — only after explicit written permission — places a live AI voice call to book a discovery meeting with Declan (CEO, Backflip Media).

Built with **Google ADK**, **SQLAlchemy 2.0 (async)**, **PostgreSQL 16**, **Langfuse** (LLM tracing), and **Claude Sonnet** (via Anthropic API or Vertex AI).

---

## How It Works

```
STAGE 1 — Lead Discovery
  Exa semantic search → Hunter.io contact enrichment → ICP scoring (≥60 threshold)

STAGE 2 — Outreach Strategy
  ICP profiling → company research + personalization hooks → 3-touch email sequences

STAGE 3 — Response Handling (triggered per inbound reply)
  Reply classification → call-permission email (INTERESTED only) → nurture scheduling

STAGE 4 — Meeting Booking (triggered after written permission granted)
  ElevenLabs live call → Google Calendar slot proposal → confirmed invite
```

### Call Gate

**No cold calls. Ever.**

Voice calls only happen when:
1. A prospect replies positively to an email
2. The pipeline drafts: *"Would it be okay if I gave you a quick call to find a time that works between yourself and our CEO, Declan?"*
3. That email is sent manually and the prospect replies granting permission
4. `--permission` flag is passed to `agent.py book`

Only then does `ConversationalVoiceAgent` initiate an ElevenLabs call.

> **Note:** Email sequences are generated and saved to `output/campaign.json`. They are **not sent automatically** — sending requires integration with an email provider (SendGrid, Mailgun, etc.) that is not yet implemented.

---

## Target Audience

**Segment A — B2B Event Organizers**
Expos, tradeshows, conferences, summits (500+ attendees). Pain: filling rooms, driving registrations with targeted digital ads.

**Segment B — Industry Associations**
Trade associations, professional societies with annual events. Pain: growing membership and driving event registrations from one ad strategy.

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for package management
- [Docker](https://www.docker.com/) or [OrbStack](https://orbstack.dev/) (for PostgreSQL)
- **LLM provider (choose one):**
  - **Option A (recommended):** Anthropic API key — simpler, no GCP required
  - **Option B:** Google Cloud project with Vertex AI enabled + service account
- **API keys:** Exa, Hunter.io, ElevenLabs
- **Google Calendar:** Service account with Declan's calendar shared to it
- **ElevenLabs + Twilio:** Outbound calls require a Twilio account linked to ElevenLabs (not just an ElevenLabs API key)

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo>
cd Backflip_SDR-Agent_Teams
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in all values in .env
```

Key environment variables:

| Variable | Where to get it | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | If using Anthropic (recommended) |
| `GOOGLE_CLOUD_PROJECT` | GCP Console | If using Vertex AI |
| `GOOGLE_APPLICATION_CREDENTIALS` | GCP → IAM → Service Accounts → Create Key | If using Vertex AI or Google Calendar |
| `EXA_API_KEY` | [exa.ai](https://exa.ai) | Yes |
| `HUNTER_API_KEY` | [hunter.io](https://hunter.io) | Yes |
| `ELEVENLABS_API_KEY` | [elevenlabs.io](https://elevenlabs.io) | Yes (Stage 4) |
| `ELEVENLABS_VOICE_ID` | ElevenLabs voice library | Yes (Stage 4) |
| `DECLAN_CALENDAR_ID` | Google Calendar settings → Calendar ID | Yes (Stage 4) |
| `DB_PASSWORD` | Choose any password | Yes |
| `DATABASE_URL` | See `.env.example` | Yes |
| `LANGFUSE_PUBLIC_KEY` | [cloud.langfuse.com](https://cloud.langfuse.com) | Optional |

**LLM provider:** Set `ANTHROPIC_API_KEY` to use Anthropic directly. Leave it blank to fall back to Vertex AI (requires `GOOGLE_CLOUD_PROJECT` and `GOOGLE_APPLICATION_CREDENTIALS`).

### 3. Start the database

```bash
docker compose up -d
```

This starts PostgreSQL 16 on port 5432 and pgAdmin on port 5050.

> If port 5432 is already in use by a local PostgreSQL installation, change the host port in `docker-compose.yml` to `"5433:5432"` and update `DATABASE_URL` accordingly.

### 4. Run database migrations

```bash
uv run alembic upgrade head
```

This creates all tables across the three schemas: `crm`, `obs`, and `improve`.

### 5. (Vertex AI only) Enable Google Calendar API

```bash
gcloud services enable calendar-json.googleapis.com --project=$GOOGLE_CLOUD_PROJECT
```

Share Declan's Google Calendar with the service account email (the one in your `GOOGLE_APPLICATION_CREDENTIALS` JSON) so it can read/write events.

---

## Usage

All commands use `uv run` to ensure the correct virtual environment.

### Discover leads and build campaign

```bash
uv run python agent.py discover --limit 10
```

Output: `output/campaign.json` — 3-touch email sequences for every qualified lead (ICP score ≥ 60).

The sequences must be sent manually through your email provider — this pipeline does not send email automatically.

### Process an inbound reply

```bash
uv run python agent.py reply \
  --lead-id lead-001 \
  --reply "Sure, happy to connect — sounds interesting."
```

Output: `output/reply_lead-001.json` — classification + call-permission email draft (if INTERESTED).

The call-permission email must also be sent manually.

### Book a meeting (after written permission received)

```bash
uv run python agent.py book \
  --lead-id lead-001 \
  --contact-name "Jane Smith" \
  --contact-email "jane@techconf.com" \
  --company "TechConf Inc" \
  --phone "+15551234567" \
  --permission
```

- With `--permission`: ElevenLabs call is initiated (requires Twilio integration). On no-answer, falls back to proposing 3 calendar slots via email draft.
- Without `--permission`: call is skipped entirely, email-based slot proposal activates.

Output: `output/booking_<lead-id>.json` — call outcome + calendar event details.

### Run tests

Integration tests require the database to be running with migrations applied.

```bash
uv run pytest
```

---

## Pipeline Outputs

| File | Contents |
|---|---|
| `output/campaign.json` | All email sequences with send schedule (send manually) |
| `output/reply_<lead-id>.json` | Reply classification + next action draft |
| `output/booking_<lead-id>.json` | Call outcome + calendar event details |

---

## Architecture

```
Backflip_SDR-Agent_Teams/
├── agent.py                  # Orchestrator + CLI (discover / reply / book)
├── model_config.py           # Provider selection: Anthropic API or Vertex AI
├── vertex_ai_init.py         # Vertex AI + Langfuse/LiteLLM callback wiring
├── teams/
│   ├── lead_discovery.py     # Stage 1: Exa → Hunter → ICP scoring
│   ├── outreach_strategy.py  # Stage 2: Research → emails → campaign JSON
│   ├── response_handling.py  # Stage 3: Classify → permission → nurture
│   └── meeting_booking.py    # Stage 4: Voice call → calendar → confirm
├── tools/
│   ├── exa_tools.py          # Exa semantic search (company + contact)
│   ├── hunter_tools.py       # Hunter.io REST API (domain search, verify)
│   ├── elevenlabs_tools.py   # ElevenLabs Conversational AI (create, call, status)
│   └── calendar_tools.py     # Google Calendar (free/busy, create event, verify)
├── db/
│   ├── connection.py         # Async SQLAlchemy engine + get_db() context manager
│   ├── models.py             # 14 ORM models across crm / obs / improve schemas
│   ├── init.sql              # Schema creation (run by Docker on first start)
│   ├── migrations/           # Alembic migrations
│   │   └── versions/
│   │       ├── 001_initial_schema.py
│   │       └── 002_event_unique_constraint.py
│   └── repositories/         # Data access layer
│       ├── organizations.py
│       ├── contacts.py
│       ├── events.py
│       ├── sequences.py
│       ├── pipeline.py       # record_reply, record_call, record_meeting, add_suppression
│       ├── observability.py  # log_agent_run, log_api_cost (populated via Langfuse)
│       └── improvement.py    # record_outcome, add_suggestion
├── schemas/                  # Pydantic models (reference types, not yet wired to agents)
├── prompts/                  # System prompts loaded at import time
│   ├── icp_profiler.md
│   ├── email_copywriter.md
│   ├── call_permission_email.md
│   └── objection_handling.md
├── tests/
│   └── test_repositories.py  # Integration tests (require live DB)
└── output/                   # Generated campaigns and results (git-ignored)
```

**Model:** `claude-sonnet-4-6` (Anthropic API) or `claude-sonnet-4-5@20250929` (Vertex AI), selected automatically based on `ANTHROPIC_API_KEY`.

---

## Database Schemas

| Schema | Tables | Purpose |
|---|---|---|
| `crm` | organizations, contacts, events, suppression_list, email_sequences, email_touches, inbound_replies, call_records, meetings | Core sales pipeline data |
| `obs` | agent_run_log, api_cost_log | Execution + cost observability |
| `improve` | prompt_versions, improvement_suggestions, outcome_feedback | Prompt versioning + feedback loop |

pgAdmin web UI: [http://localhost:5050](http://localhost:5050) (credentials in `.env`)

---

## Sequence Cadence

```
Day 1   Email Touch 1  — cold intro with personalization hook
Day 5   Email Touch 2  — value-add insight
Day 10  Email Touch 3  — warm breakup, leave door open

On positive reply:
  → Classification: INTERESTED
  → Permission email drafted: "Would it be okay if I gave you a quick call...Declan?"
  → [Manual send] → Lead replies granting permission
  → agent.py book --permission → ElevenLabs live call → book meeting
  → On no answer → email 3 calendar slots as fallback (draft generated)
  → On confirmed slot → Google Calendar event + Meet link + confirmation email draft

On nurture reply:
  → Timing-aware re-contact date scheduled (30-day default or parsed from reply)

On UNSUBSCRIBE reply:
  → Email added to suppression_list — skipped in all future discovery runs
```
