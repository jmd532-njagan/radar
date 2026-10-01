"""Admin dashboard endpoints (/chat/admin/*) over a small seeded dataset, and the usage row the
memory planner writes."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from test_chat_tool_approval import (
    PROJECT,
    USER,
    _auth_headers,
    _seed_project,
    user_id_for,
)
from test_project_access import ADMIN, CAROL_OBJECT_ID, RESOURCE, _add_user, _resources

from db.models import (
    AuditLog,
    ChatAnalytics,
    ChatMessage,
    ChatThread,
    FailureEvent,
    MessageFeedback,
)
from llm.client import estimate_cost

OUTSIDER = "bob@acme.com"
ALICE, CAROL = user_id_for(USER), user_id_for(RESOURCE)
# (purpose, user, on the thread, input, output, cached)
USAGE = [
    ("chat", ALICE, True, 1000, 200, 400),
    ("title", ALICE, True, 50, 10, 0),
    ("sop_extraction", ALICE, False, 3000, 500, 0),
    ("memory_plan", CAROL, False, 100, 20, 0),
]


def _cost(*purposes):
    return sum(estimate_cost(i, o, c) for p, _, _, i, o, c in USAGE if p in purposes)


async def _seed(db_factory) -> str:
    """acme: alice assigned, carol a resource, bob nobody; one resolved and one open
    notification; one chat (alice's) with two messages, a thumbs up, two tool calls and a
    denial; usage rows of four purposes."""
    await _seed_project(
        db_factory
    )  # alice, plus update_dataset_definition needing consent
    await _add_user(db_factory, ADMIN, admin=True)
    await _add_user(db_factory, RESOURCE, name="Carol", object_id=CAROL_OBJECT_ID)
    await _add_user(db_factory, OUTSIDER, name="Bob")
    now = datetime.now(UTC)
    async with db_factory() as db:
        for investigation_id in ("inv-resolved", "inv-open"):
            db.add(
                FailureEvent(
                    investigation_id=investigation_id,
                    project=PROJECT,
                    platform="adf",
                    pipeline_name="PL_Load",
                    run_status="Failed",
                    start_time=now - timedelta(hours=1),
                    seed_message="PL_Load failed",
                    created_at=now - timedelta(minutes=30),
                )
            )
        await db.flush()
        thread = ChatThread(
            project=PROJECT,
            investigation_id="inv-resolved",
            claimed_by_user_id=ALICE,
            title="Load failure",
            created_at=now - timedelta(minutes=20),
        )
        db.add(thread)
        await db.flush()
        db.add(
            ChatMessage(
                thread_id=thread.thread_id,
                role="user",
                content="why did it fail?",
                created_at=now,
            )
        )
        answer = ChatMessage(
            thread_id=thread.thread_id,
            role="assistant",
            content="A timeout.",
            created_at=now,
        )
        db.add(answer)
        await db.flush()
        db.add(
            MessageFeedback(
                message_id=answer.id, user_id=ALICE, rating="up", created_at=now
            )
        )
        for event_type, detail in (
            ("rbac_tool_call_allowed", {"tool": "update_dataset_definition"}),
            ("rbac_tool_call_allowed", {"tool": "list_pipelines"}),
            ("tool_approval_denied", {}),
        ):
            db.add(
                AuditLog(
                    thread_id=thread.thread_id,
                    pipeline_name="PL_Load",
                    project=PROJECT,
                    platform="adf",
                    event_type=event_type,
                    user_id=ALICE,
                    detail=detail,
                )
            )
        for purpose, user, on_thread, i, o, c in USAGE:
            db.add(
                ChatAnalytics(
                    thread_id=thread.thread_id if on_thread else None,
                    purpose=purpose,
                    user_id=user,
                    project=PROJECT,
                    platform="adf",
                    model="gpt-4o",
                    input_tokens=i,
                    output_tokens=o,
                    cached_tokens=c,
                    estimated_cost=estimate_cost(i, o, c),
                    created_at=now,
                )
            )
        await db.commit()
        return thread.thread_id


@pytest.mark.asyncio
async def test_non_admin_is_refused_everywhere(chat_client, chat_db_factory):
    await _seed_project(chat_db_factory)
    headers = _auth_headers(USER)
    for path, params in (
        ("/chat/admin/overview", {}),
        ("/chat/admin/project", {"project": PROJECT}),
        ("/chat/admin/users", {}),
        (f"/chat/admin/users/{ALICE}", {}),
    ):
        r = await chat_client.get(path, params=params, headers=headers)
        assert r.status_code == 403, path


@pytest.mark.asyncio
async def test_overview(chat_client, chat_db_factory):
    await _seed(chat_db_factory)
    with _resources(CAROL_OBJECT_ID):
        r = await chat_client.get("/chat/admin/overview", headers=_auth_headers(ADMIN))
    assert r.status_code == 200
    body = r.json()

    all_purposes = [u[0] for u in USAGE]
    totals = body["totals"]
    assert totals["tokens"] == sum(i + o for *_, i, o, _ in USAGE)
    assert totals["cached_tokens"] == 400
    assert totals["cost"] == pytest.approx(_cost(*all_purposes))
    assert (totals["chats"], totals["messages"]) == (1, 2)
    assert (totals["active_projects"], totals["active_users"]) == (1, 2)

    assert {p["purpose"] for p in body["by_purpose"]} == set(all_purposes)
    assert len(body["by_day"]) >= 1
    assert sum(d["chats"] for d in body["by_day"]) == 1
    assert body["notifications"] == {
        "received": 2,
        "resolved": 1,
        "open": 1,
        "median_minutes_to_open": 10.0,
    }
    assert body["approvals"] == {"approved": 1, "denied": 1, "expired": 0}
    assert body["feedback"] == {"up": 1, "down": 0}
    assert {t["tool"]: t["calls"] for t in body["top_tools"]} == {
        "update_dataset_definition": 1,
        "list_pipelines": 1,
    }
    assert [u["user_id"] for u in body["top_users"]] == [ALICE, CAROL]
    assert body["top_users"][0]["chats"] == 1
    assert body["knowledge"]["projects_with_sop"] == 0

    (project,) = body["projects"]
    assert project["project"] == PROJECT
    assert (project["members"], project["chats"], project["open_notifications"]) == (
        2,
        1,
        1,
    )
    assert project["cost"] == pytest.approx(_cost(*all_purposes))
    assert project["last_activity"] is not None


@pytest.mark.asyncio
async def test_project(chat_client, chat_db_factory):
    thread_id = await _seed(chat_db_factory)
    with _resources(CAROL_OBJECT_ID):
        r = await chat_client.get(
            "/chat/admin/project",
            params={"project": PROJECT},
            headers=_auth_headers(ADMIN),
        )
    assert r.status_code == 200
    body = r.json()
    assert (body["project"], body["platform"]) == (PROJECT, "adf")
    assert (body["totals"]["chats"], body["totals"]["messages"]) == (1, 2)

    members = {m["user_id"]: m for m in body["members"]}
    assert members[ALICE]["sources"] == ["assigned"]
    assert members[CAROL]["sources"] == ["resource"]
    assert members[CAROL]["notify"] is True
    assert members[ALICE]["cost"] == pytest.approx(
        _cost("chat", "title", "sop_extraction")
    )
    assert members[CAROL]["tokens"] == 120

    notifications = body["notifications"]
    assert (notifications["received"], notifications["open"]) == (2, 1)
    assert {n["investigation_id"]: n["thread_id"] for n in notifications["recent"]} == {
        "inv-resolved": thread_id,
        "inv-open": None,
    }
    (chat,) = body["chats"]
    assert chat["thread_id"] == thread_id
    assert chat["claimed_by"] == {"id": ALICE, "name": None}
    assert (chat["messages"], chat["last_message"]) == (2, "why did it fail?")
    assert chat["cost"] == pytest.approx(_cost("chat", "title"))
    assert chat["investigation_id"] == "inv-resolved"
    assert set(body["memory"]) == {"facts", "patterns", "sop"}

    missing = await chat_client.get(
        "/chat/admin/project",
        params={"project": "nope"},
        headers=_auth_headers(ADMIN),
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_users_and_user(chat_client, chat_db_factory):
    thread_id = await _seed(chat_db_factory)
    headers = _auth_headers(ADMIN)
    with _resources(CAROL_OBJECT_ID):
        listed = (await chat_client.get("/chat/admin/users", headers=headers)).json()
        searched = (
            await chat_client.get(
                "/chat/admin/users", params={"q": "CAR"}, headers=headers
            )
        ).json()
        r = await chat_client.get(f"/chat/admin/users/{ALICE}", headers=headers)

    users = {u["user_id"]: u for u in listed["users"]}
    assert listed["users"][0]["user_id"] == ALICE  # highest cost first
    assert users[ALICE]["projects"] == [PROJECT]
    assert users[CAROL]["projects"] == [PROJECT]
    assert users[user_id_for(OUTSIDER)]["projects"] == []
    assert users[user_id_for(ADMIN)]["is_admin"] is True
    assert [u["user_id"] for u in searched["users"]] == [CAROL]

    assert r.status_code == 200
    body = r.json()
    assert body["user"]["user_id"] == ALICE
    assert body["totals"]["cost"] == pytest.approx(
        _cost("chat", "title", "sop_extraction")
    )
    assert (body["totals"]["chats"], body["totals"]["messages"]) == (1, 2)
    (allocation,) = body["allocations"]
    assert (allocation["project"], allocation["sources"], allocation["chats"]) == (
        PROJECT,
        ["assigned"],
        1,
    )
    assert [c["thread_id"] for c in body["chats"]] == [thread_id]

    bad = await chat_client.get("/chat/admin/users/not-a-uuid", headers=headers)
    unknown = await chat_client.get(
        f"/chat/admin/users/{uuid.uuid4()}", headers=headers
    )
    assert (bad.status_code, unknown.status_code) == (400, 404)


@pytest.mark.asyncio
async def test_memory_plan_records_usage(chat_client, chat_db_factory):
    await _seed_project(chat_db_factory)
    reply = MagicMock()
    reply.choices = [MagicMock(message=MagicMock(content='{"changes": []}'))]
    reply.usage = MagicMock(
        prompt_tokens=100,
        completion_tokens=20,
        prompt_tokens_details=MagicMock(cached_tokens=40),
    )
    with patch(
        "chat.memory.azure_client.chat.completions.create",
        AsyncMock(return_value=reply),
    ):
        r = await chat_client.post(
            "/chat/memory/plan",
            json={"project": PROJECT, "instruction": "remember loads start at 7"},
            headers=_auth_headers(USER),
        )
    assert r.status_code == 200

    async with chat_db_factory() as db:
        (row,) = (await db.execute(select(ChatAnalytics))).scalars()
    assert (row.purpose, row.user_id, row.thread_id, row.project, row.platform) == (
        "memory_plan",
        ALICE,
        None,
        PROJECT,
        "adf",
    )
    assert (row.input_tokens, row.output_tokens, row.cached_tokens) == (100, 20, 40)
    assert row.estimated_cost == pytest.approx(estimate_cost(100, 20, 40))
