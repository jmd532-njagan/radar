"""
App-level access control for chat endpoints. Postgres does not enforce access control here,
so every endpoint must call one of these two functions itself.

Keyed on the verified X-Radar-Assertion JWT's `id` claim (WatchTower's own public.User.id),
not email — id is the stable, authoritative identity for authorization decisions.

Reads WatchTower's own public."UserProjectAssignment" directly — same cross-schema source as
thread_setup.py's recipient lookup.
"""

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ChatThread


async def require_project_access(db: AsyncSession, user_id: str, project: str) -> None:
    """Read access: either an explicit UserProjectAssignment row, or admin — an admin reads
    every project the same way any of its own assigned members would (this only grants read;
    write stays claim-gated in service.py exactly the same for admins as anyone else)."""
    result = await db.execute(
        text(
            'SELECT 1 FROM public."UserProjectAssignment" '
            'WHERE "userId" = :user_id AND "projectName" = :project '
            "UNION "
            'SELECT 1 FROM public."User" WHERE id = :user_id AND "isAdmin" = true'
        ),
        {"user_id": user_id, "project": project},
    )
    if result.first() is None:
        raise HTTPException(status_code=403, detail=f"No access to project '{project}'")


async def require_thread_access(
    db: AsyncSession, user_id: str, thread: ChatThread
) -> None:
    """Read access — any project member, or admin (view-only across every project). Write
    access (claim-gated, and additionally requiring real membership — see
    require_real_project_membership) is checked separately, inline in service.py's
    post_message/claim/rename/delete/approve/deny, since it depends on claim state that read
    access alone doesn't capture."""
    await require_project_access(db, user_id, thread.project)


async def require_real_project_membership(
    db: AsyncSession, user_id: str, project: str
) -> None:
    """Stricter than require_project_access: an explicit UserProjectAssignment row only, no
    admin bypass. Required before any write action (send a message, create a thread, claim,
    rename, delete, approve/deny) — an admin can view every project's chats via the bypass
    above, but can't create or write in one they aren't actually assigned to, same as anyone
    else would be blocked."""
    result = await db.execute(
        text(
            'SELECT 1 FROM public."UserProjectAssignment" '
            'WHERE "userId" = :user_id AND "projectName" = :project'
        ),
        {"user_id": user_id, "project": project},
    )
    if result.first() is None:
        raise HTTPException(status_code=403, detail=f"No access to project '{project}'")


async def require_admin(db: AsyncSession, user_id: str) -> None:
    """Cross-project access, deliberately independent of UserProjectAssignment — an admin sees
    every project's data, not just ones they're individually assigned to monitor."""
    result = await db.execute(
        text('SELECT 1 FROM public."User" WHERE id = :user_id AND "isAdmin" = true'),
        {"user_id": user_id},
    )
    if result.first() is None:
        raise HTTPException(status_code=403, detail="Admin access required")
