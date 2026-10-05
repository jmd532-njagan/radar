"""
App-level access control for chat endpoints. Postgres does not enforce access control here,
so every endpoint must call one of these functions itself.

The caller is identified by the X-Radar-Assertion header WatchTower's proxy attaches to every
request: a short-lived HS256 JWT signed with RADAR_ASSERTION_SECRET, whose `id` claim is
WatchTower's public.User.id — the identity every check here keys on (never email).

A user is a member of a project if they're one of the people picked for it in WatchTower's
Integrations tab: public."credentialUser" links each integration (public."Credential") to their
JIN employee_id, which is public."User"."jinEmployeeId" (also their Entra object id, saved at
SSO login), and its notifyOnFailure says whether they get RADAR's emails. Credential.resources
holds the same people's names, for display only.
"""

import jwt
from fastapi import Header, HTTPException
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings


async def _project_employee_ids(db: AsyncSession, project: str) -> dict[str, bool]:
    """The JIN employee ids linked to the project's live integrations (credentialUser), each
    with whether they get RADAR's emails — on if any of their links says so."""
    linked = await db.execute(
        text(
            'SELECT cu."employeeId", cu."notifyOnFailure" FROM public."credentialUser" cu '
            'JOIN public."Credential" c ON c.id = cu."credentialId" '
            'WHERE c."projectName" = :project AND NOT c."isDeleted"'
        ),
        {"project": project},
    )
    ids: dict[str, bool] = {}
    for employee_id, notify in linked:
        if employee_id:
            ids[employee_id] = ids.get(employee_id, False) or bool(notify)
    return ids


async def project_members(db: AsyncSession, project: str) -> dict[str, dict]:
    """Every project member: user id → {"notify": whether they get RADAR's emails}."""
    links = {
        e.lower(): n for e, n in (await _project_employee_ids(db, project)).items()
    }
    if not links:
        return {}
    result = await db.execute(
        text(
            'SELECT id, "jinEmployeeId" FROM public."User" WHERE lower("jinEmployeeId") IN :ids'
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": sorted(links)},
    )
    return {str(uid): {"notify": links[emp.lower()]} for uid, emp in result}


async def is_project_member(db: AsyncSession, user_id: str, project: str) -> bool:
    return user_id in await project_members(db, project)


async def _is_admin(db: AsyncSession, user_id: str) -> bool:
    result = await db.execute(
        text('SELECT 1 FROM public."User" WHERE id = :user_id AND "isAdmin" = true'),
        {"user_id": user_id},
    )
    return result.first() is not None


async def notification_recipient_ids(db: AsyncSession, project: str) -> list[str]:
    """Every project member whose credentialUser link has notifyOnFailure on."""
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
