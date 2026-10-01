"""
Business logic behind every chat endpoint — router.py is a thin translation layer over this.
"""

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chat.access import (
    is_project_member,
    require_project_access,
    require_real_project_membership,
)
from chat.summarization import maybe_summarize
from config.settings import APPROVAL_TTL, NOTIFICATION_LIST_LIMIT
from db.models import (
    AuditLog,
    ChatAnalytics,
    ChatMessage,
    ChatThread,
    FailureEvent,
    MessageFeedback,
    RBACPermission,
)
from db.projects import ensure_project_metadata
from gateway.credential_resolution import get_adf_credential
from llm import agent as chat_agent
from llm.client import add_usage
from llm.investigation_state import build_chat_state
from llm.memory.tools import RBAC_PLATFORM as MEMORY_RBAC_PLATFORM

logger = logging.getLogger(__name__)


# ChatMessage.content is NOT NULL; the Agents SDK's final_output can legitimately come back
# None/empty (e.g. a turn whose last step produced only non-text output) — this is what gets
# persisted instead, rather than raising past a request that already succeeded from the model's
# point of view.
_EMPTY_REPLY_FALLBACK = "(no response text was generated for this turn)"


async def _get_thread_or_404(db: AsyncSession, thread_id: str) -> ChatThread:
    thread = await db.get(ChatThread, thread_id)
    if thread is None or thread.is_deleted:
        raise HTTPException(status_code=404, detail=f"No chat thread {thread_id}")
    return thread


async def _readable_thread(
    db: AsyncSession, user_id: str, thread_id: str
) -> ChatThread:
    """Read access: a project member, or an admin (view-only across every project)."""
    thread = await _get_thread_or_404(db, thread_id)
    await require_project_access(db, user_id, thread.project)
    return thread


async def _writable_thread(
    db: AsyncSession, user_id: str, thread_id: str
) -> ChatThread:
    """Write access: real project members only — an admin can read but not act. Claim state
    is checked separately where it applies."""
    thread = await _get_thread_or_404(db, thread_id)
    await require_real_project_membership(db, user_id, thread.project)
    return thread


async def set_message_feedback(
    db: AsyncSession, user_id: str, message_id: int, rating: str | None
) -> None:
    """Thumbs up/down on an assistant message; `rating=None` removes the caller's own
    feedback (the frontend's toggle-off, the DELETE endpoint)."""
    message = await db.get(ChatMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail=f"No message {message_id}")
    await _writable_thread(db, user_id, message.thread_id)

    existing = await db.execute(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message_id, MessageFeedback.user_id == user_id
        )
    )
    row = existing.scalar_one_or_none()

    if rating is None:
        if row is not None:
            await db.delete(row)
            await db.commit()
        return

    now = datetime.now(UTC)
    if row is not None:
        row.rating = rating
        row.updated_at = now
    else:
        db.add(
            MessageFeedback(
                message_id=message_id, user_id=user_id, rating=rating, created_at=now
            )
        )
    await db.commit()


async def list_notifications(
    db: AsyncSession, user_id: str, project: str
) -> list[tuple[FailureEvent, str | None]]:
    """Every notification for this project, newest first — both still-pending and already-
    resolved (the frontend renders resolved ones differently, e.g. a checkmark, rather than
    dropping them). Capped at NOTIFICATION_LIST_LIMIT; this is a recent-activity list, not a
    paginated archive. Each comes with the thread created from it, if any (it's resolved)."""
    await require_project_access(db, user_id, project)
    result = await db.execute(
        select(FailureEvent, ChatThread.thread_id)
        .outerjoin(
            ChatThread, ChatThread.investigation_id == FailureEvent.investigation_id
        )
        .where(FailureEvent.project == project, FailureEvent.seed_message.isnot(None))
        .order_by(FailureEvent.created_at.desc())
        .limit(NOTIFICATION_LIST_LIMIT)
    )
    return [(event, thread_id) for event, thread_id in result.all()]


async def _resolved_thread_id(db: AsyncSession, investigation_id: str) -> str | None:
    return await db.scalar(
        select(ChatThread.thread_id).where(
            ChatThread.investigation_id == investigation_id
        )
    )


async def mark_notification_seen(
    db: AsyncSession, user_id: str, investigation_id: str
) -> tuple[FailureEvent, str | None]:
    """Called when a specific notification's row is clicked in the list — not when the list
    itself is merely opened, so unclicked rows stay "new" even after being glanced at.
    Idempotent: a second click is a no-op, doesn't bump seen_at to a later time. Only a
    project member's click counts — a view-only admin opening it doesn't mark it seen for the
    team."""
    failure_event = await db.get(FailureEvent, investigation_id)
    if failure_event is None or failure_event.seed_message is None:
        raise HTTPException(
            status_code=404, detail=f"No notification {investigation_id}"
        )
    await require_project_access(db, user_id, failure_event.project)
    if failure_event.seen_at is None and await is_project_member(
        db, user_id, failure_event.project
    ):
        failure_event.seen_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(failure_event)
    return failure_event, await _resolved_thread_id(db, investigation_id)


async def get_notification(
    db: AsyncSession, user_id: str, investigation_id: str
) -> tuple[FailureEvent, str | None] | None:
    """One notification by investigation_id, for the draft chat page opened via
    `?notification=<investigation_id>` (e.g. from the email link, which can be clicked again
    later). Returned even once resolved — the thread created from it tells the frontend to
    redirect there instead of showing an empty draft. None if it doesn't exist."""
    failure_event = await db.get(FailureEvent, investigation_id)
    if failure_event is None or failure_event.seed_message is None:
        return None
    await require_project_access(db, user_id, failure_event.project)
    return failure_event, await _resolved_thread_id(db, investigation_id)


async def list_threads(
    db: AsyncSession, user_id: str, project: str
) -> list[tuple[ChatThread, str | None]]:
    """The project's threads, most recently active first, each with its latest user message
    (the project page's chat list shows it under the title)."""
    await require_project_access(db, user_id, project)
    latest = (
        select(func.max(ChatMessage.id).label("id"))
        .where(ChatMessage.role == "user")
        .group_by(ChatMessage.thread_id)
        .subquery()
    )
    result = await db.execute(
        select(ChatThread, ChatMessage.content)
        .outerjoin(
            ChatMessage,
            (ChatMessage.thread_id == ChatThread.thread_id)
            & ChatMessage.id.in_(select(latest.c.id)),
        )
        .where(ChatThread.project == project, ChatThread.is_deleted.is_(False))
        .order_by(func.coalesce(ChatThread.updated_at, ChatThread.created_at).desc())
    )
    return [(thread, content) for thread, content in result.all()]


async def create_ad_hoc_thread(
    db: AsyncSession,
    user_id: str,
    project: str,
    investigation_id: str | None = None,
) -> ChatThread:
    """investigation_id is set when this thread is being created FROM a pending notification
    (the user clicked the bell, then sent the suggested message or typed their own on that same
    draft page) — mirrors an ordinary ad-hoc thread's lazy creation exactly, just also linking
    the thread to the originating FailureEvent (chat_threads.investigation_id), which is what
    stops the notification showing as pending. A stale/already-resolved/mismatched-project investigation_id is
    silently ignored rather than erroring — the thread still gets created either way, just
    without the link, since the user's message shouldn't be blocked by a notification that
    someone else already claimed or that no longer exists. Creating a thread is a write
    action — requires real project membership, not just the admin view-only bypass.

    The project must have a live ADF integration in WatchTower; its ProjectMetadata row is
    created here on first use, so a freshly integrated project needs no manual seeding."""
    await require_real_project_membership(db, user_id, project)
    if await get_adf_credential(db, project) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{project}' has no ADF integration in WatchTower",
        )
    await ensure_project_metadata(db, project, "adf")

    failure_event = None
    if investigation_id is not None:
        candidate = await db.get(FailureEvent, investigation_id)
        if (
            candidate is not None
            and candidate.project == project
            and await _resolved_thread_id(db, investigation_id) is None
        ):
            failure_event = candidate

    thread = ChatThread(
        project=project,
        investigation_id=failure_event.investigation_id if failure_event else None,
        created_at=datetime.now(UTC),
    )
    db.add(thread)

    if failure_event is not None:
        # Sending a message from a notification necessarily means it was already looked at —
        # resolving without having seen it first isn't a real path, so stamp both together
        # rather than leaving seen_at to a separate, easy-to-skip mark-as-seen call.
        if failure_event.seen_at is None:
            failure_event.seen_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(thread)
    return thread


async def get_thread_with_messages(
    db: AsyncSession,
    user_id: str,
    thread_id: str,
    before_id: int | None,
    limit: int,
) -> tuple[ChatThread, list[ChatMessage], bool]:
    """Cursor-paginated scrollback, newest page first — the initial call (before_id=None)
    returns the most recent `limit` messages, and infinite scroll asks for the page before
    whatever the oldest currently-loaded message's id is. Always returns oldest-first within
    the page (the order a chat transcript actually renders in), even though the query itself
    has to walk backwards (ORDER BY id DESC) to select "the `limit` messages right before this
    cursor" — reversed once in Python, not pushed onto Postgres.

    Third return value (has_more) is True when a full page came back, meaning there may be
    another (older) page beyond it — the frontend uses this to decide whether to keep showing
    a "load more" trigger at the top of the scroll area or stop.
    """
    thread = await _readable_thread(db, user_id, thread_id)

    query = select(ChatMessage).where(ChatMessage.thread_id == thread_id)
    if before_id is not None:
        query = query.where(ChatMessage.id < before_id)
    query = query.order_by(ChatMessage.id.desc()).limit(limit)

    result = await db.execute(query)
    page = list(result.scalars().all())
    page.reverse()
    return thread, page, len(page) == limit


async def get_thread_stats(db: AsyncSession, user_id: str, thread_id: str) -> dict:
    """Backs the sidebar's per-thread "Info" popup — token usage summed across every
    ChatAnalytics row for this thread (real usage, same source as _persist_turn_result writes,
    not the char-based estimate used for the UI's live token_count display), plus when the
    originating notification actually arrived (FailureEvent.created_at) if this thread came
    from one. Author/created_at aren't computed here — the caller already has those on the
    Thread object it fetched to open this popup in the first place, no need to duplicate."""
    thread = await _readable_thread(db, user_id, thread_id)

    result = await db.execute(
        select(
            func.coalesce(func.sum(ChatAnalytics.input_tokens), 0),
            func.coalesce(func.sum(ChatAnalytics.output_tokens), 0),
        ).where(ChatAnalytics.thread_id == thread_id)
    )
    input_tokens, output_tokens = result.one()

    notification_created_at = None
    if thread.investigation_id:
        failure_event = await db.get(FailureEvent, thread.investigation_id)
        if failure_event is not None:
            notification_created_at = failure_event.created_at

    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(input_tokens) + int(output_tokens),
        "notification_created_at": notification_created_at,
    }


async def _claim(db: AsyncSession, thread: ChatThread, user_id: str) -> bool:
    """Claims an unclaimed thread for user_id — atomically, so of two users racing only one
    wins. True if user_id holds the claim afterwards."""
    if thread.claimed_by_user_id is None:
        await db.execute(
            update(ChatThread)
            .where(
                ChatThread.thread_id == thread.thread_id,
                ChatThread.claimed_by_user_id.is_(None),
            )
            .values(claimed_by_user_id=user_id)
        )
        await db.commit()
        await db.refresh(thread)
    return thread.claimed_by_user_id == user_id


async def claim_thread(db: AsyncSession, user_id: str, thread_id: str) -> ChatThread:
    thread = await _writable_thread(db, user_id, thread_id)
    if not await _claim(db, thread, user_id):
        raise HTTPException(
            status_code=409,
            detail=f"Already claimed by another user ({thread.claimed_by_user_id})",
        )
    return thread


def _require_claimant_or_unclaimed(thread: ChatThread, user_id: str) -> None:
    """Write access for rename/delete: an unclaimed thread has no owner yet, so any project
    member may still act on it."""
    if thread.claimed_by_user_id is not None and thread.claimed_by_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail=f"Thread claimed by another user ({thread.claimed_by_user_id}), not writable by you",
        )


async def rename_thread(
    db: AsyncSession, user_id: str, thread_id: str, title: str
) -> ChatThread:
    thread = await _writable_thread(db, user_id, thread_id)
    _require_claimant_or_unclaimed(thread, user_id)
    thread.title = title[:60]
    await db.commit()
    await db.refresh(thread)
    return thread


async def delete_thread(db: AsyncSession, user_id: str, thread_id: str) -> None:
    thread = await _writable_thread(db, user_id, thread_id)
    _require_claimant_or_unclaimed(thread, user_id)
    thread.is_deleted = True
    await db.commit()


async def stop_turn(db: AsyncSession, user_id: str, thread_id: str) -> bool:
    """Cancels a turn streaming for this thread (a real mid-generation interrupt). Only the
    claimant — whose turn it is — can stop it."""
    thread = await _writable_thread(db, user_id, thread_id)
    if thread.claimed_by_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail=f"Only the claimant ({thread.claimed_by_user_id}) can stop this thread's turn",
        )
    logger.info("Turn stopped by user: thread=%s user=%s", thread_id, user_id)
    return chat_agent.cancel_chat_stream(thread_id)


async def _persist_turn_result(
    db: AsyncSession,
    thread: ChatThread,
    turn_result: chat_agent.ChatTurnResult,
    triggering_message: str,
    user_id: str | None,
    state: dict,
) -> ChatMessage | None:
    """Persists a finished turn as the assistant's ChatMessage and returns it, or — for a turn
    paused on a tool approval — stores the paused state in thread.pending_tool_approval and
    returns None. `triggering_message` is the message that started the turn (not necessarily
    the latest on a resumed turn), used to name the thread once the turn completes."""
    if turn_result.kind == "pending_approval":
        thread.pending_tool_approval = {
            **turn_result.run_state_json,
            "pending_tools": turn_result.pending_tools,
            "triggering_message": turn_result.triggering_message,
            # Carried into resume_chat_turn so the whole turn's trace and thinking time survive
            # into the final message (token usage travels inside the RunState itself).
            "tool_calls": turn_result.tool_calls,
            "thought_seconds": turn_result.thought_seconds,
            "created_at": datetime.now(UTC).isoformat(),
        }
        await db.commit()
        logger.info(
            "Turn paused for approval: thread=%s tools=%s",
            thread.thread_id,
            [t["tool_name"] for t in turn_result.pending_tools or []],
        )
        return None

    thread.pending_tool_approval = None
    tool_calls_out: dict | None = None
    if turn_result.tool_calls or turn_result.thought_seconds is not None:
        tool_calls_out = {
            "tools_called": turn_result.tool_calls or [],
            "thought_seconds": turn_result.thought_seconds,
        }
    assistant_message = ChatMessage(
        thread_id=thread.thread_id,
        role="assistant",
        content=turn_result.reply_text or _EMPTY_REPLY_FALLBACK,
        tool_calls=tool_calls_out,
        created_at=datetime.now(UTC),
    )
    db.add(assistant_message)

    usage_fields = {
        "project": state["project"],
        "platform": state["platform"],
        "user_id": user_id,
        "thread_id": thread.thread_id,
    }
    if thread.title is None:
        thread.title, title_usage = await chat_agent.generate_chat_title(
            triggering_message, turn_result.reply_text or ""
        )
        if title_usage:
            add_usage(db, title_usage, purpose="title", **usage_fields)

    add_usage(
        db,
        {
            "input_tokens": turn_result.input_tokens,
            "output_tokens": turn_result.output_tokens,
            "cached_tokens": turn_result.cached_tokens,
        },
        purpose="chat",
        **usage_fields,
    )

    await db.commit()
    await db.refresh(assistant_message)
    logger.info(
        "Turn done: thread=%s project=%s tools=%s tokens in=%s cached=%s out=%s",
        thread.thread_id,
        state["project"],
        [f"{t['name']}:{t['status']}" for t in turn_result.tool_calls or []],
        turn_result.input_tokens,
        turn_result.cached_tokens,
        turn_result.output_tokens,
    )
    return assistant_message


async def _revoked_pending_tools(
    db: AsyncSession, platform: str, pending_tool_names: set[str]
) -> list[str]:
    """Returns the subset of pending_tool_names whose rbac_permissions row is no longer
    allowed=True (revoked while the approval sat pending) — defense in depth alongside
    gateway/rbac.py's own live check at dispatch."""
    if not pending_tool_names:
        return []
    result = await db.execute(
        select(RBACPermission).where(
            RBACPermission.platform.in_((platform, MEMORY_RBAC_PLATFORM)),
            RBACPermission.tool_name.in_(pending_tool_names),
        )
    )
    rows = {row.tool_name: row for row in result.scalars().all()}
    return [
        name
        for name in pending_tool_names
        if (row := rows.get(name)) is None or not row.allowed
    ]


async def prepare_message_send(
    db: AsyncSession, user_id: str, thread_id: str, content: str
) -> tuple[ChatThread, dict, list[dict]]:
    """Every check and write that must happen before the agent runs — separate from the
    stream so a bad request still gets a normal HTTP error (an exception raised once the SSE
    response has started can't become one). Returns the thread, the chat state and the
    history to replay."""
    thread = await _writable_thread(db, user_id, thread_id)
    if not await _claim(db, thread, user_id):
        raise HTTPException(
            status_code=403,
            detail=f"Thread claimed by another user ({thread.claimed_by_user_id}), not writable by you",
        )
    if thread.pending_tool_approval is not None:
        raise HTTPException(
            status_code=409,
            detail="This thread has a pending tool approval — resolve it before sending a "
            "new message",
        )

    user_message = ChatMessage(
        thread_id=thread_id,
        role="user",
        content=content,
        created_at=datetime.now(UTC),
    )
    db.add(user_message)
    # Bumps the thread to the top of list_threads' ordering.
    thread.updated_at = datetime.now(UTC)
    await db.commit()

    state = await build_chat_state(db, thread)

    # Only messages after the summary cursor are replayed; older turns live in the summary.
    history_query = select(ChatMessage).where(
        ChatMessage.thread_id == thread_id, ChatMessage.id != user_message.id
    )
    if thread.summarized_through_timestamp is not None:
        history_query = history_query.where(
            ChatMessage.created_at > thread.summarized_through_timestamp
        )
    history_result = await db.execute(history_query.order_by(ChatMessage.id))
    # Only user/assistant text is replayed, never tool-call items: the model needs what was
    # said, not what was looked up, and hand-rebuilt tool items are fragile across SDK
    # versions. The summary of older turns is in the system prompt (state["summary"]).
    history = [
        {"role": m.role, "content": m.content}
        for m in history_result.scalars()
        if m.role in ("user", "assistant")
    ]
    return thread, state, history


async def prepare_tool_approval_resolution(
    db: AsyncSession,
    user_id: str,
    thread_id: str,
    decision: str,
    rejection_message: str | None,
) -> tuple[ChatThread, dict, dict]:
    """The approve/deny counterpart of prepare_message_send. An approval older than
    APPROVAL_TTL is auto-denied and answered with 410."""
    thread = await _writable_thread(db, user_id, thread_id)
    if thread.claimed_by_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail=f"Only the claimant ({thread.claimed_by_user_id}) can resolve a pending tool approval",
        )
    if thread.pending_tool_approval is None:
        raise HTTPException(
            status_code=409, detail="No tool approval is pending on this thread"
        )

    # Atomically claim (and clear) the pending approval before doing anything else. Without
    # this, a concurrent duplicate resolve request (double-click, network retry, second tab)
    # would also see pending_tool_approval as non-None, and both would independently resume +
    # execute the approved tool, e.g. triggering the same pipeline rerun multiple times.
    #
    # Uses a row lock, not UPDATE...RETURNING: RETURNING reflects the value after the update
    # (always NULL here), so it can't distinguish "just cleared this" from "was already NULL".
    locked = await db.execute(
        select(ChatThread.pending_tool_approval)
        .where(ChatThread.thread_id == thread_id)
        .with_for_update()
    )
    pending = locked.scalar_one_or_none()
    if pending is None:
        await db.commit()
        raise HTTPException(
            status_code=409, detail="This tool approval was already resolved"
        )
    await db.execute(
        update(ChatThread)
        .where(ChatThread.thread_id == thread_id)
        .values(pending_tool_approval=None)
    )
    await db.commit()

    pending_tools = pending.get("pending_tools", [])
    state = await build_chat_state(db, thread)

    def audit(event_type: str, detail: dict) -> None:
        logger.info("Approval %s: thread=%s user=%s", event_type, thread_id, user_id)
        db.add(
            AuditLog(
                investigation_id=thread.investigation_id,
                thread_id=thread.thread_id,
                pipeline_name=state["pipeline_name"],
                project=state["project"],
                platform=state["platform"],
                event_type=event_type,
                user_id=user_id,
                detail=detail,
            )
        )

    if datetime.now(UTC) - datetime.fromisoformat(pending["created_at"]) > APPROVAL_TTL:
        audit("tool_approval_expired", {"pending_tools": pending_tools})
        await db.commit()
        raise HTTPException(
            status_code=410,
            detail="Pending approval expired (90-minute TTL) and was auto-denied.",
        )

    revoked = await _revoked_pending_tools(
        db, state["platform"], {t["tool_name"] for t in pending_tools}
    )
    if revoked:
        audit("tool_approval_denied_revoked", {"revoked_tools": revoked})
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail=f"Tool(s) no longer allowed, cannot proceed: {revoked}",
        )

    if decision == "deny":
        # A rejected tool never reaches gateway/rbac.py (the SDK short-circuits before the
        # tool runs), so this is the only audit record of the denial.
        audit(
            "tool_approval_denied",
            {"pending_tools": pending_tools, "rejection_message": rejection_message},
        )
        await db.commit()
    else:
        logger.info(
            "Approval granted: thread=%s user=%s tools=%s",
            thread_id,
            user_id,
            [t["tool_name"] for t in pending_tools],
        )

    return thread, state, pending


async def _stream_and_persist(
    db: AsyncSession,
    thread: ChatThread,
    agent_stream: AsyncIterator[dict],
    triggering_message: str,
    user_id: str,
    state: dict,
) -> AsyncIterator[dict]:
    """Forwards the agent's token/tool_call events as they arrive, persists its terminal
    result, and ends with {"type": "message"} (turn finished or stopped) or
    {"type": "pending_approval"} (paused on a tool approval)."""
    turn_result = None
    async for event in agent_stream:
        if event["type"] in ("token", "tool_call"):
            yield event
        else:
            turn_result = event["result"]

    message = await _persist_turn_result(
        db, thread, turn_result, triggering_message, user_id=user_id, state=state
    )
    if message is None:
        yield {"type": "pending_approval", "pending_tools": turn_result.pending_tools}
    else:
        await maybe_summarize(db, thread, user_id, state["platform"])
        yield {"type": "message", "message": message}


def stream_message_reply(
    db: AsyncSession,
    db_factory: async_sessionmaker,
    thread: ChatThread,
    state: dict,
    history: list[dict],
    content: str,
    user_id: str,
) -> AsyncIterator[dict]:
    agent_stream = chat_agent.stream_chat_turn(
        state, db_factory, history, content, user_id=user_id, thread_id=thread.thread_id
    )
    return _stream_and_persist(db, thread, agent_stream, content, user_id, state)


def stream_approval_reply(
    db: AsyncSession,
    db_factory: async_sessionmaker,
    thread: ChatThread,
    state: dict,
    pending: dict,
    decision: str,
    tool_call_id: str | None,
    rejection_message: str | None,
    user_id: str,
) -> AsyncIterator[dict]:
    agent_stream = chat_agent.resume_chat_turn(
        state,
        db_factory,
        pending,
        decision,
        tool_call_id,
        rejection_message,
        user_id=user_id,
        thread_id=thread.thread_id,
    )
    return _stream_and_persist(
        db, thread, agent_stream, pending["triggering_message"], user_id, state
    )
