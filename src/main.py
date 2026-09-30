import logging
import os
import time
from collections import Counter
from contextlib import asynccontextmanager

# Before sentence-transformers is imported (via the routers): no model-load progress bars.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import jwt
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from chat.router import router as chat_router
from config.settings import (
    DB_MAX_OVERFLOW,
    DB_POOL_RECYCLE_SECONDS,
    DB_POOL_SIZE,
    DB_POOL_TIMEOUT_SECONDS,
    LOG_LEVEL,
    RADAR_DB_SCHEMA,
    RATE_LIMIT_PER_MINUTE,
    settings,
)
from intake.listener import router as events_router
from llm.embeddings import embed_texts_async

logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
for _noisy in (
    "httpx",
    "httpcore",
    "openai",
    "azure",
    "urllib3",
    "sentence_transformers",
    "transformers",
):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
# Its only warning is "set HF_TOKEN for faster downloads", on every start.
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)


class _WritesAndErrorsOnly(logging.Filter):
    """Drops uvicorn's access line for successful GETs — WatchTower polls notifications and
    threads constantly and /health is probed; writes (POST/PATCH/DELETE) and any 4xx/5xx stay.
    Record args: (client, method, path, http_version, status)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not (isinstance(args, tuple) and len(args) == 5):
            return True
        method, status = args[1], args[4]
        return method != "GET" or not isinstance(status, int) or status >= 400


logging.getLogger("uvicorn.access").addFilter(_WritesAndErrorsOnly())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # server_settings sets search_path for every connection in the pool — asyncpg doesn't
    # accept a raw libpq "options=" query param via SQLAlchemy's URL (SQLAlchemy forwards
    # unrecognized query params straight to asyncpg.connect(), which has no such kwarg; only
    # a full DSN string parsed by asyncpg itself understands "options=", which this isn't).
    engine = create_async_engine(
        settings.database_url,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        pool_timeout=DB_POOL_TIMEOUT_SECONDS,
        pool_recycle=DB_POOL_RECYCLE_SECONDS,
        # Replaces a connection that died while idle instead of failing the request using it.
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": RADAR_DB_SCHEMA}},
    )
    app.state.db_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Eagerly loads the local embedding model (llm/embeddings.py) here instead of lazily on
    # whatever request happens to need it first, so a real user's first turn doesn't pay the load cost.
    await embed_texts_async(["warmup"])

    yield

    await engine.dispose()


# Every caller is a known server (WatchTower's backend), never a browser, so CORS/trusted-host
# don't apply; security headers and rate limiting do.
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        return response


def _rate_limit_identity(request: Request) -> str:
    """Prefers the verified WatchTower user id (X-Radar-Assertion's 'id' claim) over client IP —
    every real chat/notification request arrives proxied through WatchTower's own backend, so
    keying by request.client.host would collapse the limit into one shared global counter for
    every end user behind that proxy IP. Falls back to IP for requests with no assertion at
    all (the HMAC-signed intake webhook has no per-user identity to key on) — this is a
    best-effort key choice for rate-limiting only, never an auth decision; an invalid/expired
    token still gets its real 401 from the route's own dependency, not here."""
    assertion = request.headers.get("X-Radar-Assertion")
    if assertion:
        try:
            payload = jwt.decode(
                assertion, settings.radar_assertion_secret, algorithms=["HS256"]
            )
            user_id = payload.get("id")
            if user_id:
                return f"user:{user_id}"
        except jwt.InvalidTokenError:
            pass
    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


class RateLimitingMiddleware(BaseHTTPMiddleware):
    """Fixed one-minute window per caller (verified user id, else client IP), counted in this
    process's memory — RADAR runs as one process. Counts reset when the minute changes, so
    memory stays bounded by the callers of one minute."""

    def __init__(self, app):
        super().__init__(app)
        self._window = -1
        self._counts: Counter[str] = Counter()

    async def dispatch(self, request: Request, call_next):
        window = int(time.time() // 60)
        if window != self._window:
            self._window, self._counts = window, Counter()
        caller = _rate_limit_identity(request)
        self._counts[caller] += 1

        if self._counts[caller] > RATE_LIMIT_PER_MINUTE:
            return JSONResponse(
                status_code=429, content={"detail": "Rate limit exceeded"}
            )

        return await call_next(request)


_is_production = settings.environment == "production"
app = FastAPI(
    title="RADAR",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)
# Order matters — Starlette's add_middleware() prepends to its internal list, so the LAST
# middleware added ends up OUTERMOST (runs first on the way in, last on the way out) — the
# reverse of call order. SecurityHeadersMiddleware is added last so it wraps everything,
# meaning a 429 from RateLimitingMiddleware (added first, so it's inner) still passes back
# through SecurityHeadersMiddleware and gets its headers on the way out.
app.add_middleware(RateLimitingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(events_router)
app.include_router(chat_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
