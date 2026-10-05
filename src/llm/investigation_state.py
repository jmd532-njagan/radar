"""
InvestigationState — everything a chat turn needs, rebuilt from DB rows every turn (cheap,
indexed lookups). The only code that builds it.

Besides the failure itself it carries what RADAR already knows, loaded in code so the agent
starts from it rather than having to ask: the project's active memory facts, the failure
pattern this failure matched (with its history), the SOP sections most relevant to this failure,
and the summary of the earlier conversation.
"""

from datetime import datetime
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import SOP_RESULTS_AT_FAILURE_START
from db import failure_patterns, project_memory
from db.models import ChatThread, FailureEvent, FailurePattern, ProjectMetadata
from gateway.credential_resolution import get_adf_credential
from intake.signature import summarize
from llm.injection_detection import drop_flagged
from llm.sop.search import search as search_sop

# Sentinel pipeline_name for ad-hoc threads — gateway/rbac.py's call_tool and AuditLog both
# require a non-null pipeline name, and a project-scoped conversation has no pipeline of its own.
AD_HOC_PIPELINE_SENTINEL = "(ad-hoc)"


class InvestigationState(TypedDict):
    investigation_id: str | None
    thread_id: str | None  # passed to call_tool/AuditLog for every call
    project: str
    platform: str
    pipeline_name: str
    run_status: str
    start_time: datetime
    # Parsed from the failure's signature (intake/signature.py).
    error: str | None
    error_code: str | None
    pattern_id: int | None
    # The failed activity and its run id, so the agent can go straight to the run.
    failed_activity: str | None
    activity_run_id: str | None
    # How the failed run was started (e.g. ScheduleTrigger, Manual), as WatchTower reports it.
    trigger_type: str | None
    # What's already known, loaded in code (see module docstring).
    memory: list[dict]  # active project facts: {"kind", "text"}
    pattern: dict | None  # the matched failure pattern, compact, with its history
    sop: list[dict]  # SOP sections relevant to this failure: {"section", "text"}
    summary: str | None  # summary of earlier turns (chat/summarization.py)
    # Non-secret factory identifiers from the project's WatchTower integration;
    # client_secret is never put in state.
    tenant_id: str | None
    client_id: str | None
    subscription_id: str | None
    resource_group: str | None
    factory_name: str | None


async def _matched_pattern(db: AsyncSession, event: FailureEvent) -> dict | None:
    if event.pattern_id is None:
        return None
    pattern = await db.get(FailurePattern, event.pattern_id)
    past = await failure_patterns.history(db, pattern.id, event.investigation_id)
    return {
        "id": f"FP-{pattern.id}",
        "status": pattern.status,
        "cause": pattern.cause,
        "verify_with": pattern.verify_with,
        "fix_actions": pattern.fix_actions,
        "seen_before": past.seen_before,
        "last_fixed": past.last_fixed,
    }


async def build_chat_state(db: AsyncSession, thread: ChatThread) -> InvestigationState:
    """Failure-triggered threads carry the failure; ad-hoc threads get sentinel values that
    llm/agent.py's prompt builder handles."""
    factory = await get_adf_credential(db, thread.project)
    if factory is None:
        raise RuntimeError(f"No ADF integration found for project='{thread.project}'")

    event = (
        await db.get(FailureEvent, thread.investigation_id)
        if thread.investigation_id
        else None
    )
    sig = event.signature if event else None
    detail = (event.error_detail if event else None) or {}
    platform = (
        event.platform
        if event
        else (
            await db.execute(
                select(ProjectMetadata.platform).where(
                    ProjectMetadata.project == thread.project
                )
            )
        ).scalar_one_or_none()
    )
    facts = await project_memory.list_facts(db, thread.project)
    error = (
        (summarize(sig["template"], sig["values"]) if sig else event.last_error)
        if event
        else None
    )
    failed_activity = detail.get("failed_activity_name")
    sop = (
        await drop_flagged(
            await search_sop(
                db,
                thread.project,
                " ".join(filter(None, [event.pipeline_name, failed_activity, error])),
                k=SOP_RESULTS_AT_FAILURE_START,
                # Added to every prompt unasked, so only when the SOP covers this pipeline;
                # the agent can still search the SOP itself.
                must_mention=event.pipeline_name,
            ),
            source="SOP at failure start",
        )
        if event
        else []
    )

    return {
        "investigation_id": thread.investigation_id,
        "thread_id": thread.thread_id,
        "project": thread.project,
        "platform": platform or "unknown",
        "pipeline_name": event.pipeline_name if event else AD_HOC_PIPELINE_SENTINEL,
        "run_status": event.run_status if event else "n/a",
        "start_time": event.start_time if event else thread.created_at,
        "error": error,
        "error_code": sig["code"] if sig else None,
        "pattern_id": event.pattern_id if event else None,
        "failed_activity": failed_activity,
        "activity_run_id": detail.get("failed_activity_run_id"),
        "trigger_type": event.trigger_type if event else None,
        "memory": [{"kind": f.kind, "text": f.text} for f in facts],
        "pattern": await _matched_pattern(db, event) if event else None,
        "sop": sop,
        "summary": thread.context_summary,
        "tenant_id": factory.tenant_id,
        "client_id": factory.client_id,
        "subscription_id": factory.subscription_id,
        "resource_group": factory.resource_group,
        "factory_name": factory.factory_name,
    }
