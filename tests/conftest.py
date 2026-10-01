import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import BigInteger, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

import main as main_module
from db.models import Base


# SQLite only auto-generates rowid values for a column declared exactly `INTEGER PRIMARY
# KEY` — BigInteger PKs (this schema's convention everywhere) compile to `BIGINT`, which
# does NOT get that autoincrement behavior, so plain inserts without an explicit id would
# fail NOT NULL. Harmless for tests: BIGINT vs INTEGER makes no difference to sqlite's
# storage (both are dynamically-typed integer affinity), only to whether PK autoincrement
# kicks in.
@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture
async def chat_db_factory():
    """In-memory sqlite engine, fresh per test — nothing chat-specific needs Postgres-only
    constructs (pg_insert etc.), so this is safe and far faster than real Postgres per test.

    Also attaches a fake "public" schema with minimal stand-ins for WatchTower's own
    public."User"/"UserProjectAssignment"/"Service"/"Credential"/"credentialUser" tables —
    chat/access.py,
    chat/notification.py and gateway/credential_resolution.py run real raw SQL against those,
    so tests need something for that SQL to hit. Only the columns those queries select/join on
    are modeled; use seed_watchtower_access()/seed_watchtower_integration() to populate them.
    Integrations-tab membership comes from credentialUser rows: insert them directly, or patch
    chat.access._project_employee_ids."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        await conn.exec_driver_sql(
            'CREATE TABLE public."User" (id TEXT PRIMARY KEY, email TEXT NOT NULL, '
            'name TEXT, "isAdmin" INTEGER NOT NULL DEFAULT 0, "jinEmployeeId" TEXT)'
        )
        await conn.exec_driver_sql(
            'CREATE TABLE public."UserProjectAssignment" ('
            '"userId" TEXT NOT NULL, "projectName" TEXT NOT NULL, "notifyOnFailure" INTEGER NOT NULL DEFAULT 1)'
        )
        await conn.exec_driver_sql(
            'CREATE TABLE public."Service" (id TEXT PRIMARY KEY, name TEXT NOT NULL)'
        )
        await conn.exec_driver_sql(
            'CREATE TABLE public."Credential" (id TEXT PRIMARY KEY, "serviceId" TEXT NOT NULL, '
            '"projectName" TEXT NOT NULL, "tenantId" TEXT, "clientId" TEXT, "clientSecret" TEXT, '
            '"subscriptionId" TEXT, "resourceGroupName" TEXT, "dataFactoryName" TEXT, '
            'resources TEXT, "isDeleted" INTEGER NOT NULL DEFAULT 0, '
            '"createdAt" TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)'
        )
        await conn.exec_driver_sql(
            'CREATE TABLE public."credentialUser" ("credentialId" TEXT NOT NULL, "employeeId" TEXT NOT NULL)'
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def seed_watchtower_access(
    db_factory, user_id: str, email: str, project: str, notify_on_failure: bool = True
) -> None:
    """Populates the fake public."User"/public."UserProjectAssignment" rows chat/access.py's
    require_project_access and chat/notification.py's recipient lookup actually query."""
    async with db_factory() as db:
        await db.execute(
            text('INSERT INTO public."User" (id, email) VALUES (:id, :email)'),
            {"id": user_id, "email": email},
        )
        await db.execute(
            text(
                'INSERT INTO public."UserProjectAssignment" ("userId", "projectName", "notifyOnFailure") '
                "VALUES (:user_id, :project, :notify)"
            ),
            {"user_id": user_id, "project": project, "notify": notify_on_failure},
        )
        await db.commit()


async def seed_watchtower_integration(db_factory, project: str) -> None:
    """A live ADF integration for `project`, as WatchTower's Integrations tab would write it."""
    async with db_factory() as db:
        await db.execute(
            text(
                """INSERT INTO public."Service" (id, name) SELECT 'svc-adf', 'adf'
                WHERE NOT EXISTS (SELECT 1 FROM public."Service" WHERE id = 'svc-adf')"""
            )
        )
        await db.execute(
            text(
                """INSERT INTO public."Credential" (id, "serviceId", "projectName", "tenantId",
                "clientId", "clientSecret", "subscriptionId", "resourceGroupName",
                "dataFactoryName") VALUES (:id, 'svc-adf', :project, 't', 'c', 'encrypted',
                's', 'rg', 'f')"""
            ),
            {"id": f"cred-{project}", "project": project},
        )
        await db.commit()


@pytest.fixture
async def chat_app(chat_db_factory):
    """Injects test doubles directly onto app.state, bypassing the real lifespan (which would
    otherwise try to connect to real Postgres) — main.app is a module-level singleton,
    so this mutates it in place for the duration of the test."""
    main_module.app.state.db_factory = chat_db_factory
    yield main_module.app


@pytest.fixture
async def chat_client(chat_app):
    transport = ASGITransport(app=chat_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def fake_agent_stream(result):
    """Stands in for llm.agent.stream_chat_turn / resume_chat_turn: a turn that ends straight
    away with `result` (a ChatTurnResult)."""

    async def stream(*args, **kwargs):
        yield {"type": "done", "result": result}

    return stream


def sse_events(response) -> list[dict]:
    """The JSON events of a streamed (SSE) response body."""
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
