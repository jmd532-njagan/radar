"""Project memory: the panel endpoints, the always-in-prompt block, and thread compaction."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.tool_context import ToolContext
from sqlalchemy import select
from test_chat_tool_approval import (
    PROJECT,
    USER,
    _auth_headers,
    _create_thread,
    _seed_project,
)
from test_project_access import ADMIN, _add_user

from chat import summarization
from db import project_memory, sop
from db.models import (
    AuditLog,
    ChatMessage,
    ChatThread,
    ProjectMemory,
    SopChunk,
    SopDocument,
)
from llm.agent import _build_chat_system_prompt
from llm.investigation_state import build_chat_state
from llm.tools import build_tools_for_platform


@pytest.mark.asyncio
async def test_member_adds_edits_and_retires_a_fact(chat_client, chat_db_factory):
    await _seed_project(chat_db_factory)
    headers = _auth_headers(USER)

    r = await chat_client.post(
        "/chat/memory",
        json={
            "project": PROJECT,
            "kind": "rule",
            "text": " Never rerun pl_finance_close. ",
        },
        headers=headers,
    )
    assert r.status_code == 200
    fact = r.json()
    assert (fact["status"], fact["origin"], fact["text"]) == (
        "active",
        "human",
        "Never rerun pl_finance_close.",
    )

    r = await chat_client.patch(
        f"/chat/memory/{fact['id']}", json={"status": "retired"}, headers=headers
    )
    assert r.json()["status"] == "retired"
    listed = (
        await chat_client.get(
            "/chat/memory", params={"project": PROJECT}, headers=headers
        )
    ).json()
    assert listed["facts"] == []

    async with chat_db_factory() as db:
        events = (
            (await db.execute(select(AuditLog.event_type).order_by(AuditLog.audit_id)))
            .scalars()
            .all()
        )
    assert events == ["memory_added", "memory_updated"]


@pytest.mark.asyncio
async def test_bad_kind_and_admin_view_only(chat_client, chat_db_factory):
    await _seed_project(chat_db_factory)
    await _add_user(chat_db_factory, ADMIN, admin=True)

    bad = await chat_client.post(
        "/chat/memory",
        json={"project": PROJECT, "kind": "gossip", "text": "x"},
        headers=_auth_headers(USER),
    )
    assert bad.status_code == 400

    assert (
        await chat_client.get(
            "/chat/memory", params={"project": PROJECT}, headers=_auth_headers(ADMIN)
        )
    ).status_code == 200
    denied = await chat_client.post(
        "/chat/memory",
        json={"project": PROJECT, "kind": "rule", "text": "x"},
        headers=_auth_headers(ADMIN),
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_active_facts_are_in_the_prompt_in_kind_order(chat_db_factory):
    await _seed_project(chat_db_factory)
    thread_id = await _create_thread(chat_db_factory)
    async with chat_db_factory() as db:
        project_memory.create(
            db, PROJECT, "schedule", "Daily ETL runs at 20:30 IST.", "human", None
        )
        project_memory.create(
            db, PROJECT, "rule", "Dev is the live environment.", "human", None
        )
        retired = project_memory.create(
            db, PROJECT, "quirk", "Retired, no longer true.", "sop", None
        )
        retired.status = "retired"
        await db.commit()
        state = await build_chat_state(db, await db.get(ChatThread, thread_id))

    prompt = _build_chat_system_prompt(state)
    memory = prompt.split("## Project memory")[1]
    assert memory.index("[rule] Dev is the live environment.") < memory.index(
        "[schedule] Daily ETL"
    )
    assert "Retired, no longer true" not in prompt
    assert prompt.index("## Project memory") < prompt.index("## This conversation")


@pytest.mark.asyncio
async def test_propose_memory_saves_an_active_incident_fact(chat_db_factory):
    await _seed_project(chat_db_factory)
    thread_id = await _create_thread(chat_db_factory)
    async with chat_db_factory() as db:
        state = await build_chat_state(db, await db.get(ChatThread, thread_id))
    tools = await build_tools_for_platform(
        "none",
        state,
        chat_db_factory,
        "hi",
        user_id=None,
    )
    propose = next(t for t in tools if t.name == "propose_memory")
    assert propose.needs_approval is True

    ctx = ToolContext(
        context=None, tool_name="propose_memory", tool_call_id="t", tool_arguments="{}"
    )
    await propose.on_invoke_tool(
        ctx,
        json.dumps(
            {
                "kind": "dependency",
                "text": "pl_b waits for pl_a.",
                "reason": "User said so.",
            }
        ),
    )
    async with chat_db_factory() as db:
        fact = (await db.execute(select(ProjectMemory))).scalar_one()
    assert (fact.kind, fact.origin, fact.status) == ("dependency", "incident", "active")


@pytest.mark.asyncio
async def test_compaction_keeps_the_latest_messages_word_for_word(chat_db_factory):
    await _seed_project(chat_db_factory)
    thread_id = await _create_thread(chat_db_factory)
    start = datetime.now(UTC)
    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        thread.created_at = start - timedelta(hours=1)
        for i in range(10):
            db.add(
                ChatMessage(
                    thread_id=thread_id,
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"message {i} " + "word " * 3000,
                    created_at=start + timedelta(seconds=i),
                )
            )
        await db.commit()

        reply = MagicMock()
        reply.choices = [MagicMock(message=MagicMock(content="Short summary."))]
        with patch.object(
            summarization.azure_client.chat.completions,
            "create",
            AsyncMock(return_value=reply),
        ):
            await summarization.maybe_summarize(db, thread, None, "adf")

    assert thread.context_summary == "Short summary."
    # Messages 0-3 folded into the summary; the last 6 (4-9) stay raw.
    assert thread.summarized_through_timestamp.replace(tzinfo=None) == (
        start + timedelta(seconds=3)
    ).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_memory_plan_keeps_only_valid_changes_and_writes_nothing(
    chat_client, chat_db_factory
):
    await _seed_project(chat_db_factory)
    headers = _auth_headers(USER)
    fact = (
        await chat_client.post(
            "/chat/memory",
            json={"project": PROJECT, "kind": "schedule", "text": "Loads start at 6."},
            headers=headers,
        )
    ).json()

    planned = {
        "changes": [
            {
                "op": "update",
                "id": fact["id"],
                "kind": "schedule",
                "text": "Loads start at 7.",
            },
            {"op": "add", "kind": "contact", "text": "Escalate to the data team."},
            {"op": "remove", "id": 99999},  # not this project's fact
            {"op": "add", "kind": "gossip", "text": "Not a real kind."},
        ]
    }
    reply = MagicMock()
    reply.choices = [MagicMock(message=MagicMock(content=json.dumps(planned)))]
    with patch(
        "chat.memory.azure_client.chat.completions.create",
        AsyncMock(return_value=reply),
    ):
        r = await chat_client.post(
            "/chat/memory/plan",
            json={
                "project": PROJECT,
                "instruction": "loads now start at 7, add the contact",
            },
            headers=headers,
        )

    assert r.status_code == 200
    assert r.json()["changes"] == [
        {
            "op": "update",
            "id": fact["id"],
            "kind": "schedule",
            "text": "Loads start at 7.",
            "before": "Loads start at 6.",
        },
        {"op": "add", "kind": "contact", "text": "Escalate to the data team."},
    ]
    listed = (
        await chat_client.get(
            "/chat/memory", params={"project": PROJECT}, headers=headers
        )
    ).json()
    assert [f["text"] for f in listed["facts"]] == ["Loads start at 6."]


@pytest.mark.asyncio
async def test_replacing_an_sop_retires_its_unedited_facts(chat_db_factory):
    await _seed_project(chat_db_factory)
    async with chat_db_factory() as db:
        old = SopDocument(
            project=PROJECT,
            file_name="old.docx",
            content_hash="x",
            version=1,
            warnings=[],
            uploaded_by=None,
            uploaded_at=datetime.now(UTC),
        )
        db.add(old)
        await db.flush()
        chunk = SopChunk(
            document_id=old.id, position=0, heading_path="A", text="t", embedding=[0.0]
        )
        db.add(chunk)
        await db.flush()
        untouched = project_memory.create(
            db, PROJECT, "schedule", "Loads at 6.", "sop", None
        )
        edited = project_memory.create(db, PROJECT, "rule", "Ask first.", "sop", None)
        untouched.source_chunk_id = edited.source_chunk_id = chunk.id
        await db.flush()
        project_memory.update(edited, None, text="Ask the client first.")
        await db.flush()

        assert await sop.replace_active(db, PROJECT) == 2
        await db.flush()
        assert (untouched.status, edited.status) == ("retired", "active")
