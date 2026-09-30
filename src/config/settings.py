"""
RADAR's configuration, in two parts:

- `Settings`: what differs per deployment, read from the environment (.env locally) — the
  secrets and the address of the database. Every one is required with no default, so a
  deployment missing one fails at startup instead of silently falling back to a developer's
  local database or an empty key.
- Module constants: every tunable value, in one place, changed in code. Algorithm internals
  (scoring weights, retry details) stay next to the code that uses them.

RADAR runs as ONE process (one uvicorn worker, one VM): the rate limit and a chat turn's Stop
button live in this process's memory. Running more workers or replicas
would need them shared first (e.g. through Redis).
"""

from datetime import timedelta

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Azure OpenAI (Azure AI Foundry): the resource, the gpt-4o deployment on it, and its key.
    azure_openai_endpoint: str
    azure_openai_deployment: str
    azure_openai_api_key: str

    # WatchTower's Postgres; RADAR's tables are in the RADAR_DB_SCHEMA schema.
    database_url: str

    # Verifies WatchTower's HMAC-signed POST /events/pipeline-failure (intake/listener.py).
    hmac_secret: str
    # Verifies the X-Radar-Assertion JWT WatchTower's proxy sends on every chat call
    # (chat/access.py); must match WatchTower's RADAR_ASSERTION_SECRET.
    radar_assertion_secret: str
    # Decrypts each project's ADF client_secret from WatchTower's public."Credential"
    # (gateway/credential_resolution.py); must match WatchTower's JWT_SECRET_KEY.
    watchtower_credential_key: str

    # "production" disables FastAPI's /docs, /redoc and /openapi.json (main.py).
    environment: str = "development"

    @field_validator(
        "azure_openai_api_key",
        "hmac_secret",
        "radar_assertion_secret",
        "watchtower_credential_key",
    )
    @classmethod
    def _secret_not_empty(cls, value: str, info) -> str:
        # An empty HMAC/JWT secret would make signature verification trivially forgeable.
        if not value.strip():
            raise ValueError(f"{info.field_name.upper()} must be set to a real value")
        return value

    @property
    def azure_openai_v1_base_url(self) -> str:
        """Azure AI Foundry's v1 endpoint, whether azure_openai_endpoint is the bare resource
        root or already ends in /openai/v1."""
        root = self.azure_openai_endpoint.rstrip("/")
        return root if root.endswith("/openai/v1") else f"{root}/openai/v1"


settings = Settings()

# --- Models and cost ----------------------------------------------------------------------
# The model behind azure_openai_deployment.
AZURE_OPENAI_MODEL = "gpt-4o"
# gpt-4o, $ per 1M tokens (global standard; check against the Azure bill). Cached input is
# Azure's discounted rate for a repeated prompt prefix (system prompt, tool schemas).
PRICE_PER_1M_INPUT = 2.50
PRICE_PER_1M_CACHED_INPUT = 1.25
PRICE_PER_1M_OUTPUT = 10.00
# Local embedding model for tool search, injection detection and SOP search (llm/embeddings.py).
# Changing it needs every SOP re-uploaded (stored chunk embeddings come from this model).
EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"

# --- A chat turn --------------------------------------------------------------------------
# Tool calls one turn may make before answering (the Agents SDK's max_turns).
MAX_TURNS = 15
# Project memory facts shown in every prompt, ~1,500 tokens.
MEMORY_PROMPT_CHARS = 6000
# ADF tools offered per turn by relevance to the message, on top of a fixed 2-tool baseline.
ADF_TOOLS_PER_TURN = 5
# A tool approval left this long is auto-denied on next access.
APPROVAL_TTL = timedelta(minutes=90)
# Cosine similarity to known injection phrasings (evals/injection.py). A user's message over
# it is blocked, so it sits above every benign message measured; content (tool output, SOP
# text) is scored per sentence, where attacks separate more clearly.
INJECTION_THRESHOLD_USER_MESSAGE = 0.72
INJECTION_THRESHOLD_CONTENT = 0.68

# --- Conversation memory (chat/summarization.py) ------------------------------------------
# Tokens of unsummarized conversation text that trigger folding older messages into a summary.
SUMMARY_TOKEN_BUDGET = 10_000
# The most recent messages, always sent word for word.
SUMMARY_KEEP_RAW_MESSAGES = 6
SUMMARY_MAX_TOKENS = 400

# --- SOPs (llm/sop/) ------------------------------------------------------------------------
MAX_SOP_BYTES = 10 * 2**20
# Words per chunk; the largest chunk must fit the embedding model's 512-token window.
SOP_CHUNK_WORDS = 200
# Facts one SOP upload may propose: a ceiling, not a target (evals/sop_extraction.py).
SOP_MAX_FACTS = 25
# Sections returned by the search_sop tool, and put in the prompt at a failure chat's start.
SOP_SEARCH_RESULTS = 5
SOP_RESULTS_AT_FAILURE_START = 3

# --- Notifications --------------------------------------------------------------------------
NOTIFICATION_LIST_LIMIT = 30

# --- Protection -----------------------------------------------------------------------------
# Requests per caller per minute (main.py).
RATE_LIMIT_PER_MINUTE = 100
# How long a project's Azure SDK client, and the client_secret inside it, stays cached.
AZURE_CLIENT_CACHE_TTL_SECONDS = 30 * 60

# --- Logging --------------------------------------------------------------------------------
# RADAR's own loggers (main.py). Libraries log at WARNING and successful GETs aren't logged,
# so what shows is RADAR's events, writes and errors. "DEBUG" when chasing a problem locally.
LOG_LEVEL = "INFO"

# --- Database -------------------------------------------------------------------------------
RADAR_DB_SCHEMA = "radar"  # set as the connection's search_path (main.py)
# Postgres pool; shared with WatchTower's own backend, so size against Postgres's
# max_connections: DB_POOL_SIZE + DB_MAX_OVERFLOW connections at most.
DB_POOL_SIZE = 10
DB_MAX_OVERFLOW = 10
DB_POOL_TIMEOUT_SECONDS = 30.0
# Recycle before managed Postgres's own idle/lifetime limits close connections server-side.
DB_POOL_RECYCLE_SECONDS = 1800
