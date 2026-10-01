"""Project membership: admin view-only, Integrations-tab people as members (credentialUser JIN
employee ids = User.jinEmployeeId), and on-demand ProjectMetadata for freshly integrated
projects."""

from unittest.mock import AsyncMock, patch

import pytest
from conftest import seed_watchtower_integration
from sqlalchemy import text
from test_chat_tool_approval import (
    PROJECT,
    _auth_headers,
    _create_thread,
    _pending_approval_blob,
    _seed_project,
    user_id_for,
)

from chat.access import notification_recipient_ids
from db.models import ChatThread, ProjectMetadata

ADMIN = "admin@acme.com"
RESOURCE = "carol@acme.com"
CAROL_OBJECT_ID = "8194d591-3c01-4d51-9eb2-68639460113b"


async def _add_user(
    db_factory, email: str, name: str | None = None, admin=False, object_id=None
):
    async with db_factory() as db:
        await db.execute(
            text(
                'INSERT INTO public."User" (id, email, name, "isAdmin", "jinEmployeeId") '
                "VALUES (:id, :email, :name, :admin, :oid)"
            ),
            {
                "id": user_id_for(email),
                "email": email,
                "name": name,
                "admin": admin,
                "oid": object_id,
            },
        )
        await db.commit()


def _resources(*values):
    return patch(
        "chat.access._project_employee_ids", new=AsyncMock(return_value=set(values))
    )


@pytest.mark.asyncio
async def test_admin_can_read_but_not_resolve_approval_in_foreign_project(
    chat_client, chat_db_factory
):
    await _seed_project(chat_db_factory)
    await _add_user(chat_db_factory, ADMIN, admin=True)
    # The admin is the recorded claimant (e.g. claimed while still a member) but is no longer
    # assigned to the project.
    thread_id = await _create_thread(chat_db_factory, claimed_by=ADMIN)
    async with chat_db_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        thread.pending_tool_approval = _pending_approval_blob()
        await db.commit()

    read = await chat_client.get(
        f"/chat/threads/{thread_id}", headers=_auth_headers(ADMIN)
    )
    assert read.status_code == 200

    resolve = await chat_client.post(
        f"/chat/threads/{thread_id}/tool-approvals/resolve/stream",
        json={"decision": "approve"},
        headers=_auth_headers(ADMIN),
    )
    assert resolve.status_code == 403

    stop = await chat_client.post(
        f"/chat/threads/{thread_id}/stop", headers=_auth_headers(ADMIN)
    )
    assert stop.status_code == 403


@pytest.mark.asyncio
async def test_resource_is_a_member_by_object_id(chat_client, chat_db_factory):
    await _seed_project(chat_db_factory)
    await _add_user(chat_db_factory, RESOURCE, object_id=CAROL_OBJECT_ID)

    with _resources(CAROL_OBJECT_ID.upper()):
        r = await chat_client.post(
            "/chat/threads", json={"project": PROJECT}, headers=_auth_headers(RESOURCE)
        )
    assert r.status_code == 200

    r = await chat_client.post(
        "/chat/threads", json={"project": PROJECT}, headers=_auth_headers(RESOURCE)
    )
    assert r.status_code == 403  # not a resource any more, and never manually assigned


@pytest.mark.asyncio
async def test_a_user_named_like_a_resource_is_not_a_member(
    chat_client, chat_db_factory
):
    await _seed_project(chat_db_factory)
    await _add_user(chat_db_factory, "impostor@evil.com", name="Carol Danvers")

    with _resources(CAROL_OBJECT_ID, "Carol Danvers"):
        r = await chat_client.post(
            "/chat/threads",
            json={"project": PROJECT},
            headers=_auth_headers("impostor@evil.com"),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_recipients_include_resources_and_respect_manual_opt_out(chat_db_factory):
    await _seed_project(chat_db_factory)  # alice, manually assigned, notify on
    await _add_user(chat_db_factory, RESOURCE, object_id=CAROL_OBJECT_ID)
    async with chat_db_factory() as db:
        await db.execute(
            text(
                'UPDATE public."UserProjectAssignment" SET "notifyOnFailure" = 0 '
                'WHERE "userId" = :uid'
            ),
            {"uid": user_id_for("alice@acme.com")},
        )
        await db.commit()

    with _resources(CAROL_OBJECT_ID):
        async with chat_db_factory() as db:
            recipients = await notification_recipient_ids(db, PROJECT)

    assert recipients == [user_id_for(RESOURCE)]


@pytest.mark.asyncio
async def test_new_integrated_project_needs_no_seeding(chat_client, chat_db_factory):
    await _add_user(chat_db_factory, RESOURCE, object_id=CAROL_OBJECT_ID)
    await seed_watchtower_integration(chat_db_factory, "Product - Exit Application")

    with _resources(CAROL_OBJECT_ID):
        r = await chat_client.post(
            "/chat/threads",
            json={"project": "Product - Exit Application"},
            headers=_auth_headers(RESOURCE),
        )
    assert r.status_code == 200
    async with chat_db_factory() as db:
        metadata = await db.get(ProjectMetadata, "Product - Exit Application")
        assert metadata.platform == "adf"


@pytest.mark.asyncio
async def test_thread_needs_an_adf_integration(chat_client, chat_db_factory):
    await _add_user(chat_db_factory, RESOURCE, object_id=CAROL_OBJECT_ID)
    with _resources(CAROL_OBJECT_ID):
        r = await chat_client.post(
            "/chat/threads", json={"project": "nope"}, headers=_auth_headers(RESOURCE)
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_people_linked_in_credential_user_are_members(chat_db_factory):
    # How the Integrations tab saves people now: a credentialUser row per person, keyed by
    # their JIN employee id (= User.jinEmployeeId); a deleted integration counts for nothing.
    await _add_user(
        chat_db_factory, RESOURCE, name="Carol Danvers", object_id=CAROL_OBJECT_ID
    )
    await seed_watchtower_integration(chat_db_factory, PROJECT)
    async with chat_db_factory() as db:
        await db.execute(
            text(
                'INSERT INTO public."credentialUser" ("credentialId", "employeeId") '
                "VALUES (:cred, :emp)"
            ),
            {"cred": f"cred-{PROJECT}", "emp": CAROL_OBJECT_ID.upper()},
        )
        await db.commit()
        assert await notification_recipient_ids(db, PROJECT) == [user_id_for(RESOURCE)]

        await db.execute(text('UPDATE public."Credential" SET "isDeleted" = 1'))
        await db.commit()
        assert await notification_recipient_ids(db, PROJECT) == []
