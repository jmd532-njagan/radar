# RADAR: guide for AI assistants

Read this whole file before you create, change, delete or test anything here. It's the
reference for how RADAR works and the rules for changing it; the code alone won't tell you
why things are the way they are. Also useful: `docs/folder_structure.md` (every file, one line
each) and `docs/dev-env.md` (running it locally).

Contents:
1. What RADAR is
2. The WatchTower contract
3. How a request flows
4. Data model
5. Memory: patterns, facts, SOPs
6. The agent's prompt and tools
7. Access control
8. API
9. Configuration and tuned values
10. Settled decisions: don't reintroduce
11. Security invariants
12. Logging
13. Tests
14. Recipes (add a tool, endpoint, table, platform, …)
15. Debugging
16. Known gaps

---

## 1. What RADAR is

A FastAPI backend that turns a data-pipeline failure into a live chat investigation. A human
and an LLM agent (Azure OpenAI gpt-4o via the OpenAI Agents SDK) work through it together. The
agent can call live platform tools (44 Azure Data Factory tools today), a human approves every
change, and what's learned is kept per project as memory.

RADAR has no UI, users, login, projects or credentials of its own. All of those belong to
**WatchTower**, a separate Next.js app that shares RADAR's Postgres database and hosts the
"RADAR AI" pages. So always ask: is this a RADAR change, a WatchTower change, or both?

Stack: Python 3.12+, FastAPI, SQLAlchemy async (asyncpg), OpenAI Agents SDK, Azure SDKs, a
local embedding model (`BAAI/bge-base-en-v1.5` via sentence-transformers), Prisma (migrations
only), uv, ruff, pytest.

## 2. The WatchTower contract

Two channels, three shared secrets.

**Failure intake** (WatchTower → RADAR). WatchTower polls each project's platform (every 5 min
in production, every 10 min locally while a browser tab is open). The first failure in a
streak is POSTed to `POST /events/pipeline-failure`:
- the raw body is signed with HMAC-SHA256 in the header `X-Radar-Signature-256`;
- the payload is `project`, `platform`, `pipeline_name`, `run_status`, `start_time`,
  `end_time`, `trigger_type`, `last_error`, and `error_detail` (`error_code`, `message`,
  `failed_activity_name`, `failed_activity_run_id`);
- the response is `{investigation_id, user_ids}`, and WatchTower emails those users. **RADAR
  never sends email.**

**Chat** (browser → WatchTower `/api/radar/*` → RADAR `/chat/*`). WatchTower adds a fresh
90-second HS256 JWT per request in `X-Radar-Assertion`, carrying `{id}` (WatchTower's
`User.id`). RADAR verifies it (`chat/access.py::get_current_user_id`) and trusts the `id`.
Chat turns stream back as Server-Sent Events.

**Shared secrets** (must match across the two `.env` files):

| RADAR | WatchTower | Used for |
|---|---|---|
| `HMAC_SECRET` | `RADAR_WEBHOOK_SECRET` | signing failure events |
| `RADAR_ASSERTION_SECRET` | `RADAR_ASSERTION_SECRET` | the per-request user JWT |
| `WATCHTOWER_CREDENTIAL_KEY` | `JWT_SECRET_KEY` | decrypting stored platform secrets (CryptoJS AES) |

**WatchTower tables RADAR reads (never writes), in `public`:**
- `User`: `id`, `name`, `email`, `isAdmin`, `jinEmployeeId` (the JIN employee id, also the
  person's Entra object id, saved at SSO login).
- `Credential` + `Service`: one row per project integration from WatchTower's Integrations
  tab. `Service.name` is the platform (`adf`, `fabric`, …); the row holds the connection
  fields, the encrypted secret, `pipelines[]` (monitored) and `resources[]` (people's names,
  display only).
- `credentialUser`: the people picked for each integration, as (`credentialId`,
  `employeeId` = `User.jinEmployeeId`, `notifyOnFailure`). This is what project membership,
  and who gets RADAR's emails, is read from.
- `AppProject`: WatchTower's project list (synced from the company's JIN database).

## 3. How a request flows

### 3.1 A failure arrives (`intake/listener.py`)
1. Verify the HMAC over the raw body; if it fails, log a warning and return 401.
2. `ensure_project_metadata`: `project_metadata` row on first sight (`project` verbatim).
3. Unless the run was cancelled, `intake/signature.py::parse` turns the error into a
   **signature**: a per-platform parser pulls out the code and error type, then a shared masker
   replaces variable parts (names, paths, ids, timestamps, numbers) with `<NAME>`, `<PATH>` and
   so on, giving a template plus a fingerprint.
4. `db/failure_patterns.py::match_or_create`: match a pattern in this project by a specific
   error code, or by fingerprint when the code is a generic wrapper (ADF `2200`, …). If none
   matches, create a `proposed` pattern. The result is `matched_by` = `code` | `fingerprint` |
   `new`.
5. Insert the `FailureEvent`, one per event, never batched.
6. Unless cancelled, `chat/notification.py::prepare_notification`:
   - builds a short templated seed message (no LLM);
   - computes the recipients (project members whose `credentialUser.notifyOnFailure` is on);
   - writes a `notification_ready` audit row.

### 3.2 A chat turn (`chat/router.py` → `chat/service.py` → `llm/agent.py`)
1. `prepare_message_send`:
   - checks write access and **claims** the thread (the first writer owns it; an atomic
     conditional UPDATE);
   - refuses if an approval is pending;
   - stores the user message;
   - builds the state (`llm/investigation_state.py::build_chat_state`: project credentials, the
     failure, the matched pattern, memory facts, top SOP sections, the summary);
   - loads the history newer than the summary cursor.
   All of this happens before streaming starts, so errors are normal HTTP errors.
2. `stream_chat_turn`:
   - builds the system prompt (§6) and the tools (`llm/tools.py::build_tools_for_platform`);
   - runs the Agents SDK with `scope_guardrail` (off-topic or injection → a generic refusal);
   - streams `token` and `tool_call` events.
3. The turn ends in one of three ways:
   - **reply:** stored as one assistant `ChatMessage` (tool calls folded into its `tool_calls`
     JSON), plus a `ChatAnalytics` row with real token usage, a title on the first turn, then
     `maybe_summarize` (the title and summary calls get their own usage rows);
   - **paused:** a tool needs approval, so the SDK `RunState` is stored in
     `chat_threads.pending_tool_approval` and the stream ends with a `pending_approval` event;
   - **stopped:** the claimant pressed Stop (an in-process registry cancels the stream).

### 3.3 A tool call
1. **Selection:** `platform_tools/adf/tool_search_tool.py::build_chat_tools`:
   - keeps the specs whose `rbac_permissions` row has `allowed = true`;
   - ranks them against the message (keyword overlap + embedding similarity);
   - offers the top 5 plus an always-included baseline (`list_pipelines`,
     `get_pipeline_definition`);
   - adds RADAR's memory and SOP tools.
2. **Approval:** each tool's `needs_approval` comes from its `requires_consent` row, and it only
   asks once the required arguments are present. Resolving an approval
   (`prepare_tool_approval_resolution`):
   - claimant only;
   - clears the pending JSON under a row lock (so double-clicks can't run it twice);
   - auto-denies after 90 min (410);
   - re-checks `allowed`;
   - writes an audit row for a denial;
   - then resumes the SDK run.
3. **Execution:** `gateway/rbac.py::call_tool`:
   - re-checks `allowed` for `(platform, tool_name)`;
   - writes an `rbac_tool_call_allowed`/`_denied` audit row with the model's arguments only;
   - merges the arguments with the server-side infra params and a freshly decrypted
     `client_secret`, **spread after** the arguments so the model can't override them;
   - runs the function in a thread. An Azure auth error evicts the cached SDK client
     (`client_cache.py`).
4. **Output:** JSON is scanned for prompt injection per sentence
   (`llm/injection_detection.py`); if flagged, a warning banner is prepended and the output is
   passed on. An identical repeated call within one turn is blocked.

### 3.4 An SOP upload (`chat/memory.py::upload_sop` → `llm/sop/ingest.py`)
1. Checks: project member only, `.docx`, at most 10 MB, not the same file as the active one
   (content hash).
2. Parse (`llm/sop/parser.py`):
   - headings come from Word heading styles, or from numbered bold titles when there are none;
   - the cover page, table of contents, template prompt lines and placeholders are dropped;
   - table rows are flattened to `Header: value; …`;
   - sections are split to about 200 words.
3. Embed the chunks (with the heading path), then replace the active document (the old one
   becomes `replaced`, its chunks are deleted, and its unapproved proposals are retired).
4. One LLM pass proposes project facts and one failure pattern per row of the SOP's RCA table
   (the symptom as a template, with no identity, so it never matches at intake). `PL_`/`TRG_`
   names found by regex are added to its pipeline list.
5. Upload warnings are stored on the document: file name vs project, pipelines named in the SOP
   vs monitored pipelines, and the SOP's project code.
6. Everything extracted is `proposed` until a member approves it in the Project Memory panel.

## 4. Data model

RADAR's tables are in the Postgres schema `radar`. `db/models.py` is what the app runs against;
`prisma/schema.prisma` is the DDL (migrations are generated from it per environment and not
committed), and `prisma/seed.sql` adds what the schema can't express: tool permissions, CHECK
constraints, the partial index. The models, the schema and the seed must agree.

| Table | What it holds |
|---|---|
| `project_metadata` | One row per project (`project` PK = WatchTower name verbatim, `platform`). FK parent of the project-scoped tables. Created on demand. |
| `failure_events` | One per incoming failure (`investigation_id` PK): the event fields, `signature` JSON, `pattern_id`, `matched_by`, `outcome`, `seed_message`, `seen_at`. |
| `failure_patterns` | One per *kind* of failure per project: `status` (proposed/active/retired), `identity` (unique per project), signature parts, `pipelines[]`, and the diagnosis (`category`, `cause`, `verify_with[]`, `fix_actions[]`, `approved_by/at`). Counts come from `failure_events`. |
| `project_memory` | Short facts: `kind` (rule, environment, schedule, dependency, contact, verify_after, quirk), `text`, `origin` (human/incident/sop), `status`, `source_chunk_id`. |
| `sop_documents` / `sop_chunks` | One active SOP per project (partial unique index); chunks with `heading_path`, `text`, `embedding` (768 floats, `real[]`). |
| `chat_threads` | `thread_id` (uuid), optional `investigation_id` (null = ad-hoc chat), `claimed_by_user_id`, `pending_tool_approval` JSON, `context_summary` + `summarized_through_timestamp`, soft delete. |
| `chat_messages` | Append-only, `role` user/assistant only; tool calls live in the assistant row's `tool_calls`. |
| `chat_analytics` | One row per LLM call (`llm/client.py::add_usage`): `purpose` (chat, sop_extraction, memory_plan, summary, title), `project`, `user_id` (who caused it), `thread_id` (null outside a thread), tokens (input/cached/output), estimated cost. A chat turn's row sums all its responses. Recording never fails the call it measures. |
| `message_feedback` | Thumbs up/down, one per (message, user). |
| `rbac_permissions` | PK `(platform, tool_name)`, `allowed`, `requires_consent`. RADAR's own tools use platform `radar`. |
| `audit_log` | Append-only, self-contained rows: `event_type`, `project`, `pipeline_name`, `platform`, `investigation_id`, `thread_id`, `user_id` (null = system), `detail` JSON. Every tool call, approval and memory change. |

## 5. Memory: patterns, facts, SOPs

Everything is **per project**; nothing is shared across projects. **Every long-term write is a
proposal a person approves**: the agent and the SOP extraction only propose.

- **Failure patterns** ("have we seen this before?"): created automatically at intake as
  `proposed`, with no diagnosis. The agent calls `propose_failure_pattern` once it has one
  (requires approval); a member approves or retires patterns in the panel. `category` is one of
  `db/failure_patterns.py::CATEGORIES`. The agent reads them via `get_failure_patterns`, and the
  matched one goes into the prompt at failure start ("Already known").
- **Project memory** (facts): active facts are **always** in the system prompt, up to
  `MEMORY_PROMPT_CHARS`. A human's fact is active at once; the agent's `propose_memory` needs
  approval.
- **SOP**: searched on demand with `search_sop(query)` (top 5), and automatically at a failure
  chat's start (top 3, using pipeline + failed activity + error), after the injection filter
  `drop_flagged`.
  - The search (`llm/sop/search.py`) runs in memory: BM25 + cosine merged with reciprocal rank
    fusion, cached per process by the active document id. There's no pgvector and no reranker
    (it cost ~9 s per search with no gain).
  - Stored embeddings come from `EMBEDDING_MODEL`: **changing the model means every SOP must be
    re-uploaded.**
- **Conversation memory**: when the unsummarized text passes `SUMMARY_TOKEN_BUDGET`,
  `chat/summarization.py` folds all but the last `SUMMARY_KEEP_RAW_MESSAGES` messages into
  `context_summary`, which is shown to the model as system context. `chat_messages` is never
  truncated.

**Trust order** when sources disagree: live tool results > approved facts > SOP text >
unapproved patterns. The agent confirms a known fix with a live tool before proposing it.

## 6. The agent's prompt and tools

`llm/agent.py::_build_chat_system_prompt` is ordered **most stable first** so Azure's prompt
cache reuses the prefix:
1. static instructions (every thread);
2. persona + project memory (every thread in the project);
3. the failure block (pipeline, time, status, masked error, code, failed activity, run id,
   trigger), "Already known" (the matched pattern) and "From the SOP";
4. the conversation summary.

Keep that order when you edit it, and keep the prompt platform-neutral (it takes `platform` as
a variable). SOP text and tool output are labelled as data, not instructions.

Tools per turn:
- RADAR's own: `get_failure_patterns`, `propose_failure_pattern`, `propose_memory`
  (`llm/memory/tools.py`), and `search_sop` (`llm/sop/tools.py`);
- plus the platform's retrieved tools.

`MAX_TURNS` caps tool calls per turn; when it's hit, the user still gets a fallback reply.
Lesson from earlier evals: **tool and prompt descriptions are the lever for tool-selection
accuracy**, not retrieval tweaks. When the agent picks the wrong tool, fix the descriptions
first.

## 7. Access control (`chat/access.py`)

A user is a **member** of a project if they're linked to one of its live integrations in
`credentialUser` (the people picked in the Integrations tab), by their JIN employee id =
`User.jinEmployeeId`. That row's `notifyOnFailure` decides whether they get RADAR's emails
(failure alerts, memory updates); it doesn't affect access.

Access rules:
- **Read** (`require_project_access`): member or admin.
- **Write** (`require_real_project_membership`): members only. Admins see every project
  read-only. This covers create, claim, rename or delete a thread; send; approve/deny; stop;
  feedback; memory edits; SOP upload.
- **Within a thread:** the first writer claims it; only the claimant can send, approve or stop.
- **Admin dashboard** (`/chat/admin/*`, `chat/admin.py`): `require_admin`, every project.

Every new endpoint must pick one of these checks explicitly.

## 8. API

| Endpoint | Purpose |
|---|---|
| `POST /events/pipeline-failure` | Failure intake (HMAC) |
| `GET /health` | Liveness |
| `GET /chat/notifications`, `GET /chat/notifications/{id}`, `POST …/{id}/seen` | Failure notifications |
| `GET/POST /chat/threads`, `GET/PATCH/DELETE /chat/threads/{id}`, `GET …/{id}/stats`, `POST …/{id}/claim` | Threads (the list carries each thread's latest user message for the project page) |
| `POST /chat/threads/{id}/messages/stream` | Send a message (SSE) |
| `POST /chat/threads/{id}/tool-approvals/resolve/stream` | Approve/deny (SSE) |
| `POST /chat/threads/{id}/stop` | Stop the running turn |
| `POST/DELETE /chat/messages/{id}/feedback` | Thumbs up/down |
| `GET/POST /chat/memory`, `PATCH /chat/memory/{id}`, `PATCH /chat/memory/patterns/{id}`, `POST /chat/memory/sop` | Project Memory panel |
| `POST /chat/memory/plan` | Plain-language "remember/forget…" → proposed fact changes (writes nothing; the panel confirms, then applies them through the endpoints above) |
| `GET /chat/admin/overview`, `GET /chat/admin/project?project=`, `GET /chat/admin/users?q=`, `GET /chat/admin/users/{id}` | Admin dashboard (`chat/admin.py`): usage/cost by day and purpose, notifications, approvals, feedback, top tools, members, chats. Admin only |

The SSE events are `token`, `tool_call`, then either `message` (done/stopped) or
`pending_approval`. `/docs` is disabled when `ENVIRONMENT=production`.

## 9. Configuration and tuned values

- `.env` holds **only** secrets and the database address, read into `Settings`
  (`config/settings.py`). All are required, and blank values are rejected at startup.
- **Every other value is a constant in `config/settings.py`**, grouped and commented. Don't add
  env vars for tunables, and don't scatter constants across modules. (Algorithm internals, such
  as scoring weights and the RRF k, stay next to their code.)

| Constant | Value | Meaning |
|---|---|---|
| `MAX_TURNS` | 15 | Tool calls per turn |
| `ADF_TOOLS_PER_TURN` | 5 | Retrieved tools on top of the 2-tool baseline |
| `MEMORY_PROMPT_CHARS` | 6000 | Project facts in the prompt (~1,500 tokens) |
| `APPROVAL_TTL` | 90 min | Pending approval auto-denied after |
| `INJECTION_THRESHOLD_USER_MESSAGE` / `_CONTENT` | 0.72 / 0.68 | Block a user message / flag tool output or SOP text |
| `SUMMARY_TOKEN_BUDGET` / `SUMMARY_KEEP_RAW_MESSAGES` / `SUMMARY_MAX_TOKENS` | 10000 / 6 / 400 | Conversation compaction |
| `SOP_CHUNK_WORDS` / `SOP_MAX_FACTS` / `SOP_SEARCH_RESULTS` / `SOP_RESULTS_AT_FAILURE_START` | 200 / 25 / 5 / 3 | SOP chunking, extraction, retrieval |
| `RATE_LIMIT_PER_MINUTE` | 100 | Per caller, in process |
| `LOG_LEVEL` | INFO | RADAR's own loggers |

These values were **measured**, not guessed: the injection thresholds on 611 labelled
messages, tools per turn on 84 selection cases, SOP search on 63 questions. Don't change one to
make a test pass or on intuition. If behavior needs to change, name the value, say why, and ask
the maintainer to re-measure. The eval harness is kept outside this repo.

## 10. Settled decisions: don't reintroduce

| Don't add | Why |
|---|---|
| LangGraph / workflow engines | A human is in the chat throughout; a flat Agents SDK loop is enough. |
| A separate diagnosis pipeline or classifier | Chat is the only diagnosis path. |
| Teams/Slack approval cards, role tiers | Approval is the SDK's per-tool pause in chat; access = membership + thread claim. |
| Key Vault or a RADAR copy of credentials | WatchTower's `Credential` table is the single source. |
| Sending email from RADAR | WatchTower does it. |
| RADAR's own login/OIDC | Identity comes from WatchTower's assertion. |
| Redis, workers, a concurrency cap | One process by design (rate limit, Stop registry and SOP cache are in memory). Scaling out needs those shared first; that's a deliberate redesign, not a drive-by. |
| Non-streamed chat endpoints | Removed; streaming only. |
| A reranker, pgvector | Measured: no gain at this size. |
| Checkpoint/rollback of ADF resources | Removed. |
| New settings as env vars | See §9. |

## 11. Security invariants

- The model never supplies credentials or project identity; the gateway's server-side values
  always win (§3.3).
- No `rbac_permissions` row → tool invisible. `allowed=false` → blocked at the gateway, even if
  the SDK offered it. Anything that changes state (create/update/delete/run/rerun/cancel/start/
  stop, and RADAR's `propose_*`) must be `requires_consent=true`.
- Tool output and SOP text are untrusted: always pass them through the injection checks.
- User messages go through `scope_guardrail`. Its refusal is deliberately generic; don't reveal
  which check fired.
- Authorization is by user id and project membership; admins are read-only. Every write path
  calls `require_real_project_membership`, and thread writes check the claimant.
- Intake accepts HMAC-signed bodies only; chat accepts only a valid assertion.
- Never log or return secrets. Audit rows log the model's arguments, never the enriched dict.
- `.env` is never committed or edited by an assistant.

## 12. Logging

Set up once in `main.py`: timestamped, RADAR's loggers at `LOG_LEVEL`, libraries at WARNING,
and successful GETs dropped from the access log. In a module, use
`logger = logging.getLogger(__name__)` and one line per event as `key=value`
(`thread=… project=…`):
- INFO for events: failure received, turn done, approval;
- WARNING for things someone should look at: bad signature, RBAC denial, guardrail block,
  injection flagged;
- `logger.exception` for caught errors.

Don't log inside loops or on reads, and never log secrets or whole messages.

## 13. Tests

- `tests/` mirrors `src/`: `tests/chat/`, `config/`, `gateway/`, `intake/`, `llm/`,
  `platform_tools/adf/`. Put a test next to what it tests. No `__init__.py`, and file names
  must be unique across folders (pytest's default import mode).
- `tests/conftest.py` puts `src/` on the path and provides:
  - `chat_db_factory`: in-memory SQLite built from `db/models.py`;
  - `chat_app` / `chat_client`: the app with that DB;
  - `seed_watchtower_access` / `seed_watchtower_integration`: WatchTower's tables;
  - `fake_agent_stream` / `sse_events`: script a turn without an LLM.
  Reuse them.
- Azure OpenAI and the Azure SDK are always mocked; tests need no credentials. The embedding
  model is real (it downloads once, ~440 MB).
- SQLite isn't Postgres: partial indexes, `FOR UPDATE` and cross-schema joins behave
  differently. Check anything Postgres-specific against a real database too.
- Commands: `uv run pytest` (~25 s), `uv run ruff check --fix .`, `uv run ruff format .`.
  lefthook runs ruff on commit.

## 14. Recipes

### Add a tool to ADF
1. **Function** in `platform_tools/adf/tools/<kind>.py`. Every public function there is a tool,
   and its name *is* the tool name (`TOOL_REGISTRY` is built by introspection). It takes the
   model's arguments plus the injected `tenant_id`, `client_id`, `client_secret`,
   `subscription_id`, `resource_group`, `factory_name`, gets the SDK client from
   `client_cache`, and returns a JSON-serializable dict.
2. **Spec** in `platform_tools/adf/schemas/<kind>.py`: `ADFToolSpec(name, description,
   params_json_schema)` with the same name. Don't put credentials in the schema. Mutating tools
   take a `reason` (`REASON_PROP`), which is shown to the approver. Write the description for
   retrieval: what it does, when to use it, and how it differs from its neighbours.
3. **Permission row** in `prisma/seed.sql` (and run the seed):
   `INSERT INTO radar.rbac_permissions (platform, tool_name, allowed, requires_consent) VALUES
   ('adf', '<name>', true, <true if it changes anything>);`
4. **Tests** in `tests/platform_tools/adf/`: the function (SDK mocked), and that representative
   messages retrieve it (`retrieve_relevant_tools`).

### Add or change a table or column
1. Edit `db/models.py`.
2. Mirror it in `prisma/schema.prisma`.
3. Add any CHECK constraint (enum-like column, length limit) or partial index to
   `prisma/seed.sql`, guarded so it's safe to re-run.
4. `npx prisma migrate dev --name <what_changed>` (generates and applies the migration locally;
   add any data backfill to that migration by hand), then run the seed, check the live schema
   matches the models, and run the tests.

Migrations aren't committed: every environment generates its own from the schema. Never touch
WatchTower's `public` tables.

### Add an LLM call
Record its usage: `add_usage(db, response.usage, purpose=…, project=…, platform=…, user_id=…)`
from `llm/client.py`, with a new `purpose` added to the `chat_analytics` CHECK (model +
migration).

### Add an endpoint
1. Add the route in `chat/router.py`, keeping it thin.
2. Put the logic in `chat/service.py` (or `chat/memory.py` for memory).
3. Take the user from `Depends(get_current_user_id)` and call the right access check (§7).
4. Write an audit row for any state change.
5. Add a test in `tests/chat/` using `chat_client`.
6. Add WatchTower's proxy route under `/api/radar/*` if the browser needs it.

### Add a memory tool or fact kind
- **Tools** go in `llm/memory/tools.py`. They need an `rbac_permissions` row with
  platform `radar`, and a proposing tool needs `requires_consent=true`.
- **A new fact kind** needs three changes: `db/project_memory.py::KINDS`, the DB CHECK
  constraint (migration) and the extraction prompt in `llm/sop/ingest.py`.

### Change the prompt
- Edit `llm/agent.py`, keeping the stable-first order (§6) and platform-neutral wording.
- Chat-router tests assert on parts of it; update them deliberately.
- Behavior changes are judged on real conversations, not only tests.

### Add a signature parser for a platform
Add a parser to `intake/signature.py::_PARSERS`: return the code, the error type and the core
message. Don't add platform-specific masking; the masker is shared. If the platform has codes
that wrap many unrelated causes, add them to `_GENERIC_WRAPPER_CODES` so those match by
fingerprint. Test it with real error messages in `tests/intake/test_signature.py`: the same
error with different values must give the same fingerprint, and different errors different
ones.

### Add a new platform (for example Microsoft Fabric)

Start by tracing ADF end to end (§3). A new platform follows the same path.

**What already exists.** WatchTower stores Fabric connections (Integrations → Fabric):
`tenantId`, `clientId`, encrypted `clientSecret`, `workspaceId`, `pipelines[]`, `resources[]`
on `public."Credential"`, with `Service.name = 'fabric'`. WatchTower already polls Fabric and
POSTs Fabric failures to RADAR with `platform: "fabric"`. RADAR already routes `"fabric"` to the
Azure error parser.

**What's missing:**

1. **WatchTower: error detail.** Fabric failures arrive with `last_error` and `error_detail`
   null, because `src/lib/radar/error-detail/` only implements ADF. Without the error text RADAR
   can't build a signature, so no pattern matching, no SOP lookup by error, and a seed message
   saying "no error message". Implement the Fabric fetch (the job instance's `failureReason`, or
   pipeline activity runs) first.
2. **RADAR: credentials.** `gateway/credential_resolution.py::get_adf_credential` reads only
   the `adf` Service and ADF columns. Add the Fabric lookup (its own columns; `workspaceId`
   instead of subscription/resource group/factory). The CryptoJS decryption is shared.
3. **RADAR: chat state and threads.** These hardcode ADF:
   - `llm/investigation_state.py::build_chat_state` raises without an ADF credential;
   - `chat/service.py::create_ad_hoc_thread` returns 404 without one and records the project as
     `"adf"`;
   - `llm/sop/ingest.py` defaults an unknown project to `"adf"`;
   - `intake/listener.py` reads `factory_name` from the ADF credential.

   Resolve by the project's platform instead. Today a Fabric-only project gets its failures
   stored and emailed, but opening the chat fails.
4. **RADAR: tools.** Create `platform_tools/fabric/` mirroring `platform_tools/adf/`:
   `tools/` (one module per resource kind, public function = tool), `schemas/` (specs), a
   client cache if the SDK client is expensive, and a `build_chat_tools` entry point.
   `tool_search_tool.py`'s ranking logic (keyword index, semantic score, top-k) is
   platform-neutral; with a second platform, move that half into a shared module and keep only
   the spec lists, synonyms and baseline tools per platform. Don't copy it.
5. **RADAR: dispatch.** `llm/tools.py::build_tools_for_platform` needs a `"fabric"` branch.
   `gateway/rbac.py::call_tool` / `_dispatch` use only the ADF `TOOL_REGISTRY` and ADF-shaped
   `infra_params`; choose the registry, credentials and auth-error handling by `platform`.
6. **Permissions:** a migration inserting `rbac_permissions` rows with `platform = 'fabric'`.
   Tool names may repeat ADF's, since the key is `(platform, tool_name)`.
7. **Settings:** rename `ADF_TOOLS_PER_TURN` to a platform-neutral name (or add a per-platform
   value) in `config/settings.py`.
8. **Prompt:** check it reads correctly for Fabric (it's platform-neutral by design).

**How to verify:**
- **Unit tests:**
  - `tests/platform_tools/fabric/` for every tool (SDK mocked);
  - `tests/gateway/` for Fabric credential resolution, dispatch and the permission check;
  - `tests/chat/` for a Fabric thread, both failure-triggered and ad-hoc;
  - `tests/intake/` with real Fabric error messages.
- **End to end:**
  1. Add a real Fabric project in WatchTower's Integrations tab with yourself as a resource.
  2. Fail a monitored pipeline.
  3. Check the log for `Failure received: project=… pipeline=… pattern=FP-n (new)`.
  4. Open the chat, ask about the failure and confirm `Turn done … tools=[…]` shows Fabric
     tools.
  5. Trigger a mutating tool, confirm it pauses for approval and that `radar.audit_log` has the
     rows.
- **Tool selection:** check that representative messages retrieve the right Fabric tools
  before relying on it.

## 15. Debugging

| Symptom | Where to look |
|---|---|
| Failures don't arrive | RADAR log: `Failure event rejected` = HMAC mismatch. Nothing at all = WatchTower isn't polling or the pipeline isn't in `Credential.pipelines`. |
| A user sees no project / gets 403 | `chat/access.py`: are they linked to the project's integration in `credentialUser` (their `jinEmployeeId`)? Admins are read-only. |
| 401 on chat calls | `RADAR_ASSERTION_SECRET` mismatch, or the user has no `User` row. |
| "Failed to decrypt client_secret" | `WATCHTOWER_CREDENTIAL_KEY` ≠ WatchTower `JWT_SECRET_KEY`. |
| Agent doesn't use a tool | Is it in `rbac_permissions` with `allowed`? Is it retrieved for that message (`retrieve_relevant_tools`)? Is the description clear? |
| Message refused as off-topic | Log `Guardrail: blocked=True …` shows which check fired and the score. |
| What happened in a thread | `SELECT * FROM radar.audit_log WHERE thread_id = '…' ORDER BY timestamp`, and the `thread=` log lines. |
| Cost/usage | `radar.chat_analytics` (by `purpose`), or the admin dashboard. |
| A duplicate pattern for the same error | Compare the two events' `signature` JSON: which part differs (code, template)? Fix it in the parser or masker, not by merging rows by hand. |

## 16. Known gaps

- **Projects are keyed by name.** Renaming a project in WatchTower orphans its RADAR data. The
  proper fix is end to end: WatchTower stores and sends the JIN project id, and RADAR keys on
  it. Don't normalize names as a workaround.
- **One ADF factory per project:** with several `Credential` rows, the oldest wins.
- **No approver fallback:** if the claimant disappears mid-approval, the 90-minute TTL is the
  only way out.
- **Resource access needs a prior login (or the Azure user refresh):** until then, their
  `jinEmployeeId` isn't known.
- **Tool calls run in-process,** with the app's trust level. This is acceptable on a private VM
  reachable only by WatchTower. A least-privilege DB account for the app is a cheap mitigation
  still to do.
- **Only ADF has tools.** Other platforms get failure intake and memory, but no live tools and
  no chat (see §14).
