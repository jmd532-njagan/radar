# Architecture

RADAR is a FastAPI backend that turns a WatchTower pipeline-failure event into a live, human + LLM
chat investigation, with tool-gated diagnosis and an approval-gated pipeline rerun. This document
describes the system as it exists in code today.

## 1. System overview and data flow

```
WatchTower (separate app, shares this Postgres database)
        │  POST /events/pipeline-failure  (HMAC-signed, header X-Radar-Signature-256)
        ▼
src/intake/listener.py
  - verifies the signature over the raw request body
  - normalizes `project`, upserts ProjectMetadata
  - inserts a FailureEvent row (one per incoming failure, unconditionally)
  - cancelled runs stop here — no seed message, no notification, no RCA update
  - otherwise: calls chat/thread_setup.create_thread_and_notify, then upserts ProjectRCA
        ▼
FailureEvent.seed_message is populated; WatchTower's UserProjectAssignment rows (queried
directly, cross-schema) give the recipient user ids, returned to WatchTower so it can email
them — RADAR does not send email itself
        ▼
Human opens the chat (email deep-link or in-app notification bell) — a ChatThread is only
created lazily, the moment someone actually sends a message (chat/service.create_ad_hoc_thread)
        ▼
Human sends a message (often the suggested seed prompt) → llm/agent.py runs one chat turn:
RBAC-filtered, retrieval-selected ADF tools, OpenAI Agents SDK
        ▼
A tool tiered requires_consent=true (e.g. rerun_pipeline) pauses the turn; the SDK's own
needs_approval mechanism surfaces a native in-chat approve/deny prompt
        ▼
Human approves/denies → gateway/rbac.py's RBACGateway re-validates, resolves the credential
fresh, and dispatches the real Azure Data Factory SDK call. Every call (allowed or denied) is
written to AuditLog.
```

There is no LangGraph, no Teams integration, and no separate pre-chat diagnosis pipeline —
conversational chat is the only diagnosis path. A human is present for the whole investigate →
propose → approve → rerun sequence, so there is no durable pause/resume mechanism or external
approval channel; the pause is just a `pending_tool_approval` JSON blob on the `ChatThread` row
until the human resolves it.

## 2. Event ingestion (`src/intake/listener.py`)

`POST /events/pipeline-failure` accepts a `PipelineFailureEvent` payload: `project`, `platform`,
`pipeline_name`, `run_status`, `start_time`/`end_time`, `trigger_type`, `last_error`,
`error_detail` (`error_code`/`message`/`failed_activity_name`/`failed_activity_run_id`),
`failure_count`. No credentials block — RADAR resolves those itself (§3).

**Signature verification**: HMAC-SHA256 over the raw request body, carried in the
`X-Radar-Signature-256` header, checked against `settings.hmac_secret` with
`hmac.compare_digest`. Because the signature lives in a header rather than a body field, it
signs the body's actual content with nothing self-referential — a header-based scheme like
GitHub's `X-Hub-Signature-256`.

**Flow per event**:
1. Normalize `project` (lowercase, non-alphanumeric collapsed to `_`), upsert `ProjectMetadata`.
2. Insert a `FailureEvent` row unconditionally, `factory_name` resolved from RADAR's own
   `credentials` table (a project has exactly one Credential row today).
3. If `run_status` is a cancelled variant (`Cancelled`/`Cancelling`/`Canceling`), return
   immediately — no seed message, no notification, no RCA write.
4. Otherwise call `chat/thread_setup.create_thread_and_notify` (writes the seed message onto the
   `FailureEvent` row, computes recipient user ids from WatchTower's
   `UserProjectAssignment.notifyOnFailure`, writes a `notification_ready` AuditLog row).
5. If `error_detail.error_code` is present, upsert `ProjectRCA` (find-or-create keyed on
   `(pipeline_id, project, error_signature)`, incrementing `failure_count` on a repeat).

**Concurrency**: a Redis sorted-set-backed distributed semaphore
(`gateway/concurrency.py::DistributedSemaphore`), shared across replicas, wraps each chat turn
(not intake itself) — `active_investigations` zset, atomic Lua-script acquire (prune stale
entries older than `concurrency_lease_seconds`, check count, add if under
`max_concurrent_investigations`), exponential-backoff retry up to
`concurrency_max_wait_seconds` before raising. A crashed replica's stale entry self-heals via the
next acquire's prune step — no heartbeat needed.

**Batch detection**: `batch_window_seconds`/`batch_threshold` still exist as `Settings` fields,
but nothing in `intake/listener.py` calls into any batch-aggregation logic — every event
unconditionally gets its own `FailureEvent`/investigation. Batch suppression is not part of the
current flow; treat those two settings fields as unused configuration.

## 3. Credential resolution and RBAC (`src/gateway/`)

**No Azure Key Vault anywhere in this codebase.** Each project's ADF client secret is resolved
per tool call by reading straight from **WatchTower's own encrypted `public."Credential"`
Postgres table** (`gateway/credential_resolution.py::resolve_client_secret`): a cross-schema
join against `public."Service"` filtered to `name = 'adf'`, decrypted locally with
`decrypt_cryptojs_aes` using `settings.watchtower_credential_key` (must match WatchTower's own
`JWT_SECRET_KEY`). This is a local AES operation, no network I/O, and runs fresh on every
gateway call — there is no Redis or in-memory credential cache.

Non-secret ADF identifiers (`tenant_id`, `client_id`, `subscription_id`, `resource_group`,
`factory_name`) live as plain columns on RADAR's own `credentials` table (one row per
project/factory, currently one factory per project), populated at onboarding — they are
identifiers, not secrets, and grant no access on their own.

**RBAC (`gateway/rbac.py::RBACGateway`)** has no role dimension — permission is purely per-tool:
`RBACPermission(tool_name PK, allowed, requires_consent, platform)`. `RBACGateway.call()`:
1. Sets a session GUC (`app.current_platform`) as defense-in-depth against a `tool_name`
   collision across platforms (the app connects as a Postgres superuser, so RLS itself is a
   no-op — this check is done directly in `_check_permission`, not relied on from RLS).
2. Looks up `allowed` for `(tool_name, platform)`; writes an `rbac_tool_call_allowed` or
   `rbac_tool_call_denied` AuditLog row either way, logging only the caller-supplied arguments
   (never the enriched dict, so a secret is never logged).
3. If allowed, `_enrich()` merges the caller's arguments with the project's infra params and a
   freshly-resolved `client_secret` — spread *after* the caller's arguments, so a model-supplied
   key of the same name can never override the trusted server-side value.
4. Dispatches to the matching function in `mcp_servers/adf/tools/__init__.py::TOOL_REGISTRY`. An
   `Azure ClientAuthenticationError` evicts the matching entry from the Azure-client cache
   (`mcp_servers/adf/client_cache.py`) so the next call rebuilds fresh; it does not retry the
   call itself.

`requires_consent` is an independent axis from `allowed`: it decides whether the OpenAI Agents
SDK shows a native approve/deny dialog before a tool is even invoked
(`FunctionTool(needs_approval=...)`, `mcp_servers/adf/tool_search_tool.py`). `RBACGateway`'s own
`_check_permission` check is an independent, approval-mechanism-agnostic second gate.

**Authentication** is delegated, not performed by RADAR itself: identity is asserted via a
short-lived HS256 JWT (`X-Radar-Assertion`) minted by WatchTower's own backend (which already has
its own Entra ID app registration), and RADAR just verifies the signature against a shared secret
(`RADAR_ASSERTION_SECRET`, must match WatchTower's own value) and trusts the `id` claim. This is a
deliberate trusted-delegation design, not an unfinished OIDC integration.

## 4. Project, chat, and audit data model (`src/db/models.py`)

- **`ProjectMetadata`**: `project` (PK), `platform`. A project is always exactly one platform.
- **`Credential`**: one row per project/factory (`project`, `resource_group`, `factory_name`,
  `tenant_id`, `client_id`, `subscription_id`); `client_secret` is never stored here (§3).
- **`RBACPermission`**: `tool_name` (PK), `allowed`, `requires_consent`, `platform`. No role
  column.
- **`ProjectRCA`**: `(pipeline_id, project, error_signature)` unique — root-cause/fix knowledge
  base. `error_category`, `root_cause`, `fix_applied` (resent as context on every future
  known-fix check, kept short by convention), `failure_count`, `last_failure_timestamp`.
- **`FailureEvent`**: `investigation_id` (PK) — created the instant WatchTower posts, whether or
  not a human ever opens it. Holds `seed_message` (cleared once a real thread is created from
  it, via `resolved_thread_id`) and `seen_at` (set only when the specific notification row is
  clicked, distinct from `resolved_thread_id`).
- **`ChatThread`**: `thread_id` (PK, uuid). Not 1:1 with `FailureEvent` — a thread can be ad-hoc
  (project-scoped, `investigation_id` null) or failure-triggered. `claimed_by_user_id` is set via
  a single atomic conditional `UPDATE ... WHERE claimed_by_user_id IS NULL` the first time
  anyone actually sends a message or resolves an approval on the thread — an optimistic
  concurrency "claim," not set on merely opening it. `is_deleted` is a soft delete; every read
  path filters it out. `context_summary` + `summarized_through_timestamp` back LLM
  context-window management, purely as model input — never a substitute for the real transcript.
  `pending_tool_approval` (JSON) holds a paused turn's `run_state`, the pending tool calls, the
  triggering message, a creation timestamp (90-minute TTL), and the installed Agents SDK
  version.
- **`ChatMessage`**: append-only, `role` CHECK-constrained to `user`/`assistant` only — tool
  calls made while producing a reply are folded into that same assistant row's `tool_calls` JSON,
  never their own rows.
- **`ChatAnalytics`**: one row per completed turn — real token usage from the Agents SDK's own
  `Usage` object (not the UI's char-based live estimate), plus `cached_tokens` and an
  `estimated_cost` derived from a hardcoded per-model price table.
- **`MessageFeedback`**: thumbs up/down, one row per `(message_id, user_id)` — a second click
  from the same user overwrites rather than duplicates.
- **`AuditLog`**: append-only; every row is self-contained (`pipeline_name`/`project`/`platform`
  denormalized, not joined). `investigation_id` and `thread_id` are both nullable and
  independent — an ad-hoc thread has no `FailureEvent`, and some events (`notification_ready`)
  aren't chat-turn-scoped at all. `user_id` is WatchTower's real `public."User".id`, nullable for
  system-originated events (intake, RBAC checks with no user in the loop).

**Access control** is entirely app-level, not RLS (`chat/access.py`): `require_project_access`
checks WatchTower's `UserProjectAssignment` directly; `require_thread_access` is project access
plus soft-delete filtering; `require_admin` checks WatchTower's `User.isAdmin`, independent of
project assignment. Any project member can *read* every thread in that project; only the
claimant can *write* to a given thread once claimed (`chat/service.py`'s
`_require_claimant_or_unclaimed`/`_ensure_claimed_by`).

**Context-window management**: each turn's history query pulls `ChatMessage` rows newer than
`summarized_through_timestamp`, with `context_summary` (if any) prepended as a synthetic leading
message. `chat/summarization.py::maybe_summarize` runs after a turn completes and decides when
to compact — the underlying `chat_messages` table itself is never truncated; UI scrollback is
served by cursor pagination over the same table (`get_thread_with_messages`).

## 5. Tool-calling and the rerun approval flow

**Tool set** (`src/mcp_servers/adf/schemas/__init__.py`): `SPECS` is the concatenation of one
list per ADF resource kind (`pipelines`, `datasets`, `linked_services`, `data_flows`,
`triggers`, `global_parameters`, `integration_runtimes`) — 44 tools total (`len(SPECS)`), down
from an earlier 68 after the checkpoint/rollback system's 24 tools were removed. `src/mcp_servers/
adf/tools/__init__.py` builds `TOOL_REGISTRY` from `SPECS`: tools with no cross-kind equivalent
(pipeline run/error/history/rerun/cancel, trigger run/start/stop/history/rerun/cancel,
`get_linked_service`, `get_dataset_definition`, `get_data_flow_definition`, integration-runtime
status/start) are direct entries; the generic create/update/list/get-definition-raw operations
across resource kinds share four real Azure-calling implementations in `_dispatch.py`, each given
its own registry entry via a resource-type-bound thin wrapper generated from `SPECS`. Every tool
function takes the gateway-injected infra params + `client_secret` in addition to its domain
arguments — none of those appear in the tool's `params_json_schema`, so the model never sees or
supplies them.

**Per-turn tool selection** (`tool_search_tool.py::build_chat_tools`): filters `SPECS` to rows
where `RBACPermission.allowed` is true for the thread's platform, then narrows to a top-K subset
via lexical + embedding-similarity retrieval against the user's message (`_CHAT_TOP_K = 5`,
plus an always-included baseline of `list_pipelines`/`get_pipeline_definition`). Retrieval, not
static filtering, is why the agent doesn't get every ADF tool on every turn.

**Consent/approval**: each `FunctionTool`'s `needs_approval` is set from that tool's
`RBACPermission.requires_consent` row. When the SDK hits a tool needing approval, the turn
pauses; `chat/service.py` persists the pause into `ChatThread.pending_tool_approval` and returns
a `pending_approval` outcome to the frontend instead of a message. Resolving it
(`prepare_tool_approval_resolution`):
1. Requires the resolving user to be the thread's claimant.
2. Atomically claims (clears) the pending-approval JSON via a `SELECT ... FOR UPDATE` row lock —
   not `UPDATE ... RETURNING`, since that can't distinguish "I just cleared it" from "it was
   already null," which matters for rejecting a concurrent duplicate resolve (double-click,
   retry, second tab) that would otherwise double-execute a rerun.
3. Auto-denies (writes `tool_approval_expired`) if the pause is older than 90 minutes.
4. Re-checks the pending tools' `RBACPermission.allowed` in case it was revoked while the
   approval sat pending (`tool_approval_denied_revoked`).
5. On deny, writes `tool_approval_denied` — this is the only audit record of a denial, since
   `RBACGateway.call()` never runs for a rejected tool (the SDK short-circuits before invocation).
6. On approve, resumes the paused Agents SDK run, which is what actually invokes
   `RBACGateway.call()` and dispatches the real Azure call.

There is no dedicated rerun idempotency/freshness/outcome-polling logic layered on top of
`rerun_pipeline` — it is RBAC-gated and audit-logged exactly like every other tool, and the
per-call, per-turn duplicate-call guard in `tool_search_tool.py`'s `_call_gateway` (blocks an
identical repeated `tool_name` + arguments signature within the same turn) is the only
special-casing. The human approving each mutating call individually is the actual safety
mechanism, not per-tool application logic.

Tool output is also scanned for prompt-injection indicators before being handed back to the
model (`contains_injection_indicator` regex check plus an embedding-based semantic score) — ADF
resource names/error text are attacker-influenceable content, not implicitly trusted evidence,
so a flagged payload gets a warning banner prepended rather than being silently trusted.

## 6. Notifications

RADAR does not send email itself. `chat/thread_setup.py::create_thread_and_notify` writes the
seed message onto the `FailureEvent` row and computes the recipient user ids (WatchTower's
`UserProjectAssignment` rows with `notifyOnFailure = true`), returning those ids in the intake
response. Actually delivering the email is WatchTower's responsibility. The in-app side is just
the notification bell reading `FailureEvent` rows with a non-null `seed_message`
(`chat/service.py::list_notifications`/`get_pending_notification`/`mark_notification_seen`).

## 7. Known gaps

- **SOP vector store**: not built. Project SOPs exist as unstructured docs; there is no
  ingestion/embedding pipeline, so the agent cannot ground answers in them.
- **Approver fallback**: if the thread's claimant becomes unavailable mid-approval, there is no
  secondary-claimant or reassignment mechanism — the thread simply stays claimed until that user
  acts, or the 90-minute TTL auto-denies the pending approval.
- **Multi-factory-per-project**: the schema (`Credential`, unique on `project` + `factory_name`)
  supports more than one factory per project, but every other code path
  (`_resolve_factory_name`, `llm/investigation_state.py`) assumes exactly one and takes the
  first match.
- **Batch detection**: `batch_window_seconds`/`batch_threshold` remain as configuration fields
  with no code path consuming them — every failure gets its own investigation unconditionally.
- **Sandboxed tool-dispatch boundary**: `RBACGateway._dispatch()`'s actual Azure-calling step
  runs in-process with the same trust level as the rest of the request; there is no isolation
  boundary between the trusted control plane (RBAC checks, credential resolution, audit writes)
  and the step that turns LLM-decided tool calls into real network calls. Deprioritized: the
  private-VM deployment (reachable only from WatchTower) closes the external-network vector, and
  existing injection detection plus human approval on every mutating call closes most of the
  LLM-manipulation vector. The one vector this doesn't cover — a compromised dependency achieving
  in-process code execution and reading credentials straight out of `RBACGateway`'s live
  `self._redis`/`self._db` handles — was judged low-likelihood enough not to justify the full
  sandboxing build right now. Cheap partial mitigation worth doing regardless: give the app's own
  DB/Redis connections a least-privilege service account instead of full-privilege ones.
