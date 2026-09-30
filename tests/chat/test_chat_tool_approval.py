"""
Tests for the SDK-native tool-approval pause/resume flow. Most tests are router-level against
the real FastAPI app + in-memory sqlite, mocking only chat.service.chat_agent.stream_chat_turn /
resume_chat_turn (the actual LLM/Agents-SDK call) — same pattern as tests/test_chat_router.py.
Two tests exercise llm.agent's own translation of the SDK's streamed run (_consume_stream)
directly, since router-level mocking would never catch a bug in it.

The real RunState.to_json()/from_json() round-trip and the full pause->approve->resume->
execute mechanics were already validated live against the real Azure deployment during this
feature's implementation (real needs_approval tool, real interruption, real resume, real tool
execution) — not re-asserted here as an automated test, since deterministically mocking the
Agents SDK's model layer to reproduce that live behavior offline would need to reverse-engineer
SDK internals not worth the risk/maintenance for this pass.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from conftest import (
    fake_agent_stream,
    seed_watchtower_access,
    seed_watchtower_integration,
    sse_events,
)
from sqlalchemy import select

from config.settings import settings
from db.models import (
    AuditLog,
    ChatMessage,
    ChatThread,
    ProjectMetadata,
    RBACPermission,
)
from llm.agent import ChatTurnResult, _consume_stream

_NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")


def user_id_for(email: str) -> str:
    """Deterministic per-email UUID for tests — claim/approval authorization is keyed on this
    id now (chat/service.py), not email, so it must be stable across calls within one test the
    same way a real user's public.User.id would be."""
    return str(uuid.uuid5(_NAMESPACE, email))


def _auth_headers(email: str) -> dict:
    """Mints a real X-Radar-Assertion — deps.py has no unverified-header fallback (removed
    2026-07-29, spoofable-field auth bypass)."""
    token = jwt.encode(
        {"email": email, "id": user_id_for(email)},
        settings.radar_assertion_secret,
        algorithm="HS256",
    )
    return {"X-Radar-Assertion": token}


PROJECT = "acme"
USER = "alice@acme.com"
OTHER_USER = "bob@acme.com"


async def _seed_project(db_factory, users=(USER,)):
    async with db_factory() as db:
        db.add(ProjectMetadata(project=PROJECT, platform="adf"))
        db.add(
            RBACPermission(
                tool_name="update_dataset_definition",
                allowed=True,
                requires_consent=True,
            )
        )
        await db.commit()
    await seed_watchtower_integration(db_factory, PROJECT)
    for u in users:
        await seed_watchtower_access(db_factory, user_id_for(u), u, PROJECT)


async def _create_thread(db_factory, claimed_by=USER) -> int:
    async with db_factory() as db:
        thread = ChatThread(
            project=PROJECT,
            investigation_id=None,
            claimed_by_user_id=user_id_for(claimed_by) if claimed_by else None,
            created_at=datetime.now(UTC),
        )
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
        return thread.thread_id


def _pending_approval_blob(age: timedelta = timedelta(minutes=1)) -> dict:
    return {
        "run_state": {"fake": "state"},
        "sdk_version": "0.18.0",
        "pending_tools": [
            {
                "tool_call_id": "call_1",
                "tool_name": "update_dataset_definition",
                "tool_arguments": {
                    "name": "Foo",
                    "reason": "test",
                    "definition": {"type": "AzureSqlTable"},
                },
            }
        ],
        "triggering_message": "update the Foo dataset's definition",
        "created_at": (datetime.now(UTC) - age).isoformat(),
    }


@pytest.mark.asyncio
async def test_pending_approval_pauses_and_blocks_further_messages(
    chat_client, chat_db_factory
):
    await _seed_project(chat_db_factory)
    thread_id = await _create_thread(chat_db_factory)

    pending_result = ChatTurnResult(
        kind="pending_approval",
        pending_tools=[
            {
                "tool_call_id": "call_1",
                "tool_name": "update_dataset_definition",
                "tool_arguments": {},
            }
        ],
        run_state_json={"run_state": {"fake": "state"}, "sdk_version": "0.18.0"},
        triggering_message="update the Foo dataset",
    )
    with patch(
        "chat.service.chat_agent.stream_chat_turn",
        new=fake_agent_stream(pending_result),
    ):
        r = await chat_client.post(
            f"/chat/threads/{thread_id}/messages/stream",
            json={"content": "update the Foo dataset"},
            headers=_auth_headers(USER),
        )

    assert r.status_code == 200
    body = sse_events(r)[-1]
    assert body["type"] == "pending_approval"
    assert body["pending_tools"][0]["tool_name"] == "update_dataset_definition"

    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        assert thread.pending_tool_approval is not None
        assert (
            thread.pending_tool_approval["triggering_message"]
            == "update the Foo dataset"
        )

    # A second message while paused must 409, not silently start a new turn.
    r2 = await chat_client.post(
        f"/chat/threads/{thread_id}/messages/stream",
        json={"content": "anything else"},
        headers=_auth_headers(USER),
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_resolve_requires_claimant(chat_client, chat_db_factory):
    await _seed_project(chat_db_factory, users=(USER, OTHER_USER))
    thread_id = await _create_thread(chat_db_factory, claimed_by=USER)
    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        thread.pending_tool_approval = _pending_approval_blob()
        await db.commit()

    r = await chat_client.post(
        f"/chat/threads/{thread_id}/tool-approvals/resolve/stream",
        json={"decision": "approve"},
        headers=_auth_headers(OTHER_USER),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_resolve_ttl_expiry_auto_denies_with_audit_row(
    chat_client, chat_db_factory
):
    await _seed_project(chat_db_factory)
    thread_id = await _create_thread(chat_db_factory)
    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        thread.pending_tool_approval = _pending_approval_blob(age=timedelta(minutes=91))
        await db.commit()

    r = await chat_client.post(
        f"/chat/threads/{thread_id}/tool-approvals/resolve/stream",
        json={"decision": "approve"},
        headers=_auth_headers(USER),
    )
    assert r.status_code == 410

    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        assert thread.pending_tool_approval is None

        audit_result = await db.execute(
            select(AuditLog).where(AuditLog.event_type == "tool_approval_expired")
        )
        rows = list(audit_result.scalars().all())
    assert len(rows) == 1
    assert rows[0].user_id == user_id_for(USER)


@pytest.mark.asyncio
async def test_resolve_hard_denies_when_tool_no_longer_allowed(
    chat_client, chat_db_factory
):
    await _seed_project(chat_db_factory)
    thread_id = await _create_thread(chat_db_factory)
    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        thread.pending_tool_approval = _pending_approval_blob()
        # Revoke the underlying permission after the turn already paused.
        result = await db.execute(
            select(RBACPermission).where(
                RBACPermission.tool_name == "update_dataset_definition"
            )
        )
        row = result.scalar_one()
        row.allowed = False
        await db.commit()

    r = await chat_client.post(
        f"/chat/threads/{thread_id}/tool-approvals/resolve/stream",
        json={"decision": "approve"},
        headers=_auth_headers(USER),
    )
    assert r.status_code == 409

    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        assert thread.pending_tool_approval is None
        audit_result = await db.execute(
            select(AuditLog).where(
                AuditLog.event_type == "tool_approval_denied_revoked"
            )
        )
        assert len(list(audit_result.scalars().all())) == 1


@pytest.mark.asyncio
async def test_resolve_approve_completes_turn_and_persists_message(
    chat_client, chat_db_factory
):
    await _seed_project(chat_db_factory)
    thread_id = await _create_thread(chat_db_factory)
    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        thread.pending_tool_approval = _pending_approval_blob()
        await db.commit()

    completed = ChatTurnResult(
        kind="reply",
        reply_text="Done — updated.",
        tool_calls=[
            {
                "name": "update_dataset_definition",
                "call_id": "call_1",
                "status": "approved",
            }
        ],
    )
    with patch(
        "chat.service.chat_agent.resume_chat_turn",
        new=fake_agent_stream(completed),
    ):
        r = await chat_client.post(
            f"/chat/threads/{thread_id}/tool-approvals/resolve/stream",
            json={"decision": "approve"},
            headers=_auth_headers(USER),
        )

    assert r.status_code == 200
    assert sse_events(r)[-1]["message"]["content"] == "Done — updated."

    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        assert thread.pending_tool_approval is None


@pytest.mark.asyncio
async def test_resolve_deny_writes_audit_row_and_completes(
    chat_client, chat_db_factory
):
    await _seed_project(chat_db_factory)
    thread_id = await _create_thread(chat_db_factory)
    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        thread.pending_tool_approval = _pending_approval_blob()
        await db.commit()

    completed = ChatTurnResult(
        kind="reply", reply_text="Okay, not doing that.", tool_calls=[]
    )
    with patch(
        "chat.service.chat_agent.resume_chat_turn",
        new=fake_agent_stream(completed),
    ):
        r = await chat_client.post(
            f"/chat/threads/{thread_id}/tool-approvals/resolve/stream",
            json={"decision": "deny", "rejection_message": "not now"},
            headers=_auth_headers(USER),
        )

    assert r.status_code == 200
    async with chat_db_factory() as db:
        audit_result = await db.execute(
            select(AuditLog).where(AuditLog.event_type == "tool_approval_denied")
        )
        rows = list(audit_result.scalars().all())
    assert len(rows) == 1
    assert rows[0].detail["rejection_message"] == "not now"


@pytest.mark.asyncio
async def test_resolve_can_repause_on_a_second_interruption(
    chat_client, chat_db_factory
):
    await _seed_project(chat_db_factory)
    thread_id = await _create_thread(chat_db_factory)
    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        thread.pending_tool_approval = _pending_approval_blob()
        await db.commit()

    still_pending = ChatTurnResult(
        kind="pending_approval",
        pending_tools=[
            {
                "tool_call_id": "call_2",
                "tool_name": "update_dataset_definition",
                "tool_arguments": {},
            }
        ],
        run_state_json={"run_state": {"fake": "state-2"}, "sdk_version": "0.18.0"},
        triggering_message="update the Foo dataset",
    )
    with patch(
        "chat.service.chat_agent.resume_chat_turn",
        new=fake_agent_stream(still_pending),
    ):
        r = await chat_client.post(
            f"/chat/threads/{thread_id}/tool-approvals/resolve/stream",
            json={"decision": "approve"},
            headers=_auth_headers(USER),
        )

    assert sse_events(r)[-1]["type"] == "pending_approval"
    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        assert (
            thread.pending_tool_approval["pending_tools"][0]["tool_call_id"] == "call_2"
        )


class _FakeStreamed:
    """Just the shape of the SDK's RunResultStreaming that _consume_stream reads."""

    def __init__(self, events=(), interruptions=(), final_output=None):
        self._events = events
        self.interruptions = list(interruptions)
        self.final_output = final_output
        self.raw_responses = []

    async def stream_events(self):
        for event in self._events:
            yield event

    def to_state(self):
        class _State:
            def to_json(self):
                return {"fake": "state"}

        return _State()


def _response(input_tokens: int, output_tokens: int):
    class _Usage:
        input_tokens_details = None

    usage = _Usage()
    usage.input_tokens, usage.output_tokens = input_tokens, output_tokens

    class _Response:
        pass

    response = _Response()
    response.usage = usage
    return response


async def _drain(streamed, prior=None) -> list[dict]:
    return [
        e
        async for e in _consume_stream(
            streamed, "thread-1", "update the Foo dataset", prior or {}
        )
    ]


@pytest.mark.asyncio
async def test_consume_stream_translates_interruptions():
    class _RawItem:
        call_id = "call_abc"
        name = "update_dataset_definition"
        arguments = '{"name": "Foo", "reason": "test"}'

    class _ApprovalItem:
        raw_item = _RawItem()
        tool_name = "update_dataset_definition"

    events = await _drain(_FakeStreamed(interruptions=[_ApprovalItem()]))
    assert [e["type"] for e in events] == ["pending_approval"]
    ctr = events[0]["result"]
    assert ctr.kind == "pending_approval"
    assert ctr.pending_tools == [
        {
            "tool_call_id": "call_abc",
            "tool_name": "update_dataset_definition",
            "tool_arguments": {"name": "Foo", "reason": "test"},
        }
    ]
    assert ctr.run_state_json["run_state"] == {"fake": "state"}
    assert ctr.triggering_message == "update the Foo dataset"


@pytest.mark.asyncio
async def test_consume_stream_translates_a_completed_reply_and_carries_prior_legs():
    """On a resume the SDK's raw_responses already includes the paused legs' responses, so
    the token total comes from raw_responses alone, never raw_responses + saved counts."""

    class _RawItem:
        name = "get_pipeline_definition"
        call_id = "call_2"

    class _ToolCalled:
        type = "run_item_stream_event"
        name = "tool_called"

        class item:
            raw_item = _RawItem()

    prior = {
        "tool_calls": [{"name": "earlier", "call_id": "call_1", "status": "approved"}],
        "thought_seconds": 4,
    }
    streamed = _FakeStreamed(events=[_ToolCalled()], final_output="Here's the answer.")
    streamed.raw_responses = [_response(100, 10), _response(50, 5)]  # leg 1 + this leg
    events = await _drain(streamed, prior)
    assert [e["type"] for e in events] == ["tool_call", "done"]
    ctr = events[-1]["result"]
    assert ctr.kind == "reply"
    assert ctr.reply_text == "Here's the answer."
    assert ctr.tool_calls == [
        {"name": "earlier", "call_id": "call_1", "status": "approved"},
        {"name": "get_pipeline_definition", "call_id": "call_2", "status": "ran"},
    ]
    assert ctr.thought_seconds == 4
    assert (ctr.input_tokens, ctr.output_tokens) == (150, 15)


@pytest.mark.asyncio
async def test_thread_list_shows_each_threads_latest_user_message(
    chat_client, chat_db_factory
):
    await _seed_project(chat_db_factory)
    busy = await _create_thread(chat_db_factory)
    empty = await _create_thread(chat_db_factory)
    async with chat_db_factory() as db:
        for role, content in (
            ("user", "first question"),
            ("assistant", "an answer"),
            ("user", "follow-up question"),
            ("assistant", "another answer"),
        ):
            db.add(
                ChatMessage(
                    thread_id=busy,
                    role=role,
                    content=content,
                    created_at=datetime.now(UTC),
                )
            )
        await db.commit()

    r = await chat_client.get(
        "/chat/threads", params={"project": PROJECT}, headers=_auth_headers(USER)
    )
    previews = {t["thread_id"]: t["last_message"] for t in r.json()["threads"]}
    assert previews == {str(busy): "follow-up question", str(empty): None}
