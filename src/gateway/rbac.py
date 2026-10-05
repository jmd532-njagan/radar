"""
The gateway every ADF tool call goes through: permission check, audit row, secret enrichment,
dispatch to the tool implementation.
"""

import asyncio
import logging

from azure.core.exceptions import ClientAuthenticationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog, RBACPermission
from gateway.credential_resolution import resolve_client_secret
from llm.investigation_state import InvestigationState
from platform_tools.adf import client_cache, tools as adf_tools

logger = logging.getLogger(__name__)


def infra_params(state: "dict | InvestigationState") -> dict:
    """Extract the non-secret factory identifiers (sourced from Credential) from state."""
    return {
        "tenant_id": state.get("tenant_id"),
        "client_id": state.get("client_id"),
        "subscription_id": state.get("subscription_id"),
        "resource_group": state.get("resource_group"),
        "factory_name": state.get("factory_name"),
    }


async def call_tool(
    db: AsyncSession,
    *,
    tool_name: str,
    arguments: dict,
    user_id: str | None,
    pipeline_id: str,
    project: str,
    platform: str,
    infra_params_dict: dict,
    investigation_id: str | None,
    thread_id: str | None = None,
) -> dict:
    """Runs one tool call for a chat turn. investigation_id is None for ad-hoc threads (no
    FailureEvent); thread_id ties the audit row to the chat the call happened in."""
    # No role dimension — permission is per-tool only (allowed / requires_consent).
    # requires_consent is enforced by the Agents SDK's tool-approval pause before this runs;
    # this check is an independent gate (defense in depth).
    #
    # The query is platform-scoped: two platforms may each have a tool of the same name.
    allowed = await db.scalar(
        select(RBACPermission.allowed).where(
            RBACPermission.tool_name == tool_name, RBACPermission.platform == platform
        )
    )
    # Only the caller-supplied arguments are logged, before the secret is added.
    db.add(
        AuditLog(
            investigation_id=investigation_id,
            thread_id=thread_id,
            pipeline_name=pipeline_id,
            project=project,
            platform=platform,
            event_type="rbac_tool_call_allowed" if allowed else "rbac_tool_call_denied",
            user_id=user_id,
            detail={"tool": tool_name, "arguments": arguments},
        )
    )
    await db.commit()
    if not allowed:
        logger.warning(
            "Tool call denied by RBAC: platform=%s tool=%s thread=%s user=%s",
            platform,
            tool_name,
            thread_id,
            user_id,
        )
        raise PermissionError(f"'{tool_name}' is not an allowed tool")

    # client_secret is resolved fresh on every call (a local AES decrypt, no network I/O);
    # the Azure SDK client itself is cached separately (platform_tools/adf/client_cache.py).
    # The trusted values are spread AFTER arguments: the tool schemas don't declare
    # tenant_id/client_id/.../client_secret, but nothing stops a model emitting one, and it
    # must never override the project identity resolved server-side.
    enriched = {
        **arguments,
        **infra_params_dict,
        "client_secret": await resolve_client_secret(db, project),
    }
    return await _dispatch(tool_name, enriched)


async def _dispatch(tool_name: str, arguments: dict) -> dict:
    fn = adf_tools.TOOL_REGISTRY.get(tool_name)
    if fn is None:
        raise ValueError(f"No tool registered for '{tool_name}'")
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: fn(**arguments)
        )
    except ClientAuthenticationError:
        # The cached client for this identity is no longer valid — evict it so the next call
        # rebuilds fresh. Not retried here: that could mask a genuinely bad secret as a
        # transient hiccup; the model decides whether to try again.
        client_cache.invalidate(
            arguments["tenant_id"],
            arguments["client_id"],
            arguments["client_secret"],
            arguments["subscription_id"],
        )
        raise
