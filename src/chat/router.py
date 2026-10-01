"""
Thin FastAPI layer over chat/service.py — parses requests, calls service functions, returns
JSON. Reads request.app.state.db_factory directly (matching intake/listener.py's
convention); Depends() is used only for get_current_user_id, so there's exactly one new
DI pattern introduced here, not two competing styles.
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from chat import admin, memory, service
from chat.access import get_current_user_id
from chat.summarization import count_tokens
from config.settings import MAX_SOP_BYTES

router = APIRouter(prefix="/chat")


class CreateThreadRequest(BaseModel):
    project: str
    investigation_id: str | None = None


class MessageRequest(BaseModel):
    content: str


class ToolApprovalResolveRequest(BaseModel):
    decision: Literal["approve", "deny"]
    tool_call_id: str | None = None
    rejection_message: str | None = None


class RenameThreadRequest(BaseModel):
    title: str


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]


class MemoryFactRequest(BaseModel):
    project: str
    kind: str
    text: str


class MemoryPlanRequest(BaseModel):
    project: str
    instruction: str


class PatternStatusUpdate(BaseModel):
    status: str


class MemoryFactUpdate(BaseModel):
    kind: str | None = None
    text: str | None = None
    status: str | None = None  # proposed | active | retired


def _message_out(m) -> dict:
    return {
        "id": m.id,
        "thread_id": m.thread_id,
        "role": m.role,
        "content": m.content,
        "tool_calls": m.tool_calls,
        "created_at": m.created_at.isoformat(),
        "token_count": count_tokens(m.content),
    }


def _thread_out(t) -> dict:
    # pending_tools surfaces a stuck approval (e.g. the user navigated away before resolving
    # it) so the frontend can rebuild the approval card on load instead of the thread being
    # silently blocked from new messages (prepare_message_send 409s while this is set).
    pending = t.pending_tool_approval
    return {
        "thread_id": t.thread_id,
        "project": t.project,
        "investigation_id": t.investigation_id,
        "title": t.title,
        "claimed_by_user_id": t.claimed_by_user_id,
        "created_at": t.created_at.isoformat(),
        "updated_at": (t.updated_at or t.created_at).isoformat(),
        "pending_tools": pending.get("pending_tools", []) if pending else [],
    }


def _notification_out(failure_event, resolved_thread_id: str | None) -> dict:
    return {
        "investigation_id": failure_event.investigation_id,
        "project": failure_event.project,
        "pipeline_name": failure_event.pipeline_name,
        "seed_message": failure_event.seed_message,
        "resolved": resolved_thread_id is not None,
        "resolved_thread_id": resolved_thread_id,
        "seen_at": failure_event.seen_at.isoformat() if failure_event.seen_at else None,
        "created_at": failure_event.created_at.isoformat(),
    }


@router.get("/notifications")
async def list_notifications(
    request: Request, project: str, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        notifications = await service.list_notifications(db, user_id, project)
        return {"notifications": [_notification_out(*n) for n in notifications]}


@router.post("/notifications/{investigation_id}/seen")
async def mark_notification_seen(
    request: Request, investigation_id: str, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        notification = await service.mark_notification_seen(
            db, user_id, investigation_id
        )
        return {"notification": _notification_out(*notification)}


@router.get("/notifications/{investigation_id}")
async def get_notification(
    request: Request, investigation_id: str, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        notification = await service.get_notification(db, user_id, investigation_id)
        if notification is None:
            return {"notification": None}
        return {"notification": _notification_out(*notification)}


@router.get("/threads")
async def list_threads(
    request: Request, project: str, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        threads = await service.list_threads(db, user_id, project)
        return {
            "threads": [
                {**_thread_out(t), "last_message": (last or "")[:200] or None}
                for t, last in threads
            ]
        }


@router.post("/threads")
async def create_thread(
    request: Request,
    body: CreateThreadRequest,
    user_id: str = Depends(get_current_user_id),
):
    async with request.app.state.db_factory() as db:
        thread = await service.create_ad_hoc_thread(
            db, user_id, body.project, body.investigation_id
        )
        return _thread_out(thread)


@router.get("/threads/{thread_id}")
async def get_thread(
    request: Request,
    thread_id: str,
    before_id: int | None = None,
    limit: int = 30,
    user_id: str = Depends(get_current_user_id),
):
    async with request.app.state.db_factory() as db:
        thread, messages, has_more = await service.get_thread_with_messages(
            db, user_id, thread_id, before_id, limit
        )
        return {
            "thread": _thread_out(thread),
            "messages": [_message_out(m) for m in messages],
            "has_more": has_more,
        }


@router.get("/threads/{thread_id}/stats")
async def get_thread_stats(
    request: Request, thread_id: str, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        return await service.get_thread_stats(db, user_id, thread_id)


@router.post("/threads/{thread_id}/claim")
async def claim_thread(
    request: Request, thread_id: str, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        thread = await service.claim_thread(db, user_id, thread_id)
        return _thread_out(thread)


@router.patch("/threads/{thread_id}")
async def rename_thread(
    request: Request,
    thread_id: str,
    body: RenameThreadRequest,
    user_id: str = Depends(get_current_user_id),
):
    async with request.app.state.db_factory() as db:
        thread = await service.rename_thread(db, user_id, thread_id, body.title)
        return _thread_out(thread)


@router.delete("/threads/{thread_id}")
async def delete_thread(
    request: Request, thread_id: str, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        await service.delete_thread(db, user_id, thread_id)
        return {"deleted": True}


def _sse(event: dict) -> bytes:
    if event.get("type") == "message":
        event = {"type": "message", "message": _message_out(event["message"])}
    return f"data: {json.dumps(event, default=str)}\n\n".encode()


def _sse_response(db: AsyncSession, events: AsyncIterator[dict]) -> StreamingResponse:
    """Streams events as SSE and closes the db session once the stream ends — the session
    outlives this handler, since Starlette reads the stream only after it returns."""

    async def body():
        try:
            async for event in events:
                yield _sse(event)
        finally:
            await db.close()

    return StreamingResponse(body(), media_type="text/event-stream")


@router.post("/threads/{thread_id}/messages/stream")
async def post_message_stream(
    request: Request,
    thread_id: str,
    body: MessageRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Sends a message and streams the reply: token and tool_call events as they happen, then
    the persisted message (or a pending tool approval). The checks run before the stream
    opens, so a bad request still gets a normal HTTP error."""
    db = request.app.state.db_factory()
    try:
        thread, state, history = await service.prepare_message_send(
            db, user_id, thread_id, body.content
        )
    except Exception:
        await db.close()
        raise
    return _sse_response(
        db,
        service.stream_message_reply(
            db,
            request.app.state.db_factory,
            thread,
            state,
            history,
            body.content,
            user_id,
        ),
    )


@router.post("/threads/{thread_id}/tool-approvals/resolve/stream")
async def resolve_tool_approval_stream(
    request: Request,
    thread_id: str,
    body: ToolApprovalResolveRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Approves or denies the pending tool call and streams the rest of the turn, like
    post_message_stream."""
    db = request.app.state.db_factory()
    try:
        thread, state, pending = await service.prepare_tool_approval_resolution(
            db, user_id, thread_id, body.decision, body.rejection_message
        )
    except Exception:
        await db.close()
        raise
    return _sse_response(
        db,
        service.stream_approval_reply(
            db,
            request.app.state.db_factory,
            thread,
            state,
            pending,
            body.decision,
            body.tool_call_id,
            body.rejection_message,
            user_id,
        ),
    )


@router.post("/threads/{thread_id}/stop")
async def stop_chat_stream(
    request: Request, thread_id: str, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        return {"cancelled": await service.stop_turn(db, user_id, thread_id)}


@router.post("/messages/{message_id}/feedback")
async def set_message_feedback(
    request: Request,
    message_id: int,
    body: FeedbackRequest,
    user_id: str = Depends(get_current_user_id),
):
    async with request.app.state.db_factory() as db:
        await service.set_message_feedback(db, user_id, message_id, body.rating)
    return {"status": "ok"}


@router.delete("/messages/{message_id}/feedback")
async def delete_message_feedback(
    request: Request, message_id: int, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        await service.set_message_feedback(db, user_id, message_id, None)
    return {"status": "ok"}


@router.get("/memory")
async def list_memory(
    request: Request, project: str, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        return await memory.list_memory(db, user_id, project)


@router.post("/memory")
async def add_memory_fact(
    request: Request,
    body: MemoryFactRequest,
    user_id: str = Depends(get_current_user_id),
):
    async with request.app.state.db_factory() as db:
        fact = await memory.add_fact(db, user_id, body.project, body.kind, body.text)
        return memory.fact_out(fact)


@router.post("/memory/plan")
async def plan_memory_changes(
    request: Request,
    body: MemoryPlanRequest,
    user_id: str = Depends(get_current_user_id),
):
    async with request.app.state.db_factory() as db:
        changes = await memory.plan_memory_changes(
            db, user_id, body.project, body.instruction
        )
    return {"changes": changes}


@router.patch("/memory/{fact_id}")
async def update_memory_fact(
    request: Request,
    fact_id: int,
    body: MemoryFactUpdate,
    user_id: str = Depends(get_current_user_id),
):
    async with request.app.state.db_factory() as db:
        fact = await memory.update_fact(
            db, user_id, fact_id, body.kind, body.text, body.status
        )
        return memory.fact_out(fact)


@router.patch("/memory/patterns/{pattern_id}")
async def update_failure_pattern(
    request: Request,
    pattern_id: int,
    body: PatternStatusUpdate,
    user_id: str = Depends(get_current_user_id),
):
    async with request.app.state.db_factory() as db:
        await memory.update_pattern_status(db, user_id, pattern_id, body.status)
    return {"status": "ok"}


@router.post("/memory/sop")
async def upload_sop(
    request: Request,
    project: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    user_id: str = Depends(get_current_user_id),
):
    # One byte past the limit is enough to reject a file as too big.
    data = await file.read(MAX_SOP_BYTES + 1)
    async with request.app.state.db_factory() as db:
        document = await memory.upload_sop(
            db, user_id, project, file.filename or "", data
        )
        return memory.sop_out(document)


@router.get("/admin/overview")
async def admin_overview(request: Request, user_id: str = Depends(get_current_user_id)):
    async with request.app.state.db_factory() as db:
        return await admin.get_overview(db, user_id)


@router.get("/admin/project")
async def admin_project(
    request: Request, project: str, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        return await admin.get_project(db, user_id, project)


@router.get("/admin/users")
async def admin_users(
    request: Request, q: str | None = None, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        return await admin.list_users(db, user_id, q)


@router.get("/admin/users/{target_id}")
async def admin_user(
    request: Request, target_id: str, user_id: str = Depends(get_current_user_id)
):
    async with request.app.state.db_factory() as db:
        return await admin.get_user(db, user_id, target_id)
