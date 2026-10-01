"""
The admin dashboard's reads (GET /chat/admin/*): usage, cost, chats, notifications, approvals,
feedback and knowledge across every project, by project and by user. Gated only by
require_admin — an admin sees every project, member or not. Plain aggregate queries; daily
buckets are made in Python (UTC) so the same code runs on Postgres and the SQLite tests.

Usage comes from chat_analytics (one row per LLM call, llm/client.py::add_usage). A "chat" is a
non-deleted ChatThread, and a user's chats are the ones they claimed. A notification is a
FailureEvent with a seed message; it's resolved once a ChatThread has its investigation_id.
"""

import statistics
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from chat.access import project_members, require_admin
from chat.memory import list_memory
from db.models import (
    AuditLog,
    ChatAnalytics,
    ChatMessage,
    ChatThread,
    FailureEvent,
    FailurePattern,
    MessageFeedback,
    ProjectMemory,
    ProjectMetadata,
    RBACPermission,
    SopDocument,
)
from llm.memory.tools import RBAC_PLATFORM as RADAR_PLATFORM

_DAYS = 30
_TOP = 10
_RECENT_NOTIFICATIONS = 15
_MAX_USERS = 200
_MAX_USER_CHATS = 100

_TOKENS = ChatAnalytics.input_tokens + ChatAnalytics.output_tokens
_LIVE = ChatThread.is_deleted.is_(False)
_NOTIFICATION = FailureEvent.seed_message.isnot(None)
# RADAR's own tools don't go through the gateway; their audit rows name the tool by event.
_RADAR_TOOL_EVENTS = {
    "failure_patterns_lookup": "get_failure_patterns",
    "failure_pattern_approved": "propose_failure_pattern",
    "memory_approved": "propose_memory",
}


def _utc(dt: datetime | None) -> datetime | None:
    """SQLite hands timestamps back naive; they're stored in UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _iso(dt: datetime | None) -> str | None:
    return _utc(dt).isoformat() if dt else None


async def _integrations(db: AsyncSession) -> dict[str, str]:
    """Projects with a live WatchTower integration → its platform (Service.name)."""
    result = await db.execute(
        text(
            'SELECT c."projectName", s.name FROM public."Credential" c '
            'JOIN public."Service" s ON s.id = c."serviceId" WHERE NOT c."isDeleted"'
        )
    )
    return dict(result.all())


async def _users(db: AsyncSession, q: str | None = None) -> dict[str, dict]:
    query = 'SELECT id, name, email, "isAdmin" FROM public."User"'
    params = {}
    if q:
        query += " WHERE lower(name) LIKE :q OR lower(email) LIKE :q"
        params["q"] = f"%{q.lower()}%"
    result = await db.execute(text(query), params)
    return {
        str(uid): {
            "user_id": str(uid),
            "name": name,
            "email": email,
            "is_admin": bool(admin),
        }
        for uid, name, email, admin in result
    }


async def _usage_by(db: AsyncSession, key, *where) -> dict:
    """key → (tokens, cost, last call) from chat_analytics."""
    result = await db.execute(
        select(
            key,
            func.coalesce(func.sum(_TOKENS), 0),
            func.coalesce(func.sum(ChatAnalytics.estimated_cost), 0.0),
            func.max(ChatAnalytics.created_at),
        )
        .where(*where)
        .group_by(key)
    )
    return {k: (int(tokens), float(cost), last) for k, tokens, cost, last in result}


async def _count_by(db: AsyncSession, key, *where) -> dict:
    result = await db.execute(select(key, func.count()).where(*where).group_by(key))
    return {k: int(n) for k, n in result}


async def _totals(db: AsyncSession, thread_where: list, usage_where: list) -> dict:
    tokens, input_tokens, output_tokens, cached, cost = (
        await db.execute(
            select(
                func.coalesce(func.sum(_TOKENS), 0),
                func.coalesce(func.sum(ChatAnalytics.input_tokens), 0),
                func.coalesce(func.sum(ChatAnalytics.output_tokens), 0),
                func.coalesce(func.sum(ChatAnalytics.cached_tokens), 0),
                func.coalesce(func.sum(ChatAnalytics.estimated_cost), 0.0),
            ).where(*usage_where)
        )
    ).one()
    chats = await db.scalar(
        select(func.count()).select_from(ChatThread).where(_LIVE, *thread_where)
    )
    messages = await db.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .join(ChatThread, ChatThread.thread_id == ChatMessage.thread_id)
        .where(_LIVE, *thread_where)
    )
    return {
        "tokens": int(tokens),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cached_tokens": int(cached),
        "cost": float(cost),
        "chats": int(chats),
        "messages": int(messages),
    }


async def _by_day(
    db: AsyncSession, thread_where: list, usage_where: list
) -> list[dict]:
    """The last 30 days, one entry per UTC day that has usage or new chats."""
    since = datetime.now(UTC) - timedelta(days=_DAYS)
    days = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "chats": 0})
    usage = await db.execute(
        select(ChatAnalytics.created_at, _TOKENS, ChatAnalytics.estimated_cost).where(
            ChatAnalytics.created_at >= since, *usage_where
        )
    )
    for created_at, tokens, cost in usage:
        day = days[_utc(created_at).date()]
        day["tokens"] += int(tokens)
        day["cost"] += float(cost)
    threads = await db.execute(
        select(ChatThread.created_at).where(
            _LIVE, ChatThread.created_at >= since, *thread_where
        )
    )
    for (created_at,) in threads:
        days[_utc(created_at).date()]["chats"] += 1
    return [
        {"date": day.isoformat(), **values, "cost": round(values["cost"], 6)}
        for day, values in sorted(days.items())
    ]


async def _by_purpose(db: AsyncSession, *where) -> list[dict]:
    usage = await _usage_by(db, ChatAnalytics.purpose, *where)
    return [
        {"purpose": purpose, "tokens": tokens, "cost": cost}
        for purpose, (tokens, cost, _) in sorted(usage.items(), key=lambda u: -u[1][1])
    ]


async def _notification_counts(db: AsyncSession, *where) -> dict[str, tuple[int, int]]:
    """project → (received, resolved)."""
    result = await db.execute(
        select(
            FailureEvent.project,
            func.count(),
            func.count(ChatThread.thread_id),
        )
        .outerjoin(
            ChatThread, ChatThread.investigation_id == FailureEvent.investigation_id
        )
        .where(_NOTIFICATION, *where)
        .group_by(FailureEvent.project)
    )
    return {project: (int(n), int(resolved)) for project, n, resolved in result}


def _notification_totals(counts: dict[str, tuple[int, int]]) -> dict:
    received = sum(n for n, _ in counts.values())
    resolved = sum(r for _, r in counts.values())
    return {"received": received, "resolved": resolved, "open": received - resolved}


async def _tools(db: AsyncSession, *where) -> tuple[dict, list[dict]]:
    """Approval counts and the most-called tools, from audit_log. A gateway call is an
    approval when its tool requires consent; RADAR's own tools count the same way."""
    calls = Counter()
    gateway_tool = AuditLog.detail["tool"].as_string()
    gateway = await db.execute(
        select(AuditLog.platform, gateway_tool, func.count())
        .where(AuditLog.event_type == "rbac_tool_call_allowed", *where)
        .group_by(AuditLog.platform, gateway_tool)
    )
    for platform, tool, n in gateway:
        calls[(platform, tool)] += int(n)
    radar = await db.execute(
        select(AuditLog.event_type, func.count())
        .where(AuditLog.event_type.in_(_RADAR_TOOL_EVENTS), *where)
        .group_by(AuditLog.event_type)
    )
    for event_type, n in radar:
        calls[(RADAR_PLATFORM, _RADAR_TOOL_EVENTS[event_type])] += int(n)

    consent = {
        tuple(row)
        for row in (
            await db.execute(
                select(RBACPermission.platform, RBACPermission.tool_name).where(
                    RBACPermission.requires_consent.is_(True)
                )
            )
        ).all()
    }
    outcomes = dict(
        (
            await db.execute(
                select(AuditLog.event_type, func.count())
                .where(
                    AuditLog.event_type.in_(
                        (
                            "tool_approval_denied",
                            "tool_approval_denied_revoked",
                            "tool_approval_expired",
                        )
                    ),
                    *where,
                )
                .group_by(AuditLog.event_type)
            )
        ).all()
    )
    approvals = {
        "approved": sum(n for key, n in calls.items() if key in consent),
        "denied": outcomes.get("tool_approval_denied", 0)
        + outcomes.get("tool_approval_denied_revoked", 0),
        "expired": outcomes.get("tool_approval_expired", 0),
    }
    by_tool = Counter()
    for (_, tool), n in calls.items():
        by_tool[tool] += n
    top = [{"tool": tool, "calls": n} for tool, n in by_tool.most_common(_TOP)]
    return approvals, top


async def _feedback(db: AsyncSession, *thread_where) -> dict:
    result = await db.execute(
        select(MessageFeedback.rating, func.count())
        .join(ChatMessage, ChatMessage.id == MessageFeedback.message_id)
        .join(ChatThread, ChatThread.thread_id == ChatMessage.thread_id)
        .where(*thread_where)
        .group_by(MessageFeedback.rating)
    )
    counts = dict(result.all())
    return {"up": counts.get("up", 0), "down": counts.get("down", 0)}


async def _chats(db: AsyncSession, *where, limit: int | None = None) -> list[dict]:
    """Threads, newest activity first, each with its latest user message, message count and
    usage."""
    latest = (
        select(func.max(ChatMessage.id))
        .where(ChatMessage.role == "user")
        .group_by(ChatMessage.thread_id)
    )
    message_counts = (
        select(ChatMessage.thread_id, func.count().label("n"))
        .group_by(ChatMessage.thread_id)
        .subquery()
    )
    result = await db.execute(
        select(ChatThread, ChatMessage.content, message_counts.c.n)
        .outerjoin(
            ChatMessage,
            (ChatMessage.thread_id == ChatThread.thread_id)
            & ChatMessage.id.in_(latest),
        )
        .outerjoin(message_counts, message_counts.c.thread_id == ChatThread.thread_id)
        .where(_LIVE, *where)
        .order_by(func.coalesce(ChatThread.updated_at, ChatThread.created_at).desc())
        .limit(limit)
    )
    rows = result.all()
    usage = await _usage_by(
        db,
        ChatAnalytics.thread_id,
        ChatAnalytics.thread_id.in_([t.thread_id for t, _, _ in rows]),
    )
    chats = []
    for thread, last, messages in rows:
        tokens, cost, _ = usage.get(thread.thread_id, (0, 0.0, None))
        chats.append(
            {
                "thread_id": thread.thread_id,
                "project": thread.project,
                "title": thread.title,
                "last_message": (last or "")[:200] or None,
                "claimed_by_user_id": thread.claimed_by_user_id,
                "updated_at": _iso(thread.updated_at or thread.created_at),
                "messages": int(messages or 0),
                "tokens": tokens,
                "cost": cost,
                "investigation_id": thread.investigation_id,
            }
        )
    return chats


def _latest(*dts: datetime | None) -> str | None:
    found = [_utc(dt) for dt in dts if dt]
    return max(found).isoformat() if found else None


async def get_overview(db: AsyncSession, user_id: str) -> dict:
    await require_admin(db, user_id)
    totals = await _totals(db, [], [])
    users = await _users(db)

    distinct = (
        await db.execute(
            select(
                func.count(func.distinct(ChatAnalytics.project)),
                func.count(func.distinct(ChatAnalytics.user_id)),
            )
        )
    ).one()

    notification_counts = await _notification_counts(db)
    opened = await db.execute(
        select(FailureEvent.created_at, ChatThread.created_at)
        .join(ChatThread, ChatThread.investigation_id == FailureEvent.investigation_id)
        .where(_NOTIFICATION)
    )
    minutes = [
        (_utc(thread_at) - _utc(event_at)).total_seconds() / 60
        for event_at, thread_at in opened
    ]
    approvals, top_tools = await _tools(db)

    user_usage = await _usage_by(
        db, ChatAnalytics.user_id, ChatAnalytics.user_id.isnot(None)
    )
    user_chats = await _count_by(db, ChatThread.claimed_by_user_id, _LIVE)
    top_users = [
        {
            "user_id": uid,
            "name": users.get(uid, {}).get("name"),
            "email": users.get(uid, {}).get("email"),
            "tokens": tokens,
            "cost": cost,
            "chats": user_chats.get(uid, 0),
        }
        for uid, (tokens, cost, _) in sorted(
            user_usage.items(), key=lambda u: -u[1][1]
        )[:_TOP]
    ]

    facts = await _count_by(
        db, ProjectMemory.project, ProjectMemory.status != "retired"
    )
    patterns = await _count_by(
        db, FailurePattern.project, FailurePattern.status != "retired"
    )
    pattern_statuses = await _count_by(db, FailurePattern.status)
    with_sop = set(
        (
            await db.execute(
                select(SopDocument.project).where(SopDocument.status == "active")
            )
        ).scalars()
    )

    integrations = await _integrations(db)
    metadata = dict(
        (await db.execute(select(ProjectMetadata.project, ProjectMetadata.platform)))
        .tuples()
        .all()
    )
    project_usage = await _usage_by(db, ChatAnalytics.project)
    project_chats = await _count_by(db, ChatThread.project, _LIVE)
    last_failure = dict(
        (
            await db.execute(
                select(
                    FailureEvent.project, func.max(FailureEvent.created_at)
                ).group_by(FailureEvent.project)
            )
        ).all()
    )
    projects = []
    for project in integrations.keys() | metadata.keys():
        tokens, cost, last_call = project_usage.get(project, (0, 0.0, None))
        received, resolved = notification_counts.get(project, (0, 0))
        projects.append(
            {
                "project": project,
                "platform": metadata.get(project) or integrations.get(project),
                "members": len(await project_members(db, project)),
                "tokens": tokens,
                "cost": cost,
                "chats": project_chats.get(project, 0),
                "open_notifications": received - resolved,
                "has_sop": project in with_sop,
                "facts": facts.get(project, 0),
                "patterns": patterns.get(project, 0),
                "last_activity": _latest(last_call, last_failure.get(project)),
            }
        )
    projects.sort(key=lambda p: (-p["cost"], p["project"]))

    return {
        "totals": {
            "tokens": totals["tokens"],
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
            "cached_tokens": totals["cached_tokens"],
            "cost": totals["cost"],
            "chats": totals["chats"],
            "messages": totals["messages"],
            "active_projects": int(distinct[0]),
            "active_users": int(distinct[1]),
        },
        "by_day": await _by_day(db, [], []),
        "by_purpose": await _by_purpose(db),
        "notifications": {
            **_notification_totals(notification_counts),
            "median_minutes_to_open": round(statistics.median(minutes), 1)
            if minutes
            else None,
        },
        "approvals": approvals,
        "feedback": await _feedback(db),
        "top_tools": top_tools,
        "top_users": top_users,
        "knowledge": {
            "projects_with_sop": len(with_sop),
            "facts": sum(facts.values()),
            "patterns_active": pattern_statuses.get("active", 0),
            "patterns_proposed": pattern_statuses.get("proposed", 0),
        },
        "projects": projects,
    }


async def get_project(db: AsyncSession, user_id: str, project: str) -> dict:
    await require_admin(db, user_id)
    integrations = await _integrations(db)
    metadata = await db.get(ProjectMetadata, project)
    if metadata is None and project not in integrations:
        raise HTTPException(status_code=404, detail=f"No project '{project}'")

    thread_where = [ChatThread.project == project]
    usage_where = [ChatAnalytics.project == project]
    totals = await _totals(db, thread_where, usage_where)
    users = await _users(db)

    usage = await _usage_by(db, ChatAnalytics.user_id, *usage_where)
    chats_by_user = await _count_by(
        db, ChatThread.claimed_by_user_id, _LIVE, *thread_where
    )
    members = []
    for uid, member in (await project_members(db, project)).items():
        tokens, cost, last_call = usage.get(uid, (0, 0.0, None))
        user = users.get(uid, {})
        members.append(
            {
                "user_id": uid,
                "name": user.get("name"),
                "email": user.get("email"),
                **member,
                "tokens": tokens,
                "cost": cost,
                "chats": chats_by_user.get(uid, 0),
                "last_active": _iso(last_call),
            }
        )
    members.sort(key=lambda m: (-m["cost"], m["name"] or m["email"] or ""))

    recent = await db.execute(
        select(FailureEvent, ChatThread.thread_id)
        .outerjoin(
            ChatThread, ChatThread.investigation_id == FailureEvent.investigation_id
        )
        .where(_NOTIFICATION, FailureEvent.project == project)
        .order_by(FailureEvent.created_at.desc())
        .limit(_RECENT_NOTIFICATIONS)
    )
    approvals, top_tools = await _tools(db, AuditLog.project == project)

    chats = []
    for chat in await _chats(db, *thread_where):
        claimant = chat.pop("claimed_by_user_id")
        del chat["project"]
        chats.append(
            {
                **chat,
                "claimed_by": {
                    "id": claimant,
                    "name": users.get(claimant, {}).get("name"),
                }
                if claimant
                else None,
            }
        )

    return {
        "project": project,
        "platform": (metadata and metadata.platform) or integrations.get(project),
        "totals": {k: totals[k] for k in ("tokens", "cost", "chats", "messages")},
        "by_day": await _by_day(db, thread_where, usage_where),
        "by_purpose": await _by_purpose(db, *usage_where),
        "members": members,
        "notifications": {
            **_notification_totals(
                await _notification_counts(db, FailureEvent.project == project)
            ),
            "recent": [
                {
                    "investigation_id": event.investigation_id,
                    "pipeline_name": event.pipeline_name,
                    "created_at": _iso(event.created_at),
                    "resolved": thread_id is not None,
                    "thread_id": thread_id,
                }
                for event, thread_id in recent
            ],
        },
        "approvals": approvals,
        "feedback": await _feedback(db, *thread_where),
        "top_tools": top_tools,
        "chats": chats,
        "memory": await list_memory(db, user_id, project),
    }


async def _memberships(db: AsyncSession) -> dict[str, dict[str, dict]]:
    """user id → {project: membership}, over projects with a live integration."""
    by_user = defaultdict(dict)
    for project in sorted(await _integrations(db)):
        for uid, member in (await project_members(db, project)).items():
            by_user[uid][project] = member
    return by_user


async def list_users(db: AsyncSession, user_id: str, q: str | None) -> dict:
    await require_admin(db, user_id)
    users = await _users(db, q)
    memberships = await _memberships(db)
    usage = await _usage_by(
        db, ChatAnalytics.user_id, ChatAnalytics.user_id.isnot(None)
    )
    chats = await _count_by(db, ChatThread.claimed_by_user_id, _LIVE)
    rows = []
    for uid, user in users.items():
        tokens, cost, last_call = usage.get(uid, (0, 0.0, None))
        rows.append(
            {
                **user,
                "projects": sorted(memberships.get(uid, {})),
                "tokens": tokens,
                "cost": cost,
                "chats": chats.get(uid, 0),
                "last_active": _iso(last_call),
            }
        )
    rows.sort(key=lambda u: (-u["cost"], u["name"] or u["email"] or ""))
    return {"users": rows[:_MAX_USERS]}


async def get_user(db: AsyncSession, user_id: str, target_id: str) -> dict:
    await require_admin(db, user_id)
    try:
        uuid.UUID(target_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="user_id must be a UUID") from exc
    user = (await _users(db)).get(target_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"No user {target_id}")

    thread_where = [ChatThread.claimed_by_user_id == target_id]
    usage_where = [ChatAnalytics.user_id == target_id]
    totals = await _totals(db, thread_where, usage_where)
    usage = await _usage_by(db, ChatAnalytics.project, *usage_where)
    chats_by_project = await _count_by(db, ChatThread.project, _LIVE, *thread_where)
    allocations = []
    for project, member in sorted((await _memberships(db)).get(target_id, {}).items()):
        tokens, cost, last_call = usage.get(project, (0, 0.0, None))
        allocations.append(
            {
                "project": project,
                **member,
                "tokens": tokens,
                "cost": cost,
                "chats": chats_by_project.get(project, 0),
                "last_active": _iso(last_call),
            }
        )

    used_threads = select(ChatAnalytics.thread_id).where(*usage_where)
    chats = await _chats(
        db,
        or_(*thread_where, ChatThread.thread_id.in_(used_threads)),
        limit=_MAX_USER_CHATS,
    )
    return {
        "user": user,
        "totals": {k: totals[k] for k in ("tokens", "cost", "chats", "messages")},
        "by_day": await _by_day(db, thread_where, usage_where),
        "allocations": allocations,
        "chats": [
            {
                k: chat[k]
                for k in (
                    "thread_id",
                    "project",
                    "title",
                    "last_message",
                    "updated_at",
                    "messages",
                    "tokens",
                    "cost",
                )
            }
            for chat in chats
        ],
    }
