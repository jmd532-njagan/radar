"""
Business logic behind the Project Memory panel: list a project's facts, failure patterns and
SOP; add a fact, edit / approve / retire a fact or pattern; turn a plain-language instruction
into fact changes for the panel to confirm; upload an SOP. Reading follows chat
access (members and admins); changing needs real project membership. Every change writes an
audit_log row with its before/after, which is the item's history.
"""

import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chat.access import require_project_access, require_real_project_membership
from config.settings import MAX_SOP_BYTES, settings
from db import failure_patterns, project_memory, sop
from db.models import (
    AuditLog,
    FailurePattern,
    ProjectMemory,
    ProjectMetadata,
    SopDocument,
)
from llm.client import add_usage, azure_client
from llm.investigation_state import AD_HOC_PIPELINE_SENTINEL
from llm.sop import ingest

# The Project Memory panel's "tell RADAR what to remember or forget" box (plan_memory_changes).
_PLAN_PROMPT = f"""You maintain a data-platform project's memory: short facts an assistant
always knows about the project. Kinds: {", ".join(project_memory.KINDS)}.
The user says, in their own words, what to remember, change or forget. Turn that into changes
to the current facts (given as JSON with ids). Return JSON:
{{"changes": [{{"op": "add", "kind": "...", "text": "..."}},
              {{"op": "update", "id": 12, "kind": "...", "text": "..."}},
              {{"op": "remove", "id": 7}}]}}
Rules: one short, self-contained sentence per fact, in the user's terms; update a fact rather
than adding a near-duplicate; only remove what the user asked to forget; ids must come from the
current facts; no changes if the request isn't about the project's memory."""


def fact_out(fact: ProjectMemory) -> dict:
    return {
        "id": fact.id,
        "kind": fact.kind,
        "text": fact.text,
        "origin": fact.origin,
        "status": fact.status,
        "approved_at": fact.approved_at.isoformat() if fact.approved_at else None,
        "updated_at": (fact.updated_at or fact.created_at).isoformat(),
    }


def sop_out(document: SopDocument | None) -> dict | None:
    if document is None:
        return None
    return {
        "id": document.id,
        "file_name": document.file_name,
        "version": document.version,
        "warnings": document.warnings,
        "uploaded_at": document.uploaded_at.isoformat(),
    }


def _audit(project: str, user_id: str, event_type: str, detail: dict) -> AuditLog:
    return AuditLog(
        project=project,
        pipeline_name=AD_HOC_PIPELINE_SENTINEL,
        platform="radar",
        event_type=event_type,
        user_id=user_id,
        detail=detail,
    )


def _validate(kind: str | None, status: str | None, text: str | None) -> None:
    if kind is not None and kind not in project_memory.KINDS:
        raise HTTPException(
            400, f"kind must be one of: {', '.join(project_memory.KINDS)}"
        )
    if status is not None and status not in project_memory.STATUSES:
        raise HTTPException(
            400, f"status must be one of: {', '.join(project_memory.STATUSES)}"
        )
    if text is not None and not text.strip():
        raise HTTPException(400, "text can't be empty")


async def list_memory(db: AsyncSession, user_id: str, project: str) -> dict:
    await require_project_access(db, user_id, project)
    facts = await project_memory.list_facts(db, project, ("proposed", "active"))
    patterns = await failure_patterns.for_pipeline(db, project, None, limit=100)
    pasts = await failure_patterns.histories(db, [p.id for p in patterns])
    return {
        "facts": [fact_out(f) for f in facts],
        "patterns": [
            {
                "id": f"FP-{p.id}",
                "pattern_id": p.id,
                "status": p.status,
                "code": p.code,
                "template": p.template,
                "category": p.category,
                "cause": p.cause,
                "fix_actions": p.fix_actions,
                "pipelines": p.pipelines,
                "seen": pasts[p.id].seen_before,
                "last_seen": pasts[p.id].last_seen.isoformat()
                if pasts[p.id].last_seen
                else None,
            }
            for p in patterns
        ],
        "sop": sop_out(await sop.active_document(db, project)),
    }


async def add_fact(
    db: AsyncSession, user_id: str, project: str, kind: str, text: str
) -> ProjectMemory:
    await require_real_project_membership(db, user_id, project)
    _validate(kind, None, text)
    fact = project_memory.create(db, project, kind, text, "human", user_id)
    await db.flush()
    db.add(
        _audit(
            project,
            user_id,
            "memory_added",
            {"fact": fact.id, "kind": kind, "text": fact.text},
        )
    )
    await db.commit()
    return fact


async def update_fact(
    db: AsyncSession,
    user_id: str,
    fact_id: int,
    kind: str | None,
    text: str | None,
    status: str | None,
) -> ProjectMemory:
    fact = await db.get(ProjectMemory, fact_id)
    if fact is None:
        raise HTTPException(404, f"No memory fact {fact_id}")
    await require_real_project_membership(db, user_id, fact.project)
    _validate(kind, status, text)
    changes = project_memory.update(
        fact, user_id, kind=kind, text=text.strip() if text else None, status=status
    )
    if changes:
        db.add(
            _audit(
                fact.project,
                user_id,
                "memory_updated",
                {"fact": fact.id, "changes": changes},
            )
        )
        await db.commit()
    return fact


async def plan_memory_changes(
    db: AsyncSession, user_id: str, project: str, instruction: str
) -> list[dict]:
    """What an instruction like "forget the old contact, loads now start at 7" would change,
    as add/update/remove operations on the project's facts. Writes nothing: the panel shows
    them for confirmation, then applies each through add_fact / update_fact. Only the call's
    usage row is written."""
    await require_real_project_membership(db, user_id, project)
    if not instruction.strip():
        raise HTTPException(400, "Say what RADAR should remember or forget")
    facts = {
        f.id: f
        for f in await project_memory.list_facts(db, project, ("proposed", "active"))
    }
    current = [{"id": f.id, "kind": f.kind, "text": f.text} for f in facts.values()]
    response = await azure_client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[
            {"role": "system", "content": _PLAN_PROMPT},
            {
                "role": "user",
                "content": f"Current facts: {json.dumps(current)}\n\nRequest: {instruction}",
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    add_usage(
        db,
        response.usage,
        purpose="memory_plan",
        project=project,
        platform=await db.scalar(
            select(ProjectMetadata.platform).where(ProjectMetadata.project == project)
        )
        or "adf",
        user_id=user_id,
    )
    await db.commit()
    proposed = json.loads(response.choices[0].message.content or "{}").get(
        "changes", []
    )
    changes = []
    for change in proposed if isinstance(proposed, list) else []:
        op, fact = change.get("op"), facts.get(change.get("id"))
        kind, text = change.get("kind"), str(change.get("text") or "").strip()
        if op == "add" and kind in project_memory.KINDS and text:
            changes.append({"op": op, "kind": kind, "text": text})
        elif op == "update" and fact and text:
            changes.append(
                {
                    "op": op,
                    "id": fact.id,
                    "kind": kind if kind in project_memory.KINDS else fact.kind,
                    "text": text,
                    "before": fact.text,
                }
            )
        elif op == "remove" and fact:
            changes.append(
                {"op": op, "id": fact.id, "kind": fact.kind, "text": fact.text}
            )
    return changes


async def update_pattern_status(
    db: AsyncSession, user_id: str, pattern_id: int, status: str
) -> None:
    """Approve (active) or retire a failure pattern — SOP-extracted issues arrive proposed."""
    if status not in ("active", "retired"):
        raise HTTPException(400, "status must be active or retired")
    pattern = await db.get(FailurePattern, pattern_id)
    if pattern is None:
        raise HTTPException(404, f"No failure pattern {pattern_id}")
    await require_real_project_membership(db, user_id, pattern.project)
    if pattern.status == status:
        return
    before = pattern.status
    if status == "active":
        failure_patterns.apply_update(pattern, approved_by=user_id)
    else:
        pattern.status, pattern.updated_at = status, datetime.now(UTC)
    db.add(
        _audit(
            pattern.project,
            user_id,
            "failure_pattern_updated",
            {
                "pattern": f"FP-{pattern_id}",
                "status": {"before": before, "after": status},
            },
        )
    )
    await db.commit()


async def upload_sop(
    db: AsyncSession, user_id: str, project: str, file_name: str, data: bytes
) -> SopDocument:
    await require_real_project_membership(db, user_id, project)
    if not file_name.lower().endswith(".docx"):
        raise HTTPException(400, "Upload the SOP as a .docx file")
    if len(data) > MAX_SOP_BYTES:
        raise HTTPException(413, "SOP files are limited to 10 MB")
    active = await sop.active_document(db, project)
    if active and active.content_hash == ingest.content_hash(data):
        raise HTTPException(409, "This SOP is already the project's current one")
    try:
        document = await ingest.ingest(db, project, file_name, data, user_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.add(
        _audit(
            project,
            user_id,
            "sop_uploaded",
            {
                "document": document.id,
                "file_name": file_name,
                "version": document.version,
            },
        )
    )
    await db.commit()
    return document
