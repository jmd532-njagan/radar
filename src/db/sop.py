"""
SOP data access — plain queries, no LLM concepts. See db.models.SopDocument / SopChunk.

A project has at most one `active` SOP. Uploading a new one replaces it: the old document is
kept as `replaced` (its row is the upload history), its chunks are deleted, and what came from
it is retired so the new SOP's extraction doesn't duplicate it: its facts that nobody has edited
since, and its patterns nobody approved. Edited facts and approved patterns stay — a person
worked on them, so they outlive the document they came from.
"""

from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import FailurePattern, ProjectMemory, SopChunk, SopDocument


async def active_document(db: AsyncSession, project: str) -> SopDocument | None:
    return (
        await db.execute(
            select(SopDocument).where(
                SopDocument.project == project, SopDocument.status == "active"
            )
        )
    ).scalar_one_or_none()


async def replace_active(db: AsyncSession, project: str) -> int:
    """Retires the project's active SOP (if any) and returns the version number the next one
    gets. Does not commit."""
    old = await active_document(db, project)
    if old is not None:
        chunk_ids = select(SopChunk.id).where(SopChunk.document_id == old.id)
        now = datetime.now(UTC)
        await db.execute(
            update(ProjectMemory)
            .where(
                ProjectMemory.source_chunk_id.in_(chunk_ids),
                ProjectMemory.status == "active",
                ProjectMemory.updated_at == ProjectMemory.created_at,
            )
            .values(status="retired", updated_at=now)
        )
        await db.execute(
            update(FailurePattern)
            .where(
                FailurePattern.source_chunk_id.in_(chunk_ids),
                FailurePattern.status == "proposed",
            )
            .values(status="retired", updated_at=now)
        )
        await db.execute(delete(SopChunk).where(SopChunk.document_id == old.id))
        old.status = "replaced"
    latest = await db.scalar(
        select(func.max(SopDocument.version)).where(SopDocument.project == project)
    )
    return (latest or 0) + 1


async def chunks(db: AsyncSession, document_id: int) -> list[SopChunk]:
    return list(
        (
            await db.execute(
                select(SopChunk)
                .where(SopChunk.document_id == document_id)
                .order_by(SopChunk.position)
            )
        ).scalars()
    )
