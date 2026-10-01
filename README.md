# RADAR

AI-powered pipeline failure investigation and remediation system. When a monitoring app (**WatchTower**) detects an Azure Data Factory pipeline failure, RADAR opens a live chat where a human works with an LLM agent to diagnose the root cause and — where safe and approved — trigger a rerun. Synapse, Databricks, and Fabric are planned; ADF is the only platform built today.

This is not a replacement for WatchTower. WatchTower detects failures; RADAR adds investigation, diagnosis, and remediation on top.

## How it works

```
WatchTower detects failure
        │
        ▼
POST /events/pipeline-failure  (HMAC-signed)
        │
        ▼
FailureEvent row created; client_secret resolved per tool
call straight from WatchTower's own encrypted Credential row
        │
        ▼
ChatThread + seed message created immediately, email sent
→ human opens the chat (no manual "diagnose" trigger needed)
        │
        ▼
Human asks a question, or sends a suggested prompt like
"diagnose this failure" — handled like any other message
        │
        ▼
The conversational LLM agent investigates/acts using real
ADF tool calls (44 distinct tools, keyword-retrieval-selected
per turn, RBAC-gated, every call logged to the audit trail)
        │
        ▼
A mutating tool call (e.g. rerun_pipeline) pauses the run and
shows a native in-chat approval prompt — human approves/denies
        │
        ▼
Approved calls execute against real ADF infrastructure through
the same RBAC-gated gateway as every other tool call — no
per-tool special-casing (e.g. no dedicated rerun idempotency/
freshness/outcome-polling logic; a human approves every mutating
call individually, which is the actual safety mechanism)
```

No LangGraph, no Teams, and no separate structured pre-chat diagnosis pipeline — the conversational chat agent is the only diagnosis path. A human is present for the entire investigate → act → approve sequence, driven entirely through chat, so there's no durable pause/resume mechanism or external approval channel to maintain.

## Folder structure

See [`docs/folder_structure.md`](docs/folder_structure.md) for the full tree.

## Getting started

```bash
uv sync --all-groups
npm install            # Prisma tooling only — see prisma/schema.prisma
cp .env.example .env   # fill in real values — see config/settings.py for the full list
npx prisma migrate deploy   # applies this repo's own radar-schema migrations
uv run python -m uvicorn main:app --reload --app-dir src
```

Or via Docker: `docker compose up --build`.

Full setup from a fresh clone (WatchTower first, admin, connecting a project): [`docs/dev-env.md`](docs/dev-env.md).

## Tech stack

FastAPI · SQLAlchemy (async, asyncpg) · OpenAI Agents SDK on Azure OpenAI gpt-4o · Azure SDKs
(`azure-identity`, `azure-mgmt-datafactory`) · local `BAAI/bge-base-en-v1.5` embeddings
(sentence-transformers) · Prisma for the `radar` schema's migrations · uv, ruff, pytest.

## Current status

**Built and working:** event ingestion with HMAC signature verification, credential resolution straight from WatchTower's own encrypted `Credential` table (no Key Vault), authentication via a WatchTower-minted signed assertion (RADAR deliberately delegates SSO to WatchTower's own Entra ID integration rather than performing OIDC itself), the full chat/RBAC/audit data model, a per-caller rate limit (in-process; RADAR runs as one process), failure patterns, project memory and SOP upload + search, the full 44-tool ADF set with correctly seeded `rbac_permissions` (`allowed`/`requires_consent` per tool), and the chat consent/approval flow via the OpenAI Agents SDK's native tool-approval mechanism.

**Not yet built:** a sandboxed tool-dispatch boundary (considered and deprioritized: private-VM deployment, injection detection and human approval on mutating calls cover most of the risk).

How it fits together, the rules for changing it and how to add a platform: [`docs/claude.md`](docs/claude.md).

## Next development steps

1. **Re-check the tuned values on real traffic** — injection thresholds (guardrail scores are logged at DEBUG), SOP search and tool selection, once real chats exist.
2. **Least-privilege DB service account** for the app's own connection — cheap, caps the blast radius of an in-process compromise without a full sandboxing project.
3. **Later, larger, less time-sensitive:** Synapse/Databricks/Fabric platform support, and an approver-fallback mechanism for an unavailable thread claimant.
