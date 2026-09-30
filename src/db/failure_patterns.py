"""
Failure-pattern data access — plain queries, no LLM concepts.

A pattern is matched by the parsed signature's `identity` within a project. Occurrences are the
failure_events rows that point at a pattern, so counts, "last seen" and "last fixed" are derived
here rather than stored.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import FailureEvent, FailurePattern
from intake.signature import Signature

# The vocabulary for FailurePattern.category, shown to the agent in propose_failure_pattern
# so categories stay consistent (always "timeout", never "Timeout"); other values are dropped.
CATEGORIES: list[str] = [
    "oom",
    "timeout",
    "credential_expired",
    "permissions",  # service principal lacks RBAC rights (not expired, just missing)
    "network",
    "data_quality",
    "schema_drift",
    "resource_unavailable",
    "storage_access",
    "rate_limit",
    "config",
    "platform_outage",
    "business_logic",  # application-level failures (bad params, assertion errors)
    "cancelled",  # pipeline was cancelled (user/system/dependency)
    "unknown",
]


async def match_or_create(
    db: AsyncSession, project: str, sig: Signature, pipeline: str
) -> tuple[FailurePattern, str]:
    """The project's pattern for this signature, creating a `proposed` one on first sight so the
    next occurrence matches even before anyone has diagnosed it. Returns (pattern, matched_by)
    with matched_by = "code" | "fingerprint" | "new". Does not commit."""
    created = await db.execute(
        pg_insert(FailurePattern)
        .values(
            project=project,
            identity=sig.identity,
            platform=sig.platform,
            code=sig.code,
            error_type=sig.error_type,
            template=sig.template,
            pipelines=[pipeline],
        )
        .on_conflict_do_nothing(index_elements=["project", "identity"])
        .returning(FailurePattern.id)
    )
    new_id = created.scalar_one_or_none()
    pattern = (
        await db.execute(
            select(FailurePattern).where(
                FailurePattern.project == project,
                FailurePattern.identity == sig.identity,
            )
        )
    ).scalar_one()
    if new_id is not None:
        return pattern, "new"
    if pipeline not in pattern.pipelines:
        pattern.pipelines = [*pattern.pipelines, pipeline]
    return pattern, "fingerprint" if sig.is_generic else "code"


@dataclass(frozen=True)
class PatternHistory:
    seen_before: int
    last_seen: datetime | None
    last_fixed: datetime | None


async def histories(
    db: AsyncSession,
    pattern_ids: list[int],
    exclude_investigation_id: str | None = None,
) -> dict[int, PatternHistory]:
    """Occurrence history for several patterns in one query, optionally leaving out the
    current failure. Patterns with no occurrences get an empty history."""
    empty = PatternHistory(0, None, None)
    if not pattern_ids:
        return {}
    query = (
        select(
            FailureEvent.pattern_id,
            func.count(),
            func.max(FailureEvent.created_at),
            func.max(FailureEvent.created_at).filter(FailureEvent.outcome == "fixed"),
        )
        .where(FailureEvent.pattern_id.in_(pattern_ids))
        .group_by(FailureEvent.pattern_id)
    )
    if exclude_investigation_id:
        query = query.where(FailureEvent.investigation_id != exclude_investigation_id)
    found = {row[0]: PatternHistory(*row[1:]) for row in await db.execute(query)}
    return {pid: found.get(pid, empty) for pid in pattern_ids}


async def history(
    db: AsyncSession, pattern_id: int, exclude_investigation_id: str | None = None
) -> PatternHistory:
    return (await histories(db, [pattern_id], exclude_investigation_id))[pattern_id]


async def for_pipeline(
    db: AsyncSession, project: str, pipeline: str | None, limit: int = 5
) -> list[FailurePattern]:
    """Non-retired patterns seen on a pipeline (or, with no pipeline, across the project),
    active first, then most recently created. A project has tens of patterns, so the pipeline
    filter runs in Python."""
    rows = (
        await db.execute(
            select(FailurePattern)
            .where(
                FailurePattern.project == project, FailurePattern.status != "retired"
            )
            .order_by(FailurePattern.created_at.desc())
        )
    ).scalars()
    matching = [p for p in rows if not pipeline or pipeline in p.pipelines]
    matching.sort(key=lambda p: p.status != "active")
    return matching[:limit]


def apply_update(
    pattern: FailurePattern,
    *,
    approved_by: str | None,
    cause: str | None = None,
    category: str | None = None,
    verify_with: list[str] | None = None,
    fix_actions: list[str] | None = None,
) -> dict:
    """Applies a human-approved update to a pattern (only the fields given), activates it, and
    returns the before/after of what changed for the audit log."""
    changes = {}
    for field, value in (
        ("cause", cause),
        ("category", category),
        ("verify_with", verify_with),
        ("fix_actions", fix_actions),
    ):
        if value is not None and getattr(pattern, field) != value:
            changes[field] = {"before": getattr(pattern, field), "after": value}
            setattr(pattern, field, value)
    now = datetime.now(UTC)
    pattern.status = "active"
    pattern.approved_by, pattern.approved_at, pattern.updated_at = approved_by, now, now
    return changes
