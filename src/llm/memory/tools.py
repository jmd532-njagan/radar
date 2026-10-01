"""
The project-memory tools every platform gets — thin @function_tool wrappers around
db/failure_patterns.py and db/project_memory.py:

  - get_failure_patterns: what the project already knows about a pipeline's failures (read).
  - propose_failure_pattern: the agent's diagnosis for this failure's pattern.
  - propose_memory: a lasting fact about the project the human mentioned.

Both propose tools pause for the human's approval (needs_approval comes from their
rbac_permissions rows, like any gated tool) and run only once approved, so nothing becomes
project knowledge without a person agreeing. Not routed through gateway.rbac.call_tool: they
touch only RADAR's own tables. Every call writes an AuditLog row, which is also the change
history of patterns and facts.
"""

import json

from agents import function_tool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from db import failure_patterns, project_memory
from db.models import AuditLog, FailureEvent, FailurePattern, RBACPermission
from llm.investigation_state import InvestigationState

_GATED = ("propose_failure_pattern", "propose_memory")
# rbac_permissions.platform for RADAR's own tools (the ADF tools use "adf").
RBAC_PLATFORM = "radar"


def _compact(pattern: FailurePattern, past: failure_patterns.PatternHistory) -> dict:
    return {
        "pattern": f"FP-{pattern.id}",
        "status": pattern.status,
        "code": pattern.code,
        "error_type": pattern.error_type,
        "template": pattern.template,
        "category": pattern.category,
        "cause": pattern.cause,
        "verify_with": pattern.verify_with,
        "fix_actions": pattern.fix_actions,
        "seen": past.seen_before,
        "last_seen": past.last_seen.isoformat() if past.last_seen else None,
        "last_fixed": past.last_fixed.isoformat() if past.last_fixed else None,
    }


async def build_memory_tools(
    state: InvestigationState, db_factory: async_sessionmaker, user_id: str | None
) -> list:

    def audit(event_type: str, detail: dict) -> AuditLog:
        return AuditLog(
            investigation_id=state["investigation_id"],
            thread_id=state["thread_id"],
            pipeline_name=state["pipeline_name"],
            project=state["project"],
            platform=state["platform"],
            event_type=event_type,
            user_id=user_id,
            detail=detail,
        )

    async def get_failure_patterns(pipeline: str | None = None) -> str:
        """What this project already knows about a pipeline's failures: each known failure
        pattern with its likely cause, how to verify it, the usual fix, and how often it has
        occurred. Treat it as leads to confirm with live tools, not as established fact.

        Args:
            pipeline: The pipeline to look up. Defaults to this chat's failed pipeline; in an
                open-ended chat, pass the pipeline the user is asking about.
        """
        resolved = pipeline or state["pipeline_name"]
        async with db_factory() as db:
            patterns = await failure_patterns.for_pipeline(
                db, state["project"], resolved
            )
            pasts = await failure_patterns.histories(db, [p.id for p in patterns])
            payload = [_compact(p, pasts[p.id]) for p in patterns]
            db.add(
                audit(
                    "failure_patterns_lookup",
                    {"pipeline": resolved, "patterns": [p["pattern"] for p in payload]},
                )
            )
            await db.commit()
        return json.dumps(
            payload or "No failure patterns recorded for this pipeline yet."
        )

    async def propose_failure_pattern(
        cause: str,
        category: str,
        verify_with: list[str],
        fix_actions: list[str],
        outcome: str,
        reason: str,
    ) -> str:
        """Save your diagnosis to this failure's pattern so future failures like it start from
        what you learned. The human sees the proposal and approves or rejects it; it's saved only
        if approved. Call it once you have a real diagnosis (tentative is fine), and again if
        your understanding changes.

        Args:
            cause: the root cause in one sentence, at most ~20 words.
            category: one of {categories}.
            verify_with: tool names that confirm this cause, e.g. ["get_dataset_definition"].
            fix_actions: short action tags that fixed or would fix it, e.g.
                ["update_copy_mapping", "rerun_pipeline"].
            outcome: fixed | not_fixed | unknown — how this failure ended.
            reason: one line on why you believe this, shown to the human when approving.
        """
        pattern_id = state["pattern_id"]
        if pattern_id is None:
            return "This chat isn't tied to a failure with a pattern, so there's nothing to update."
        async with db_factory() as db:
            changes = failure_patterns.apply_update(
                await db.get(FailurePattern, pattern_id),
                approved_by=user_id,
                cause=cause,
                category=category if category in failure_patterns.CATEGORIES else None,
                verify_with=verify_with,
                fix_actions=fix_actions,
            )
            (await db.get(FailureEvent, state["investigation_id"])).outcome = outcome
            db.add(
                audit(
                    "failure_pattern_approved",
                    {
                        "pattern": f"FP-{pattern_id}",
                        "changes": changes,
                        "outcome": outcome,
                        "reason": reason,
                    },
                )
            )
            await db.commit()
        return f"FP-{pattern_id} updated and active."

    async def propose_memory(kind: str, text: str, reason: str) -> str:
        """Save a lasting fact about this project to its memory, which every future chat in the
        project sees. Use it when the human states something that stays true (an environment
        detail, a schedule, a dependency, a contact, a rule) — not for this failure's diagnosis
        (that's propose_failure_pattern). The human approves it before it's saved.

        Args:
            kind: one of {kinds}.
            text: the fact in one short sentence.
            reason: one line on where this came from, shown to the human when approving.
        """
        if kind not in project_memory.KINDS:
            return f"kind must be one of: {', '.join(project_memory.KINDS)}"
        async with db_factory() as db:
            fact = project_memory.create(
                db, state["project"], kind, text, "incident", user_id
            )
            await db.flush()
            db.add(
                audit(
                    "memory_approved",
                    {
                        "fact": fact.id,
                        "kind": kind,
                        "text": fact.text,
                        "reason": reason,
                    },
                )
            )
            await db.commit()
        return "Saved to project memory."

    propose_failure_pattern.__doc__ = propose_failure_pattern.__doc__.format(
        categories=", ".join(failure_patterns.CATEGORIES)
    )
    propose_memory.__doc__ = propose_memory.__doc__.format(
        kinds=", ".join(project_memory.KINDS)
    )
    async with db_factory() as db:
        consent = dict(
            (
                await db.execute(
                    select(
                        RBACPermission.tool_name, RBACPermission.requires_consent
                    ).where(
                        RBACPermission.platform == RBAC_PLATFORM,
                        RBACPermission.tool_name.in_(_GATED),
                    )
                )
            ).all()
        )
    return [
        function_tool(get_failure_patterns),
        *(
            function_tool(tool, needs_approval=consent.get(tool.__name__, True))
            for tool in (propose_failure_pattern, propose_memory)
        ),
    ]
