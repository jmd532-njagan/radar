"""
Writes the pending seed message onto the FailureEvent row for a newly received pipeline
failure, called from intake/listener.py right after that row is inserted. Chat is the only
diagnosis path — "Diagnose this failure" is just a suggested first chat message, not a
separate pipeline.

Notification email delivery is WatchTower's responsibility (it already has a working send
path and is what detected the failure in the first place). This function's job ends at
determining who should be notified, which intake/listener.py relays back to WatchTower over
HTTP. The `notification_ready` audit entry records that determination regardless of whether
WatchTower's send actually succeeds.

Recipients are the project's members as chat/access.py defines them (manual
UserProjectAssignment rows plus the resources picked in WatchTower's Integrations tab), read
straight from WatchTower's own tables rather than kept as a separate copy that could drift.

No ChatThread is created here. The seed text lives on FailureEvent.seed_message until a human
sends it (or types something else) from the draft chat page opened via the notification bell,
at which point chat/service.py's create_ad_hoc_thread creates the real ChatThread, linked by
its investigation_id.
"""

import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from chat.access import notification_recipient_ids
from db import failure_patterns
from db.failure_patterns import PatternHistory
from db.models import AuditLog, FailureEvent, FailurePattern
from intake.signature import summarize

logger = logging.getLogger(__name__)


# The seed message is a fixed template, not LLM-generated: fast, predictable, and no model
# call before a human has even opened the chat.
def build_seed_message(
    event: FailureEvent, pattern: FailurePattern | None, past: PatternHistory | None
) -> str:
    sig = event.signature
    error = (
        summarize(sig["template"], sig["values"])
        if sig
        else event.last_error or "no error message"
    )
    failed_at = (event.end_time or event.start_time).strftime("%d %b %H:%M UTC")
    lines = [f"`{event.pipeline_name}` failed at {failed_at}: {error}"]

    if pattern is not None and past is not None and past.seen_before:
        known = (
            f"Matches failure pattern FP-{pattern.id}, seen {past.seen_before}× before"
        )
        if pattern.category and pattern.category != "unknown":
            known += f" ({pattern.category.replace('_', ' ')})"
        if pattern.cause:
            known += f". Known cause: {pattern.cause}"
            if pattern.fix_actions:
                known += f" Usual fix: {', '.join(pattern.fix_actions)}."
        else:
            known += ", no diagnosis recorded yet."
        lines.append(known)
    else:
        lines.append("First time this error has been seen in this project.")

    lines.append("Investigate this failure.")
    return "\n\n".join(lines)


async def prepare_notification(
    db_factory: async_sessionmaker, investigation_id: str
) -> list[str]:
    """Writes the seed message onto the already-inserted FailureEvent (idempotent: re-running
    overwrites the same row's seed_message) and returns the recipient user ids."""
    async with db_factory() as db:
        event = await db.get(FailureEvent, investigation_id)
        recipient_user_ids = await notification_recipient_ids(db, event.project)

        pattern = past = None
        if event.pattern_id is not None:
            pattern = await db.get(FailurePattern, event.pattern_id)
            past = await failure_patterns.history(
                db, event.pattern_id, investigation_id
            )
        event.seed_message = build_seed_message(event, pattern, past)

        db.add(
            AuditLog(
                investigation_id=investigation_id,
                thread_id=None,  # no thread exists yet — nothing to attribute this to
                pipeline_name=event.pipeline_name,
                project=event.project,
                platform=event.platform,
                event_type="notification_ready",
                user_id=None,  # system-originated (WatchTower intake), no real user to attribute to
                detail={"recipient_user_ids": recipient_user_ids},
            )
        )
        await db.commit()

    if not recipient_user_ids:
        logger.warning(
            "No project members to notify for project=%s (no UserProjectAssignment rows "
            "with notifyOnFailure=true and no integration resources matching a WatchTower "
            "user) — WatchTower will have nobody to email. investigation_id=%s",
            event.project,
            investigation_id,
        )

    return recipient_user_ids
