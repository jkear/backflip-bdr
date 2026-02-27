# Code Review — Backflip SDR Agent Teams

**Date:** 2026-02-26
**Scope:** Full codebase review — no files modified. Observations only.
**Reviewer:** Claude Sonnet 4.6

---

## How to Read This Document

Issues are grouped by severity:

- **[BROKEN]** — Causes runtime failure or produces silently wrong data
- **[GAP]** — Feature documented or expected but missing; pipeline falls back silently
- **[BUG]** — Logical error that won't crash but produces wrong behavior
- **[DEAD]** — Code that exists but is never called or imported
- **[RISK]** — Latent problem that will surface at scale or in production
- **[QUALITY]** — Missing guard, fragile assumption, or consistency issue

---

## 1. CLI — Missing `confirm` Subcommand

**Severity: [BROKEN]**
**File:** `agent.py:9-17` (docstring), `agent.py:438-465` (`_build_arg_parser`)

The module docstring describes a third CLI subcommand:

```
python agent.py confirm --lead-id lead-001 --slot "2026-03-03T10:00:00"
```

This subcommand does not exist in `_build_arg_parser()`. Only `discover`, `reply`, and `book` are registered. The `run_meeting_booking()` function accepts `confirmed_slot: dict = None` (the direct-slot path), but there is no way to pass a `confirmed_slot` from the CLI. The `ConfirmationAgent` in Stage 4 can only be reached when `confirmed_slot` is provided, which is only possible by calling `run_meeting_booking()` programmatically.

**Impact:** The calendar event creation and confirmation email path (`ConfirmationAgent`) is unreachable from the command line. The Stage 4 `book` subcommand can only trigger the voice call or the slot proposal email — it cannot confirm a specific slot and create the calendar event.

---

## 2. Reply, Call, and Meeting Records Are Never Linked to Orgs or Contacts

**Severity: [BROKEN]**
**Files:** `agent.py:307-318`, `agent.py:393-422`

In both `run_reply_handler()` and `run_meeting_booking()`, pipeline records are persisted with hardcoded `None` values:

```python
# agent.py:307
await pipeline_repo.record_reply(
    session,
    org_id=None,       # never resolved
    contact_id=None,   # never resolved
    touch_id=None,     # never resolved
    reply_text=reply_text,
    ...
)

# agent.py:393
call_record = await pipeline_repo.record_call(
    session,
    org_id=None,       # never resolved
    contact_id=None,   # never resolved
    ...
)
```

The `lead_id` string (e.g. `"lead-001"`) passed to these stages has no resolution path. No lookup is performed to find the `Organization` or `Contact` by `lead_id`. As a result, every `InboundReply`, `CallRecord`, and `Meeting` row is orphaned — the foreign key columns (`org_id`, `contact_id`) are all `NULL` even when the data exists in the DB from Stage 1.

**Impact:** The `obs` schema and the `improve.outcome_feedback` table cannot be meaningfully queried by org. `get_org_history()` in `pipeline.py` (which joins by `org_id`) returns empty results for all orgs touched by Stage 3 or 4.

---

## 3. `schemas/` Package Is Dead Code

**Severity: [DEAD]**
**Files:** `schemas/lead.py`, `schemas/campaign.py`, `schemas/meeting.py`, `schemas/__init__.py`

A complete set of Pydantic models is defined in `schemas/`:

- `schemas/lead.py`: `RawLead`, `EnrichedLead`, `ScoredLead`, `IcpScoreDimensions`, `LeadDiscoveryOutput`, etc.
- `schemas/campaign.py`: `EmailTouch`, `EmailSequence`, `CampaignOutput`, `ReplyClassificationOutput`, `NurtureScheduleOutput`
- `schemas/meeting.py`: `CallPermissionRecord`, `CallOutcome`, `MeetingSlot`, `ConfirmedSlot`, `ConfirmationOutput`

None of these are imported anywhere — not in `agent.py`, not in any `teams/` file, not in any `tools/` file. Agent outputs are raw JSON strings parsed with `state.get("key", {})`. The schema models exist but are never used for validation, serialization, or type checking.

**Impact:** Agent output correctness is entirely trust-based. When an agent returns malformed JSON or a missing field, `state.get("key", {})` silently returns `{}` and the pipeline continues with empty data. The schemas exist to catch exactly this, but they aren't wired in.

---

## 4. `hunter_find_email()` Is Dead Code

**Severity: [DEAD]**
**File:** `tools/hunter_tools.py:99-130`

`hunter_find_email(domain, first_name, last_name)` is fully implemented, calls Hunter's `/email-finder` endpoint, and returns a validated result. It is never imported and never registered as a tool in any agent. The only Hunter tools in use are `hunter_domain_search` and `hunter_verify_email`.

---

## 5. Observability and Improvement Repos Are Never Called

**Severity: [DEAD]**
**Files:** `db/repositories/observability.py`, `db/repositories/improvement.py`

The `obs` schema has two tables: `agent_run_log` and `api_cost_log`. Repository functions `log_agent_run()` and `log_api_cost()` are defined and correct. Neither is called from `agent.py` or any team file.

Similarly, `record_outcome()` and `add_suggestion()` in `improvement.py` are never called.

Langfuse tracing is wired via LiteLLM callbacks (in `vertex_ai_init.py`) and works for LLM call tracing. But the custom observability tables (`obs.*`) and improvement feedback loop (`improve.*`) are entirely inert — the tables are created by migrations but never populated.

---

## 6. `get_free_slots()` Timezone Labeling Is Wrong

**Severity: [BUG]**
**File:** `tools/calendar_tools.py:52-83`

The function builds candidate slot datetimes using `datetime.now(timezone.utc)` and replaces only the hour:

```python
cursor = now.replace(hour=9, minute=0, second=0, microsecond=0)
candidate_start = cursor.replace(hour=hour, minute=0)
```

`cursor` is a UTC-aware datetime. The slots in the returned list are UTC ISO datetimes. But every slot is labeled:

```python
"timezone": "America/Chicago"
```

A slot generated as `2026-03-03T15:00:00+00:00` UTC is 9:00 AM Chicago time (CT = UTC-6). The label claims it is a Chicago time but the ISO string is UTC. Downstream, `CalendarProposalAgent` formats these as human-readable using the label ("Tuesday March 3rd at 9am CT") and `ConfirmationAgent` passes them to `create_event()` with `timezone="America/Chicago"`. Google Calendar will interpret the datetime as already in CT and create the event at the wrong time.

**Impact:** Calendar events are created 5–6 hours off from the intended slot (depending on DST). The free/busy check also queries UTC but the candidate times were built assuming UTC is business hours — so "9am UTC" (3am CT) may appear free but is outside business hours.

---

## 7. ElevenLabs Calls Require Twilio (Undocumented Dependency)

**Severity: [GAP]**
**File:** `tools/elevenlabs_tools.py:90`

Outbound calls use the ElevenLabs Twilio integration endpoint:

```python
resp = requests.post(
    f"{ELEVENLABS_BASE}/convai/twilio/outbound-call",
    ...
)
```

This endpoint requires a Twilio account with a phone number linked to the ElevenLabs project. An ElevenLabs API key alone is insufficient. The `.env.example`, README, and prerequisites mention nothing about Twilio. A user who sets up ElevenLabs correctly will see a 404 or 422 from this endpoint.

**What's needed:** A Twilio account, Twilio phone number, and the ElevenLabs + Twilio integration configured in the ElevenLabs dashboard. The env vars `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_PHONE_NUMBER` (or similar) are needed but absent from `.env.example`.

---

## 8. `ELEVENLABS_CONV_AGENT_ID` Is Documented but Never Read

**Severity: [GAP]**
**File:** `.env.example:46`, `tools/elevenlabs_tools.py`

`.env.example` documents `ELEVENLABS_CONV_AGENT_ID` with the note "Set after the pipeline creates the Conversational AI agent on first run." This implies the agent ID should be cached and reused. In practice, `ConversationalVoiceAgent` calls `elevenlabs_create_conv_agent()` on every Stage 4 invocation, creating a new ElevenLabs agent each time. `ELEVENLABS_CONV_AGENT_ID` is never read anywhere in the codebase. Agent IDs accumulate in ElevenLabs without reuse or cleanup.

---

## 9. `CalendarProposalAgent` Has a Contradictory Trigger Condition

**Severity: [BUG]**
**File:** `teams/meeting_booking.py:137`

The agent instruction says:

```
TRIGGER CONDITIONS (run when either is true):
  - {call_outcome}.call_status == "NO_ANSWER"
  - {call_outcome}.call_status == "SKIPPED" AND {call_permission_record}.call_permission_granted == True
  - {confirmed_slot} is provided but call_outcome is not (direct email booking path)
```

The second condition is logically impossible. `ConversationalVoiceAgent` returns `call_status: "SKIPPED"` only when `call_permission_granted` is `False` (enforced by its HARD GATE). If `call_permission_granted` were `True`, the voice agent would proceed (not SKIPPED). The agent may correctly fall through to the first condition in practice, but the contradictory rule is a logic error in the prompt that could confuse the LLM into incorrect behavior.

---

## 10. `EmailCopywriterAgent` Uses Fragile Template Syntax

**Severity: [RISK]**
**File:** `teams/outreach_strategy.py:145`

The instruction contains:

```
LEADS TO WRITE FOR:
{researched_leads}.researched_leads
```

Google ADK substitutes `{researched_leads}` with the string representation of whatever is stored in the session state under the key `researched_leads`. If `researched_leads` holds a dict like `{"researched_leads": [...]}`, the substituted text becomes `{'researched_leads': [...]}.researched_leads` — a Python dict repr with a literal `.researched_leads` suffix that the LLM must parse. This works only by relying on the LLM to understand the intent despite malformed templating.

The correct approach is to store only the list in session state (not the wrapper dict) and reference `{researched_leads}` directly, or to use a nested key reference if ADK supports it.

---

## 11. Email Sending Is Not Implemented

**Severity: [GAP]**
**Files:** `.env.example:57-61`, all `teams/` files

`.env.example` defines `SENDER_EMAIL` and `SENDER_NAME`. The pipeline generates complete 3-touch email sequences, call-permission emails, scheduling emails, and confirmation email drafts. None are sent — there is no SMTP client, no SendGrid, no Mailgun, no SES integration. All emails exist only as JSON strings in session state and output files.

This is the largest operational gap. The pipeline generates a complete outreach campaign but has no delivery mechanism.

---

## 12. `requirements.txt` and `pyproject.toml` Are Redundant

**Severity: [QUALITY]**
**Files:** `requirements.txt`, `pyproject.toml`

Both files list the same dependencies. The canonical source for UV-managed projects is `pyproject.toml` + `uv.lock`. `requirements.txt` was likely generated as a compatibility shim but can diverge from `pyproject.toml` silently. The old README instructions (`uv pip install -r requirements.txt`) would install without locking, bypassing the lockfile.

**Recommendation:** The README now documents `uv sync` (correct). `requirements.txt` is redundant and could be removed to avoid confusion.

---

## 13. Google Calendar Service Account Permissions Are Incomplete

**Severity: [RISK]**
**File:** `.env.example:13-14`

`.env.example` lists `roles/calendar.events` as the required IAM role. This IAM role grants Calendar access within a Google Workspace domain via domain-wide delegation. For a standard Gmail calendar owned by an individual (Declan), this IAM role is not applicable. Instead:

1. The service account must be granted viewer/editor access to the specific calendar via Calendar Settings → "Share with specific people."
2. If using Google Workspace, domain-wide delegation must be configured separately.
3. `roles/calendar.events` is a GCP IAM role and does not directly control Calendar sharing for personal Gmail accounts.

A user following the current instructions may configure IAM correctly but still fail to access the calendar.

---

## 14. `InboundReply.classification` Has No DB-Level CHECK Constraint

**Severity: [QUALITY]**
**File:** `db/models.py:405`, `db/migrations/versions/001_initial_schema.py:159-179`

`InboundReply.classification` stores one of `INTERESTED`, `NURTURE`, `NOT_FIT`, or `UNSUBSCRIBE`. Unlike `Organization.pipeline_stage`, `EmailSequence.status`, and `SuppressionList.source`, there is no `CheckConstraint` on this column. A malformed LLM response could persist an invalid classification value without error.

---

## 15. Session IDs Are Fixed Strings

**Severity: [RISK]**
**File:** `agent.py:114`, `agent.py:180`

```python
await run_agent(lead_discovery_team, session_id="discovery", ...)
await run_agent(outreach_strategy_team, session_id="outreach", ...)
```

`InMemorySessionService` is instantiated fresh per `run_agent()` call, so concurrent runs won't collide on the session service. However, if the orchestration is ever refactored to share a session service (e.g. to persist state across stages), the fixed IDs would cause stage 1 and stage 2 to clobber each other. Using a unique session ID (e.g., `f"discovery_{uuid4().hex[:8]}"`) is safer.

---

## 16. `DateUtil.relativedelta` Import in `db/models.py` Is Unused at Runtime

**Severity: [QUALITY]**
**File:** `db/models.py:15`

```python
from dateutil.relativedelta import relativedelta
```

This import is used only inside the `@property` methods of `Event` (`outreach_window_open`, `outreach_window_close`). These properties are Python-side computed values (not DB columns). The import is valid but it adds a runtime dependency on `python-dateutil` at model import time, which happens before the DB connection is established. This is fine but should be noted — `python-dateutil` must be installed even in testing environments that don't touch the DB.

---

## 17. `run_discovery()` Duplicates Domain Parsing Logic

**Severity: [QUALITY]**
**File:** `agent.py:138-143`, `agent.py:198-206`

The URL → domain parsing block (`urllib.parse.urlparse` → `netloc.removeprefix("www.")`) appears twice in `run_discovery()`: once to persist orgs after Stage 1, and again to build the `persisted_orgs` lookup after Stage 2. This is identical logic that could be extracted to a helper function.

---

## 18. `ANALYSIS-Feb18.md` and `Promt-mellow-puzzling-meteor.md` Are in the Project Root

**Severity: [QUALITY]**
**Files:** `ANALYSIS-Feb18.md`, `Promt-mellow-puzzling-meteor.md`

These are planning artifacts (analysis document and implementation plan) left in the project root. They are not listed in `.gitignore` and would be included in any `git add .`. Consider moving them to a `docs/` directory or archiving them once the implementation is complete.

---

## Summary Table

| # | Issue | Severity | File(s) |
|---|---|---|---|
| 1 | Missing `confirm` CLI subcommand | BROKEN | `agent.py` |
| 2 | Reply/call/meeting records always `org_id=None` | BROKEN | `agent.py` |
| 3 | `schemas/` package never imported or used | DEAD | `schemas/` |
| 4 | `hunter_find_email()` never called or registered | DEAD | `tools/hunter_tools.py` |
| 5 | Observability + improvement repos never called | DEAD | `db/repositories/observability.py`, `improvement.py` |
| 6 | `get_free_slots()` UTC slots labeled as CT | BUG | `tools/calendar_tools.py` |
| 7 | Outbound calls require Twilio (undocumented) | GAP | `tools/elevenlabs_tools.py` |
| 8 | `ELEVENLABS_CONV_AGENT_ID` env var never read | GAP | `.env.example` |
| 9 | `CalendarProposalAgent` contradictory trigger | BUG | `teams/meeting_booking.py` |
| 10 | `EmailCopywriterAgent` fragile template syntax | RISK | `teams/outreach_strategy.py` |
| 11 | Email delivery not implemented | GAP | All `teams/` |
| 12 | `requirements.txt` redundant with `pyproject.toml` | QUALITY | root |
| 13 | Service account Calendar permissions incomplete | RISK | `.env.example` |
| 14 | `InboundReply.classification` no CHECK constraint | QUALITY | `db/models.py` |
| 15 | Fixed session IDs for discovery/outreach stages | RISK | `agent.py` |
| 16 | `dateutil` import at model load time | QUALITY | `db/models.py` |
| 17 | Domain parsing logic duplicated | QUALITY | `agent.py` |
| 18 | Planning artifacts in project root | QUALITY | root |

---

## What's Working Well

- **DB layer is solid.** SQLAlchemy 2.0 async models are typed correctly (`Mapped[T]`), upserts use `pg_insert().on_conflict_do_update()` with `populate_existing=True` to avoid staleness, and suppression checks are idempotent.
- **Call gate is properly enforced.** `ConversationalVoiceAgent` has a hard gate that checks `call_permission_granted` before calling any tool. The instruction is structured clearly with the check first.
- **Domain dedup uses `removeprefix("www.")` correctly.** The earlier `lstrip("www.")` bug (which strips any combination of the characters w, ., w) was fixed.
- **Alembic migrations match the ORM models.** Schema column definitions in `001_initial_schema.py` are consistent with `db/models.py`. The `002_event_unique_constraint.py` migration correctly adds the `uq_event_org_name` constraint to close a gap from the initial schema.
- **Suppression list is well-designed.** `add_suppression()` is idempotent, normalized to lowercase, and honored at both the discovery (skip known emails) and reply-handling (auto-suppress UNSUBSCRIBE) layers.
- **ICP scoring is thoughtfully structured.** The four-dimension scoring rubric (event relevance 35 + digital ad readiness 25 + contact quality 20 + org size fit 20 = 100) is clearly specified with dimension caps enforced in both the prompt and `schemas/lead.py`.
- **Prompt files are externalized.** `icp_profiler.md`, `email_copywriter.md`, `call_permission_email.md`, and `objection_handling.md` are loaded from files at import time. This separation makes prompts editable without touching Python code.
- **Integration tests cover core dedup and suppression logic.** All 6 tests verify meaningful behavior (upsert idempotency, event window filtering, suppression checks, touch cancellation).
