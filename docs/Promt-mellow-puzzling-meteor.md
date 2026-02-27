# Plan: Persistent Lead Storage + Observability + Self-Improvement DB

## Context
The Backflip SDR pipeline currently uses `InMemorySessionService` — all lead data, outreach history, and outcomes die when the process exits. This plan adds three PostgreSQL schemas (crm / obs / improve), a repository layer, Docker Compose for local Postgres, and Langfuse Cloud for LLM tracing. Research agents are updated to skip known orgs/contacts and target only orgs with events 4–12 months out.

---

## Infrastructure

### New Files
- `docker-compose.yml` — PostgreSQL 16 + pgAdmin (port 5050)
- `db/init.sql` — Creates three schemas: `crm`, `obs`, `improve`

### Connection
- `db/connection.py` — SQLAlchemy 2.0 async engine, `AsyncSession` factory, `get_db()` context manager
- URL: `postgresql+asyncpg://backflip:${DB_PASSWORD}@localhost:5432/backflip_sdr`

### Migrations
- `alembic.ini` — points to `db/migrations/`
- `db/migrations/env.py` — standard Alembic async setup using SQLAlchemy models
- `db/migrations/versions/001_initial_schema.py` — creates all tables

---

## Database Schema (3 PostgreSQL Schemas)

### Schema 1: `crm` — Lead Pipeline

**`crm.organizations`** (dedup key: `domain`)
```
id UUID PK | name TEXT | domain TEXT UNIQUE | website TEXT | description TEXT
org_type TEXT | employee_count_range TEXT | icp_score INT | icp_score_dimensions JSONB
pipeline_stage TEXT | why_fit TEXT | last_outreach_date TIMESTAMPTZ | next_outreach_date TIMESTAMPTZ
notes TEXT | disqualified BOOL DEFAULT FALSE | disqualified_reason TEXT
created_at TIMESTAMPTZ | updated_at TIMESTAMPTZ
```

Pipeline stages (enforced by CHECK constraint):
`discovered → enriched → scored → qualified → rejected → in_sequence → touch_1_sent → touch_2_sent → touch_3_sent → replied_interested → call_permission_sent → call_permission_granted → call_attempted → booked → meeting_held → became_client → nurture → closed_lost → unsubscribed`

**`crm.events`** (FK → organizations, separate table to avoid sparse columns)
```
id UUID PK | org_id UUID FK | event_name TEXT | event_type TEXT
event_date DATE (nullable) | event_date_approximate BOOL | event_date_notes TEXT
estimated_attendees TEXT | registration_url TEXT
is_recurring BOOL | recurrence_period TEXT ('annual'|'quarterly'|'biannual')
outreach_window_open DATE GENERATED (event_date - 12 months)
outreach_window_close DATE GENERATED (event_date - 4 months)
discovered_at TIMESTAMPTZ | created_at TIMESTAMPTZ
```

**`crm.contacts`** (dedup key: `email`)
```
id UUID PK | org_id UUID FK | name TEXT | first_name TEXT | last_name TEXT
title TEXT | email TEXT UNIQUE | email_verified BOOL | hunter_score INT
phone TEXT (E.164) | linkedin_url TEXT | is_primary BOOL
last_verified_at TIMESTAMPTZ | created_at TIMESTAMPTZ | notes TEXT
```

**`crm.suppression_list`** (permanent — never override, legal compliance)
```
id UUID PK | email TEXT UNIQUE | domain TEXT
reason TEXT | source TEXT ('unsubscribe_reply'|'manual'|'bounce')
suppressed_at TIMESTAMPTZ
```

**`crm.email_sequences`**
```
id UUID PK | org_id UUID FK | contact_id UUID FK
icp_profile_snapshot JSONB | personalization_hook TEXT
status TEXT ('pending'|'active'|'completed'|'paused'|'cancelled')
created_at TIMESTAMPTZ | completed_at TIMESTAMPTZ
```

**`crm.email_touches`**
```
id UUID PK | sequence_id UUID FK | org_id UUID FK | contact_id UUID FK
touch_number INT (1-3) | scheduled_date TIMESTAMPTZ | sent_at TIMESTAMPTZ
subject TEXT | body TEXT | status TEXT | message_id TEXT
created_at TIMESTAMPTZ
```

**`crm.inbound_replies`**
```
id UUID PK | org_id UUID FK | contact_id UUID FK | touch_id UUID FK (nullable)
reply_text TEXT | received_at TIMESTAMPTZ
classification TEXT | classification_reasoning TEXT | key_phrase TEXT | classified_at TIMESTAMPTZ
recontact_date DATE | recontact_note TEXT
actioned BOOL DEFAULT FALSE | created_at TIMESTAMPTZ
```

**`crm.call_records`**
```
id UUID PK | org_id UUID FK | contact_id UUID FK
call_permission_granted BOOL | call_permission_granted_at TIMESTAMPTZ
elevenlabs_call_id TEXT | elevenlabs_agent_id TEXT
call_status TEXT | transcript TEXT | call_successful BOOL
initiated_at TIMESTAMPTZ | completed_at TIMESTAMPTZ | agreed_slot JSONB | notes TEXT
```

**`crm.meetings`**
```
id UUID PK | org_id UUID FK | contact_id UUID FK | call_record_id UUID FK (nullable)
google_event_id TEXT | html_link TEXT | meet_link TEXT
scheduled_start TIMESTAMPTZ | scheduled_end TIMESTAMPTZ | timezone TEXT
status TEXT ('confirmed'|'cancelled'|'completed'|'no_show')
outcome_notes TEXT | confirmation_email_draft TEXT | event_verified BOOL
created_at TIMESTAMPTZ
```

---

### Schema 2: `obs` — Observability (what Langfuse doesn't capture)

**`obs.agent_run_log`** (Langfuse captures LLM calls; this captures agent-level summaries)
```
id UUID PK | session_id TEXT | agent_name TEXT | team_name TEXT | stage_number INT
org_id UUID (nullable) | langfuse_trace_id TEXT
started_at TIMESTAMPTZ | completed_at TIMESTAMPTZ | duration_ms INT
success BOOL | error_message TEXT | model_used TEXT
input_token_count INT | output_token_count INT | estimated_llm_cost_usd DECIMAL(10,6)
```

**`obs.api_cost_log`** (non-LLM API costs: Exa, Hunter, ElevenLabs, Google Calendar)
```
id UUID PK | service TEXT | operation TEXT | org_id UUID (nullable)
agent_run_id UUID FK (nullable) | estimated_cost_usd DECIMAL(10,6)
units_used INT | called_at TIMESTAMPTZ | success BOOL
```

---

### Schema 3: `improve` — Self-Improvement Engine

**`improve.prompt_versions`** (local tracking; Langfuse Cloud prompt management is a future migration)
```
id UUID PK | prompt_name TEXT | version TEXT | content TEXT
change_summary TEXT | is_active BOOL DEFAULT TRUE
deployed_at TIMESTAMPTZ | deprecated_at TIMESTAMPTZ
```

**`improve.improvement_suggestions`** (agent-proposed; human-approved)
```
id UUID PK | source TEXT | category TEXT | description TEXT
proposed_change JSONB | supporting_evidence TEXT
status TEXT DEFAULT 'pending_review' ('pending_review'|'approved'|'rejected'|'implemented')
reviewed_at TIMESTAMPTZ | implementation_notes TEXT | created_at TIMESTAMPTZ
```

**`improve.outcome_feedback`** (outcome tracking; feeds future analysis agents)
```
id UUID PK | org_id UUID FK (nullable) | sequence_id UUID FK (nullable)
call_record_id UUID FK (nullable) | meeting_id UUID FK (nullable)
conversion_event TEXT | icp_score_at_time INT | prompt_versions_snapshot JSONB
personalization_hook_used TEXT | email_touch_number INT
days_since_first_touch INT | notes TEXT | recorded_at TIMESTAMPTZ
```

---

## Repository Layer (Data Access)

**`db/models.py`** — SQLAlchemy ORM models for all tables above

**`db/repositories/organizations.py`**
- `get_by_domain(domain)` → Org | None  ← dedup check
- `get_known_domains()` → Set[str]  ← passed to research agents to skip
- `upsert(data)` → Org
- `update_stage(org_id, stage)` → Org
- `get_in_event_window(months_min=4, months_max=12)` → List[Org + Events]
- `get_due_for_outreach()` → List[Org]  (next_outreach_date <= today)

**`db/repositories/contacts.py`**
- `get_by_email(email)` → Contact | None  ← dedup check
- `get_known_emails()` → Set[str]  ← passed to research agents to skip
- `upsert(data)` → Contact
- `is_suppressed(email)` → bool  ← checks suppression_list before any send

**`db/repositories/events.py`**
- `upsert(org_id, event_data)` → Event
- `get_upcoming_events(months_min=4, months_max=12)` → List[Event]
- `get_by_org(org_id)` → List[Event]

**`db/repositories/sequences.py`**
- `create_sequence(org_id, contact_id, emails, hook, icp_snapshot)` → Sequence
- `get_pending_touches()` → List[Touch]  (scheduled_date <= today, status='scheduled')
- `mark_touch_sent(touch_id, message_id, sent_at)` → Touch
- `cancel_remaining_touches(sequence_id)` → int  ← called when UNSUBSCRIBE received

**`db/repositories/pipeline.py`**
- `record_reply(org_id, contact_id, touch_id, reply_text, classification, ...)` → Reply
- `record_call(org_id, contact_id, ...)` → CallRecord
- `record_meeting(org_id, contact_id, ...)` → Meeting
- `add_suppression(email, domain, reason, source)` → Suppression  ← permanent
- `get_org_history(org_id)` → dict  ← full context for agents

**`db/repositories/observability.py`**
- `log_agent_run(...)` → AgentRunLog
- `log_api_cost(service, operation, ...)` → ApiCostLog

**`db/repositories/improvement.py`**
- `record_outcome(...)` → OutcomeFeedback
- `add_suggestion(category, description, ...)` → ImprovementSuggestion

---

## Langfuse Integration

**Changes to `vertex_ai_init.py`** — add 2 lines after `vertexai.init()`:
```python
import litellm
litellm.success_callback = ["langfuse"]
litellm.failure_callback = ["langfuse"]
```

**New env vars** (in `.env.example`):
```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

This automatically captures: every LLM call, model, tokens, cost, latency, input/output.

For non-LLM tracing (tool calls, agent runs), `obs.agent_run_log` and `obs.api_cost_log` serve as the local complement.

**Prompt versioning:** Langfuse Cloud has Prompt Management, but it requires migrating `.md` files to their API. For now, `improve.prompt_versions` tracks prompt versions locally. Future migration to Langfuse Prompt Management is possible by reading `.md` files and pushing via `langfuse.create_prompt()`.

---

## Changes to `agent.py`

**`run_discovery()`** — before calling teams, query DB:
```python
known_domains = await get_known_domains()
known_emails = await get_known_emails()
# Add to initial message for ExaResearchAgent and HunterEnrichmentAgent to skip
```

**After Stage 1** — persist all discovered/scored leads to `crm.organizations`, `crm.contacts`

**After Stage 2** — persist sequences and touches to `crm.email_sequences`, `crm.email_touches`

**`run_reply_handler()`** — write reply + classification to `crm.inbound_replies`; update org stage; on UNSUBSCRIBE → write to `crm.suppression_list`, cancel remaining touches

**`run_meeting_booking()`** — write call record to `crm.call_records`; on BOOKED → write to `crm.meetings`; update org stage to `booked`

---

## Changes to `teams/lead_discovery.py`

**ExaResearchAgent instruction** — add to bottom:
```
DOMAINS TO SKIP (already in our database — do not research these again):
{known_domains}
```

**HunterEnrichmentAgent instruction** — add:
```
EMAILS TO SKIP (contacts already in our database — do not re-enrich):
{known_contact_emails}
```

**Event window context** — add to ExaResearchAgent instruction:
```
RESEARCH PRIORITY: We are looking for organizations with events 4–12 months from today.
{target_event_window_context}
```

---

## Files to Create (13 new)
1. `docker-compose.yml`
2. `db/__init__.py`
3. `db/connection.py`
4. `db/models.py`
5. `db/init.sql`
6. `alembic.ini`
7. `db/migrations/env.py`
8. `db/migrations/versions/001_initial_schema.py`
9. `db/repositories/__init__.py`
10. `db/repositories/organizations.py`
11. `db/repositories/contacts.py`
12. `db/repositories/events.py`
13. `db/repositories/sequences.py`
14. `db/repositories/pipeline.py`
15. `db/repositories/observability.py`
16. `db/repositories/improvement.py`

## Files to Modify (4)
1. `agent.py` — DB calls before/after each stage
2. `teams/lead_discovery.py` — pass `known_domains`, `known_contact_emails`, event window context
3. `vertex_ai_init.py` — add LiteLLM → Langfuse callbacks
4. `requirements.txt` — add: `sqlalchemy[asyncio]>=2.0`, `alembic>=1.13`, `asyncpg>=0.29`, `langfuse>=2.0`
5. `.env.example` — add DB URL, DB credentials, Langfuse keys

---

## Execution Approach: Subagent-Driven Development

Use `/subagent-driven-development` skill. Tasks run **sequentially** (dependencies exist between batches). One fresh subagent per task. Two-stage review per task: spec compliance first → code quality second. Controller provides full task text + scene-setting context; subagents do not read the plan file.

**Context file for subagents:** `ANALYSIS.md` describes the full pipeline. Each subagent gets the relevant section verbatim.

---

## Task Breakdown (Ordered by Dependency)

### BATCH 1 — Infrastructure (no dependencies, can run independently)

#### Task 1: Docker + Config
**Creates:** `docker-compose.yml`, `db/init.sql`, updates `.env.example`, updates `requirements.txt`
**What:** PostgreSQL 16 + pgAdmin via Docker Compose, managed by **OrbStack** (not Docker Desktop — OrbStack provides the Docker daemon on this machine, `docker compose` CLI works identically). `db/init.sql` creates 3 schemas. Add 5 deps to requirements.txt. Add 5 env vars to .env.example.
**Done when:** `docker compose up -d` starts cleanly via OrbStack; `psql -U backflip backflip_sdr -c "\dn"` shows schemas crm, obs, improve.

#### Task 2: DB Connection Layer
**Creates:** `db/__init__.py`, `db/connection.py`
**Depends on:** Task 1 (Postgres running)
**What:** SQLAlchemy 2.0 async engine using `asyncpg`. `AsyncSession` factory. `get_db()` async context manager. Read `DATABASE_URL` from env.
**Done when:** `python -c "import asyncio; from db.connection import engine; print(engine.url)"` prints the DB URL without errors.

---

### BATCH 2 — Models + Migrations (depends on Task 2)

#### Task 3: SQLAlchemy ORM Models
**Creates:** `db/models.py`
**Depends on:** Task 2
**What:** All 14 tables across 3 schemas as SQLAlchemy mapped classes. Use `__table_args__ = {"schema": "crm"}` pattern. Include all fields, FKs, CHECK constraints for pipeline_stage enum. Generated columns for outreach_window_open/close on events table (as Python properties, not DB-generated, for portability).
**Done when:** `python -c "from db.models import Organization, Contact, Event, Meeting; print('OK')"` imports cleanly.

#### Task 4: Alembic Migrations
**Creates:** `alembic.ini`, `db/migrations/env.py`, `db/migrations/versions/001_initial_schema.py`
**Depends on:** Task 3
**What:** Standard Alembic async setup. Migration creates all tables in the correct schema order (crm first, then obs, then improve). FKs created after all tables.
**Done when:** `alembic upgrade head` runs without errors; all 14 tables visible in pgAdmin.

---

### BATCH 3 — Repository Layer (depends on Task 3 + Task 4)

#### Task 5: Org + Contact + Event Repositories
**Creates:** `db/repositories/__init__.py`, `db/repositories/organizations.py`, `db/repositories/contacts.py`, `db/repositories/events.py`
**Depends on:** Task 3, Task 4
**What:** All CRUD + dedup + query methods listed in the plan above. `get_known_domains()` and `get_known_emails()` must return fast (used before every discovery run). `get_in_event_window()` query must filter by event_date range.
**Done when:** Unit tests pass: insert org, verify dedup blocks duplicate domain, fetch in-window events, verify suppression check blocks suppressed email.

#### Task 6: Sequence + Pipeline + Observability + Improvement Repositories
**Creates:** `db/repositories/sequences.py`, `db/repositories/pipeline.py`, `db/repositories/observability.py`, `db/repositories/improvement.py`
**Depends on:** Task 5
**What:** All methods listed above. `cancel_remaining_touches()` must mark status='cancelled' for all unsent touches in a sequence. `add_suppression()` must be idempotent (upsert on email).
**Done when:** Insert a sequence with 3 touches, call `cancel_remaining_touches`, verify touches are cancelled. Insert a suppression, call again, no error.

---

### BATCH 4 — Pipeline Integration (depends on all repositories)

#### Task 7: Langfuse + LiteLLM Wiring
**Modifies:** `vertex_ai_init.py`, `.env.example`
**Depends on:** Task 2 (env loading pattern)
**What:** Add `litellm.success_callback = ["langfuse"]` and `litellm.failure_callback = ["langfuse"]` after `vertexai.init()`. Add guard: only enable if `LANGFUSE_PUBLIC_KEY` is set (so pipeline still works without Langfuse configured). Add LANGFUSE env vars to `.env.example`.
**Done when:** With Langfuse keys set, run a single LiteLLM call; verify trace appears in Langfuse Cloud dashboard. Without keys set, pipeline still runs normally.

#### Task 8: Research Agent Skip-Context Injection
**Modifies:** `teams/lead_discovery.py`
**Depends on:** Task 5 (get_known_domains, get_known_emails)
**What:** Add `known_domains` and `known_contact_emails` and `target_event_window_context` to ExaResearchAgent and HunterEnrichmentAgent instructions (appended at bottom, not replacing existing logic). These values come from the initial message JSON — agent.py will populate them before calling the team.
**Done when:** ExaResearchAgent instruction contains the `{known_domains}` reference. Running discovery with a pre-seeded domain in DB produces 0 new results for that domain.

#### Task 9: Wire agent.py to DB (full pipeline persistence)
**Modifies:** `agent.py`
**Depends on:** Task 6, Task 7, Task 8
**What:**
- `run_discovery()`: query `get_known_domains()` + `get_known_emails()` before calling teams; after Stage 1 persist orgs/contacts/events; after Stage 2 persist sequences + touches; pass known_domains/emails in the initial message
- `run_reply_handler()`: after Stage 3, write to `inbound_replies`; update org pipeline_stage; on UNSUBSCRIBE → `add_suppression()` + `cancel_remaining_touches()`; update `next_outreach_date` for NURTURE
- `run_meeting_booking()`: after Stage 4, write call_record; on BOOKED → write meeting + update org to `booked` stage
- Wrap all DB calls in try/except — pipeline must continue even if DB write fails (log error, don't crash)
**Done when:** Full end-to-end: `python agent.py discover --limit 2` → rows in crm.organizations, crm.contacts, crm.email_sequences, crm.email_touches. Second run → 0 new org rows for same domains. Reply handler → row in crm.inbound_replies with correct classification.

---

## Verification

1. `docker compose up -d` → Postgres starts on port 5432, pgAdmin on 5050
2. `alembic upgrade head` → all tables created in all 3 schemas
3. `python -c "import asyncio; from db.repositories.organizations import get_known_domains; print(asyncio.run(get_known_domains()))"` → returns empty set
4. `python agent.py discover --limit 3` → pipeline runs; pgAdmin shows rows in crm.organizations, crm.contacts, crm.email_sequences, crm.email_touches
5. Second `python agent.py discover --limit 3` → 0 new org rows for already-known domains (dedup working)
6. Langfuse Cloud dashboard shows LLM traces for each agent model call
7. `python agent.py reply --lead-id <id> --reply "Sure, let's chat"` → row in crm.inbound_replies, org stage = `replied_interested`
8. `python agent.py reply --lead-id <id> --reply "unsubscribe"` → row in crm.suppression_list, org stage = `unsubscribed`, remaining touches cancelled

1. `docker compose up -d` → Postgres starts on port 5432, pgAdmin on 5050
2. `alembic upgrade head` → all tables created in all 3 schemas
3. `python -c "import asyncio; from db.repositories.organizations import get_known_domains; print(asyncio.run(get_known_domains()))"` → returns empty set (fresh DB)
4. `python agent.py discover --limit 3` → pipeline runs, check pgAdmin for rows in `crm.organizations`, `crm.contacts`, `crm.email_sequences`
5. Run discovery a second time — should produce 0 new orgs for already-known domains
6. Langfuse Cloud dashboard should show LLM traces for each agent's model calls
7. `python agent.py reply --lead-id <id> --reply "Sure, let's chat"` → row appears in `crm.inbound_replies` with classification=INTERESTED; org stage updates to `replied_interested`
8. Reply with "unsubscribe" → row appears in `crm.suppression_list`; org stage = `unsubscribed`
