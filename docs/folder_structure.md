# Folder structure

```
radar/
├── src/                              # The application
│   ├── main.py                       # FastAPI app: lifespan (DB, model warm-up), HTTP
│   │                                 # middleware (security headers, rate limiting), routers
│   │
│   ├── config/
│   │   └── settings.py               # Secrets/DB address from .env (all required) + every tunable value
│   │
│   ├── db/                           # Plain queries, no LLM concepts
│   │   ├── models.py                 # SQLAlchemy models — single source of schema truth
│   │   ├── projects.py               # ProjectMetadata created on demand (no manual seeding)
│   │   ├── failure_patterns.py       # Failure-pattern matching, history, updates, CATEGORIES
│   │   ├── project_memory.py         # Project memory facts
│   │   └── sop.py                    # Active SOP per project, replacing it, its chunks
│   │
│   ├── intake/
│   │   ├── listener.py               # POST /events/pipeline-failure: verify, parse, match pattern, store, notify
│   │   └── signature.py              # Platform-neutral failure signatures (per-platform parser + shared masker)
│   │
│   ├── chat/                         # The chat API — the only diagnosis path
│   │   ├── router.py                 # FastAPI endpoints (chat turns stream over SSE)
│   │   ├── service.py                # Business logic behind each endpoint
│   │   ├── access.py                 # Who the caller is (X-Radar-Assertion) and what they may do
│   │   ├── admin.py                  # Admin dashboard reads (/chat/admin/*): usage, cost, members, by project/user
│   │   ├── memory.py                 # Project Memory panel: facts, patterns, SOP upload
│   │   ├── notification.py           # A new failure's seed message + who to notify
│   │   └── summarization.py          # Context-window compaction for long threads
│   │
│   ├── llm/                          # The agent and what it knows
│   │   ├── agent.py                  # The streamed chat turn: prompt, guardrail, approval pause/resume
│   │   ├── client.py                 # The Azure OpenAI client; cost estimate + one usage row per LLM call
│   │   ├── tools.py                  # The tools a turn gets: memory + SOP + the platform's tools
│   │   ├── investigation_state.py    # Everything a turn needs, rebuilt from DB rows
│   │   ├── embeddings.py             # Local bge-base embedding model
│   │   ├── injection_detection.py    # Prompt-injection check (user messages and tool output)
│   │   ├── memory/
│   │   │   └── tools.py              # get_failure_patterns, propose_failure_pattern, propose_memory
│   │   └── sop/
│   │       ├── parser.py             # .docx → heading-path chunks (defusedxml; template lines stripped)
│   │       ├── ingest.py             # Upload: parse, embed, LLM extraction into proposals, warnings
│   │       ├── search.py             # Hybrid BM25 + cosine (RRF), in memory
│   │       └── tools.py              # search_sop
│   │
│   ├── gateway/                      # Every platform tool call passes through here
│   │   ├── rbac.py                   # call_tool: permission check, audit row, credentials, dispatch
│   │   └── credential_resolution.py  # A project's ADF connection + decrypted client_secret
│   │
│   └── platform_tools/               # One tool set per data platform
│       └── adf/
│           ├── tools/                # 44 tool functions, one file per resource kind (TOOL_REGISTRY)
│           ├── schemas/              # Their LLM-facing specs, one file per resource kind
│           ├── tool_search_tool.py   # Picks the tools relevant to a message + builds FunctionTools
│           └── client_cache.py       # Per-project Azure SDK client cache
│
├── prisma/                           # schema.prisma (the "radar" Postgres schema) + seed.sql (tool
│                                     # permissions, CHECKs, partial index); migrations/ is generated
│                                     # per environment and not committed (docs/dev-env.md)
├── tests/                            # pytest, mirrors src/: chat/, config/, gateway/, intake/,
│                                     # llm/, platform_tools/adf/; conftest.py = shared fixtures
├── docs/
│   ├── claude.md                     # Read-first guide for AI assistants: rules, how to add a
│   │                                 # tool or a platform, how to verify
│   ├── dev-env.md                    # Clone → running, admin, connecting a project
│   ├── error-corpus-review.md        # The masker's output on 345 real platform errors
│   ├── folder_structure.md           # This file
│   └── watchtowerchanges.md          # Every change RADAR's branch makes to WatchTower
├── evals/, xyz/                      # Gitignored, local-only (maintainers' evals and notes)
├── .env.example                      # The environment values the app needs
├── Dockerfile, docker-compose.yml
└── pyproject.toml, uv.lock
```
