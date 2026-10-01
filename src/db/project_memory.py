"""
Project memory data access — plain queries, no LLM concepts. See db.models.ProjectMemory.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ProjectMemory

KINDS = (
    "rule",
    "environment",
    "schedule",
    "dependency",
    "contact",
    "verify_after",
    "quirk",
)
STATUSES = ("proposed", "active", "retired")


async def list_facts(
    db: AsyncSession, project: str, statuses: tuple[str, ...] = ("active",)
) -> list[ProjectMemory]:
    """Facts in `statuses`, grouped in KINDS order (rules first), oldest first within a kind."""
    rows = (
        await db.execute(
            select(ProjectMemory)
            .where(ProjectMemory.project == project, ProjectMemory.status.in_(statuses))
            .order_by(ProjectMemory.created_at)
        )
    ).scalars()
    return sorted(
        rows, key=lambda f: KINDS.index(f.kind) if f.kind in KINDS else len(KINDS)
    )


def create(
    db: AsyncSession,
    project: str,
    kind: str,
    text: str,
    origin: str,
    user_id: str | None,
) -> ProjectMemory:
    """An active fact: a person added it, approved the agent's proposal of it, or uploaded the
    SOP it came from. Does not commit."""
    now = datetime.now(UTC)
    fact = ProjectMemory(
        project=project,
        kind=kind,
        text=text.strip(),
        origin=origin,
        status="active",
        created_by=user_id,
        approved_by=user_id,
        approved_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(fact)
    return fact


def update(fact: ProjectMemory, user_id: str | None, **fields: str | None) -> dict:
    """Applies the given fields (kind / text / status) and returns their before/after for the
    audit log. Activating a fact records who approved it. Does not commit."""
    changes = {}
    for field, value in fields.items():
        if value is not None and getattr(fact, field) != value:
            changes[field] = {"before": getattr(fact, field), "after": value}
            setattr(fact, field, value)
    now = datetime.now(UTC)
    if changes.get("status", {}).get("after") == "active":
        fact.approved_by, fact.approved_at = user_id, now
    if changes:
        fact.updated_at = now
    return changes
