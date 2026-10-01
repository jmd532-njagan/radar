"""
App-level access control for chat endpoints. Postgres does not enforce access control here,
so every endpoint must call one of these functions itself.

The caller is identified by the X-Radar-Assertion header WatchTower's proxy attaches to every
request: a short-lived HS256 JWT signed with RADAR_ASSERTION_SECRET, whose `id` claim is
WatchTower's public.User.id — the identity every check here keys on (never email).

A user is a member of a project if either:
- WatchTower's public."UserProjectAssignment" has a row for them (manual assignment), or
- they're one of the "resources" picked for that project in WatchTower's Integrations tab.
  public."Credential".resources holds JIN employee_ids, which are Azure AD object ids — the
  same id WatchTower saves as public."User"."azureObjectId" at SSO login — so a resource maps
  straight to a WatchTower user id.
"""

import jwt
from fastapi import Header, HTTPException
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings


async def _project_resources(db: AsyncSession, project: str) -> set[str]:
    result = await db.execute(
        text(
            'SELECT resources FROM public."Credential" '
            'WHERE "projectName" = :project AND NOT "isDeleted"'
        ),
        {"project": project},
    )
    return {r for (resources,) in result for r in resources or [] if r}


async def _resource_member_ids(db: AsyncSession, project: str) -> set[str]:
    resources = await _project_resources(db, project)
    if not resources:
        return set()
    result = await db.execute(
        text(
            'SELECT id FROM public."User" WHERE lower("azureObjectId") IN :ids'
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": sorted(r.lower() for r in resources)},
    )
    return {str(uid) for (uid,) in result}


async def is_project_member(db: AsyncSession, user_id: str, project: str) -> bool:
    assigned = await db.execute(
        text(
            'SELECT 1 FROM public."UserProjectAssignment" '
            'WHERE "userId" = :user_id AND "projectName" = :project'
        ),
        {"user_id": user_id, "project": project},
    )
    if assigned.first() is not None:
        return True
    return user_id in await _resource_member_ids(db, project)


async def _is_admin(db: AsyncSession, user_id: str) -> bool:
    result = await db.execute(
        text('SELECT 1 FROM public."User" WHERE id = :user_id AND "isAdmin" = true'),
        {"user_id": user_id},
    )
    return result.first() is not None


async def project_members(db: AsyncSession, project: str) -> dict[str, dict]:
    """Every project member: user id → {"sources": how they're a member ("resource" and/or
    "assigned"), "notify": false only when their assignment has notifyOnFailure off}."""
    result = await db.execute(
        text(
            'SELECT "userId", "notifyOnFailure" FROM public."UserProjectAssignment" '
            'WHERE "projectName" = :project'
        ),
        {"project": project},
    )
    assignments = {str(uid): bool(notify) for uid, notify in result}
    resources = await _resource_member_ids(db, project)
    return {
        uid: {
            "sources": [
                source
                for source, member in (
                    ("resource", uid in resources),
                    ("assigned", uid in assignments),
                )
                if member
            ],
            "notify": assignments.get(uid, True),
        }
        for uid in resources | assignments.keys()
    }


async def notification_recipient_ids(db: AsyncSession, project: str) -> list[str]:
    """Every project member, minus anyone whose manual assignment has notifyOnFailure off."""
    members = await project_members(db, project)
    return sorted(uid for uid, member in members.items() if member["notify"])


async def require_project_access(db: AsyncSession, user_id: str, project: str) -> None:
    """Read access: a project member, or admin — an admin reads every project the same way
    any of its members would (read only; every write also calls
    require_real_project_membership, which has no admin bypass)."""
    if not await is_project_member(db, user_id, project) and not await _is_admin(
        db, user_id
    ):
        raise HTTPException(status_code=403, detail=f"No access to project '{project}'")


async def require_real_project_membership(
    db: AsyncSession, user_id: str, project: str
) -> None:
    """Stricter than require_project_access: project members only, no admin bypass. Required
    before any write action (send a message, create a thread, claim, rename, delete,
    approve/deny a tool call, stop a running turn, message feedback) — an admin can view every
    project's chats, but can't act in one they aren't actually a member of."""
    if not await is_project_member(db, user_id, project):
        raise HTTPException(status_code=403, detail=f"No access to project '{project}'")


async def require_admin(db: AsyncSession, user_id: str) -> None:
    """Cross-project access, deliberately independent of project membership — an admin sees
    every project's data, not just ones they're a member of."""
    if not await _is_admin(db, user_id):
        raise HTTPException(status_code=403, detail="Admin access required")


async def get_current_user_id(
    x_radar_assertion: str | None = Header(default=None, alias="X-Radar-Assertion"),
) -> str:
    if not x_radar_assertion:
        raise HTTPException(status_code=401, detail="Missing X-Radar-Assertion")
    try:
        payload = jwt.decode(
            x_radar_assertion, settings.radar_assertion_secret, algorithms=["HS256"]
        )
    except jwt.InvalidTokenError as err:
        raise HTTPException(
            status_code=401, detail="Invalid or expired X-Radar-Assertion"
        ) from err
    user_id = payload.get("id")
    if not user_id:
        raise HTTPException(
            status_code=401, detail="X-Radar-Assertion missing 'id' claim"
        )
    return user_id
