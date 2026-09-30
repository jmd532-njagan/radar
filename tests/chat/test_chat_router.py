"""
Chat backend core — endpoint-level tests against the real FastAPI app, an in-memory sqlite
DB. Only the actual LLM/Agents-SDK call (chat.service.chat_agent.stream_chat_turn)
and outbound Azure/network calls are mocked — everything else (access checks, claim atomicity,
status transitions, DB writes) runs for real.
"""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

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
    FailureEvent,
    ProjectMetadata,
)
from llm.agent import ChatTurnResult

PROJECT = "acme"
USER = "alice@acme.com"
OTHER_USER = "bob@acme.com"

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


async def _seed_project(db_factory, users=(USER,)):
    async with db_factory() as db:
        db.add(ProjectMetadata(project=PROJECT, platform="adf"))
        await db.commit()
    await seed_watchtower_integration(db_factory, PROJECT)
    for u in users:
        await seed_watchtower_access(db_factory, user_id_for(u), u, PROJECT)


async def _create_ad_hoc_thread(db_factory, project=PROJECT) -> int:
    async with db_factory() as db:
        thread = ChatThread(
            project=project,
            investigation_id=None,
            created_at=datetime.now(UTC),
        )
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
        return thread.thread_id


@pytest.mark.asyncio
async def test_claim_race_second_caller_gets_409(chat_client, chat_db_factory):
    await _seed_project(chat_db_factory, users=(USER, OTHER_USER))
    thread_id = await _create_ad_hoc_thread(chat_db_factory)

    r1 = await chat_client.post(
        f"/chat/threads/{thread_id}/claim", headers=_auth_headers(USER)
    )
    assert r1.status_code == 200
    assert r1.json()["claimed_by_user_id"] == user_id_for(USER)

    r2 = await chat_client.post(
        f"/chat/threads/{thread_id}/claim", headers=_auth_headers(OTHER_USER)
    )
    assert r2.status_code == 409

    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        assert thread.claimed_by_user_id == user_id_for(
            USER
        )  # exactly one claimant persisted


@pytest.mark.asyncio
async def test_claim_is_idempotent_for_the_same_user(chat_client, chat_db_factory):
    await _seed_project(chat_db_factory)
    thread_id = await _create_ad_hoc_thread(chat_db_factory)

    r1 = await chat_client.post(
        f"/chat/threads/{thread_id}/claim", headers=_auth_headers(USER)
    )
    r2 = await chat_client.post(
        f"/chat/threads/{thread_id}/claim", headers=_auth_headers(USER)
    )
    assert r1.status_code == 200
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_access_denied_without_user_project_access(chat_client, chat_db_factory):
    await _seed_project(chat_db_factory)
    thread_id = await _create_ad_hoc_thread(chat_db_factory)

    for method, path, kwargs in [
        ("get", f"/chat/threads/{thread_id}", {}),
        ("post", f"/chat/threads/{thread_id}/claim", {}),
        (
            "post",
            f"/chat/threads/{thread_id}/messages/stream",
            {"json": {"content": "hi"}},
        ),
        ("get", "/chat/threads", {"params": {"project": PROJECT}}),
    ]:
        r = await getattr(chat_client, method)(
            path, headers=_auth_headers("nobody@x.com"), **kwargs
        )
        assert r.status_code == 403, (
            f"{method} {path} expected 403, got {r.status_code}"
        )


@pytest.mark.asyncio
async def test_missing_thread_404s(chat_client, chat_db_factory):
    await _seed_project(chat_db_factory)
    for method, path in [
        ("get", "/chat/threads/999999"),
        ("post", "/chat/threads/999999/claim"),
    ]:
        r = await getattr(chat_client, method)(path, headers=_auth_headers(USER))
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_conversational_follow_up_persists_reply_and_autoclaims(
    chat_client, chat_db_factory
):
    await _seed_project(chat_db_factory)
    thread_id = await _create_ad_hoc_thread(chat_db_factory)

    with patch(
        "chat.service.chat_agent.stream_chat_turn",
        new=fake_agent_stream(
            ChatTurnResult(
                kind="reply",
                reply_text="Here's the answer.",
                tool_calls=[
                    {
                        "name": "get_pipeline_run_history",
                        "call_id": "call_1",
                        "status": "ran",
                    }
                ],
            )
        ),
    ):
        r = await chat_client.post(
            f"/chat/threads/{thread_id}/messages/stream",
            json={"content": "why did this fail before?"},
            headers=_auth_headers(USER),
        )

    assert r.status_code == 200
    final = sse_events(r)[-1]
    assert final["type"] == "message"
    body = final["message"]
    assert body["role"] == "assistant"
    assert body["content"] == "Here's the answer."
    assert body["tool_calls"]["tools_called"] == [
        {"name": "get_pipeline_run_history", "call_id": "call_1", "status": "ran"}
    ]

    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        assert thread.claimed_by_user_id == user_id_for(USER)

        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.id)
        )
        msgs = list(result.scalars().all())
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[0].content == "why did this fail before?"


@pytest.mark.asyncio
async def test_none_reply_text_persists_fallback_instead_of_500(
    chat_client, chat_db_factory
):
    """Regression test: ChatMessage.content is NOT NULL, but the Agents SDK's final_output
    (turn_result.reply_text) isn't guaranteed non-empty even on a normal completion — this used
    to hit the NOT NULL constraint and turn an already-persisted user message into a 500."""
    await _seed_project(chat_db_factory)
    thread_id = await _create_ad_hoc_thread(chat_db_factory)

    with patch(
        "chat.service.chat_agent.stream_chat_turn",
        new=fake_agent_stream(
            ChatTurnResult(kind="reply", reply_text=None, tool_calls=[])
        ),
    ):
        r = await chat_client.post(
            f"/chat/threads/{thread_id}/messages/stream",
            json={"content": "hi"},
            headers=_auth_headers(USER),
        )

    assert r.status_code == 200
    assert sse_events(r)[-1]["message"]["content"]  # non-empty fallback, not a crash


@pytest.mark.asyncio
async def test_claimed_thread_blocks_other_user_from_posting(
    chat_client, chat_db_factory
):
    await _seed_project(chat_db_factory, users=(USER, OTHER_USER))
    thread_id = await _create_ad_hoc_thread(chat_db_factory)
    await chat_client.post(
        f"/chat/threads/{thread_id}/claim", headers=_auth_headers(USER)
    )

    r = await chat_client.post(
        f"/chat/threads/{thread_id}/messages/stream",
        json={"content": "hi"},
        headers=_auth_headers(OTHER_USER),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_ad_hoc_thread_tool_call_audits_with_null_investigation_id(
    chat_db_factory,
):
    """Exercises the exact path the AuditLog.investigation_id nullability fix was for:
    gateway.rbac.call_tool() from an ad-hoc thread (no FailureEvent, investigation_id=None) must
    not raise, and the resulting AuditLog row must actually persist with investigation_id
    NULL — not routed through the HTTP layer since this is really testing gateway/rbac.py's
    contract, not the router."""
    from gateway import rbac as rbac_module
    from gateway.rbac import call_tool

    def fake_tool(**kwargs):
        return {"ok": True}

    with (
        patch.dict(rbac_module.adf_tools.TOOL_REGISTRY, {"fake_tool": fake_tool}),
        patch.object(
            rbac_module,
            "resolve_client_secret",
            AsyncMock(return_value="s"),
        ),
    ):
        async with chat_db_factory() as db:
            # A real-shaped fake id, with actual hex letters — sqlite's dynamic type affinity
            # silently stores an all-digit string (even a flattened all-"1"s uuid) as an
            # integer/float, which then breaks uuid.UUID() parsing on read-back; real thread
            # ids are always proper UUID strings, so this only ever bites test placeholders
            # that happen to look numeric, never production data.
            fake_thread_id = "60f2295e-fd68-486c-828d-2fffaedfbdf6"
            # allow the tool: seed rbac_permissions
            from db.models import RBACPermission

            db.add(
                RBACPermission(
                    tool_name="fake_tool",
                    allowed=True,
                    requires_consent=False,
                    platform="adf",
                )
            )
            await db.commit()

            result = await call_tool(
                db,
                tool_name="fake_tool",
                arguments={},
                user_id=None,
                pipeline_id="(ad-hoc)",
                project=PROJECT,
                platform="adf",
                infra_params_dict={},
                investigation_id=None,
                thread_id=fake_thread_id,
            )
            assert result == {"ok": True}

        async with chat_db_factory() as db:
            audit_result = await db.execute(
                select(AuditLog).where(AuditLog.pipeline_name == "(ad-hoc)")
            )
            rows = list(audit_result.scalars().all())
        assert len(rows) == 1
        assert rows[0].investigation_id is None
        # thread_id is passed explicitly to call_tool — the only thing that ties this row to
        # the actual chat thread the tool call happened in.
        assert rows[0].thread_id == fake_thread_id


@pytest.mark.asyncio
async def test_pipeline_failure_event_writes_seed_message_without_creating_a_thread(
    chat_client, chat_db_factory
):
    """The concrete fix for a real, previously-existing gap: before 2026-07-28, nothing
    notified a human of a new failure until they somehow already knew to manually trigger a
    (now-retired) /diagnose call on a thread that didn't exist yet. Now POSTing the failure
    event alone must be enough — no follow-up call required. As of 2026-08-05, this must NOT
    create a ChatThread — most notifications are never opened, so a thread only gets created
    once a human actually sends something from the notification's draft chat page."""
    await _seed_project(chat_db_factory)

    payload = {
        "project": PROJECT,
        "platform": "adf",
        "pipeline_name": "PL_NEW_FAILURE",
        "run_status": "Failed",
        "start_time": datetime.now(UTC).isoformat(),
        "last_error": "Something broke",
        "failure_count": 1,
    }
    body = json.dumps(payload).encode()
    signature = hmac.HMAC(
        settings.hmac_secret.encode(), body, hashlib.sha256
    ).hexdigest()

    r = await chat_client.post(
        "/events/pipeline-failure",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Radar-Signature-256": signature,
        },
    )

    assert r.status_code == 202
    body_json = r.json()
    assert body_json["accepted"] is True
    assert "thread_id" not in body_json
    investigation_id = body_json["investigation_id"]

    async with chat_db_factory() as db:
        failure_event = await db.get(FailureEvent, investigation_id)
        assert failure_event is not None
        # The seed text lives on the FailureEvent, not a ChatThread — surfaced by the
        # notification bell / draft chat page as an unsent suggested prompt.
        assert failure_event.seed_message is not None
        assert "PL_NEW_FAILURE" in failure_event.seed_message

        result = await db.execute(
            select(ChatThread).where(ChatThread.investigation_id == investigation_id)
        )
        assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_failure_seed_message_first_time_then_matches_pattern(
    chat_client, chat_db_factory
):
    """The first failure creates a failure pattern and says so; a repeat of the same error (with
    different values) matches that pattern and reports it was seen before."""
    await _seed_project(chat_db_factory)

    async def post(column: str) -> str:
        message = (
            "ErrorCode=MappingColumnNameNotFoundInSourceFile,'Type=Microsoft.DataTransfer.Common."
            f"Shared.HybridDeliveryException,Message=Column '{column}' specified in column mapping "
            "cannot be found in 'in/customers.csv' source file.,Source=Microsoft.DataTransfer.ClientLibrary,'"
        )
        body = json.dumps(
            {
                "project": PROJECT,
                "platform": "adf",
                "pipeline_name": "PL_COPY",
                "run_status": "Failed",
                "start_time": datetime.now(UTC).isoformat(),
                "last_error": message,
                "error_detail": {"error_code": "2200", "message": message},
                "failure_count": 1,
            }
        ).encode()
        signature = hmac.HMAC(
            settings.hmac_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        r = await chat_client.post(
            "/events/pipeline-failure",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Radar-Signature-256": signature,
            },
        )
        assert r.status_code == 202
        async with chat_db_factory() as db:
            return (
                await db.get(FailureEvent, r.json()["investigation_id"])
            ).seed_message

    first = await post("ID")
    assert "Column 'ID' specified in column mapping" in first
    assert "First time this error has been seen" in first

    second = await post("ID_v2")
    assert "Matches failure pattern FP-" in second
    assert "seen 1× before" in second


@pytest.mark.asyncio
async def test_cancelled_run_writes_no_seed_message_and_notifies_nobody(
    chat_client, chat_db_factory
):
    """A cancelled run isn't a real failure — restores the old pre_check() short-circuit that
    was dropped when the structured diagnosis pipeline was retired."""
    await _seed_project(chat_db_factory)

    payload = {
        "project": PROJECT,
        "platform": "adf",
        "pipeline_name": "PL_CANCELLED_RUN",
        "run_status": "Cancelled",
        "start_time": datetime.now(UTC).isoformat(),
        "last_error": None,
        "failure_count": 1,
    }
    body = json.dumps(payload).encode()
    signature = hmac.HMAC(
        settings.hmac_secret.encode(), body, hashlib.sha256
    ).hexdigest()

    r = await chat_client.post(
        "/events/pipeline-failure",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Radar-Signature-256": signature,
        },
    )

    assert r.status_code == 202
    body_json = r.json()
    assert body_json["user_ids"] == []
    async with chat_db_factory() as db:
        failure_event = await db.get(FailureEvent, body_json["investigation_id"])
        assert failure_event is not None  # still logged for the record...
        assert (
            failure_event.seed_message is None
        )  # ...but no seed message, no notification


@pytest.mark.asyncio
async def test_only_the_claimant_can_stop_a_turn(chat_client, chat_db_factory):
    await _seed_project(chat_db_factory, users=(USER, OTHER_USER))
    thread_id = await _create_ad_hoc_thread(chat_db_factory)
    await chat_client.post(
        f"/chat/threads/{thread_id}/claim", headers=_auth_headers(USER)
    )

    other = await chat_client.post(
        f"/chat/threads/{thread_id}/stop", headers=_auth_headers(OTHER_USER)
    )
    own = await chat_client.post(
        f"/chat/threads/{thread_id}/stop", headers=_auth_headers(USER)
    )
    assert other.status_code == 403
    assert own.status_code == 200
    assert own.json() == {"cancelled": False}  # nothing was streaming


@pytest.mark.asyncio
async def test_rate_limit_rejects_calls_over_the_limit(chat_client, monkeypatch):
    import main as main_module

    monkeypatch.setattr(main_module, "RATE_LIMIT_PER_MINUTE", 2)
    monkeypatch.setattr(main_module.time, "time", lambda: 1_000_000.0)  # one window
    headers = _auth_headers("rate-limit-test@acme.com")  # a caller no other test uses

    codes = [
        (await chat_client.get("/health", headers=headers)).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]
