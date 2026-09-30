"""
Tests for platform_tools.adf.tool_search_tool.build_chat_tools — the chat agent's (66-distinct-tool,
retrieval-selected) ADF tool builder. Uses the real rbac_permissions table (via
chat_db_factory) rather than mocking it, since the whole point of this function is being
DB-driven.

Split out of test_chat_tools.py (2026-07-28) when llm/tools.py's ADF-specific half moved to
platform_tools/adf/tool_search_tool.py (named retrieval.py until renamed for consistency with the
OpenAI Agents SDK's own "tool search tool" terminology — this module is still a host-side
keyword pre-filter, not the SDK's model-driven mid-conversation search mechanism) —
llm/tools.py itself is now platform-agnostic (see test_chat_tools.py), so its tests shouldn't
depend on ADF specs/rbac seeding.
"""

import pytest

from db.models import RBACPermission
from llm.embeddings import embed_texts
from platform_tools.adf.schemas import SPECS
from platform_tools.adf.tool_search_tool import (
    build_chat_tools,
    build_keyword_index,
    retrieve_relevant_tools,
)

_STATE = {
    "investigation_id": None,
    "pipeline_name": "orders_pipeline",
    "project": "acme",
    "platform": "adf",
}


async def _asks_approval(tool, **args) -> bool:
    """Whether a call with every required argument (or the given ones) pauses for approval."""
    if not callable(tool.needs_approval):
        return tool.needs_approval
    spec = next(s for s in SPECS if s.name == tool.name)
    args = args or dict.fromkeys(spec.params_json_schema["required"], "x")
    return await tool.needs_approval(None, args, "call_1")


async def _seed_all_rbac_rows(db_factory, overrides: dict[str, bool] | None = None):
    """One rbac_permissions row per tool, keyed by spec.name; creates, updates and run
    actions need consent."""
    overrides = overrides or {}
    consent_required_actions = {
        "rerun_pipeline",
        "cancel_pipeline_run",
        "start_trigger",
        "stop_trigger",
        "rerun_trigger_run",
        "cancel_trigger_run",
        "start_integration_runtime",
    }
    async with db_factory() as db:
        for spec in SPECS:
            allowed = overrides.get(spec.name, True)
            db.add(
                RBACPermission(
                    tool_name=spec.name,
                    allowed=allowed,
                    requires_consent=spec.name.startswith(("create_", "update_"))
                    or spec.name in consent_required_actions,
                )
            )
        await db.commit()


@pytest.mark.asyncio
async def test_disallowed_tool_never_appears_regardless_of_retrieval_score(
    chat_db_factory,
):
    await _seed_all_rbac_rows(
        chat_db_factory, overrides={"update_dataset_definition": False}
    )
    tools = await build_chat_tools(
        _STATE,
        chat_db_factory,
        "please update the orders dataset's definition to fix the schema drift",
        user_id="alice@acme.com",
    )
    names = [t.name for t in tools]
    assert "update_dataset_definition" not in names


@pytest.mark.asyncio
async def test_needs_approval_matches_registry_row_for_a_direct_tool(chat_db_factory):
    await _seed_all_rbac_rows(chat_db_factory)
    tools = await build_chat_tools(
        _STATE,
        chat_db_factory,
        "kill the pipeline run that's stuck",
        user_id="alice@acme.com",
    )
    by_name = {t.name: t for t in tools}

    assert "cancel_pipeline_run" in by_name
    assert await _asks_approval(
        by_name["cancel_pipeline_run"]
    )  # direct entry, requires_consent=True

    assert "list_pipelines" in by_name  # always-include core tool
    assert (
        by_name["list_pipelines"].needs_approval is False
    )  # list_resources is read-only


@pytest.mark.asyncio
async def test_needs_approval_matches_registry_row_for_a_generic_derived_tool(
    chat_db_factory,
):
    await _seed_all_rbac_rows(chat_db_factory)
    tools = await build_chat_tools(
        _STATE,
        chat_db_factory,
        "please update the orders dataset's definition to fix the schema drift",
        user_id="alice@acme.com",
    )
    by_name = {t.name: t for t in tools}

    assert "update_dataset_definition" in by_name
    assert await _asks_approval(
        by_name["update_dataset_definition"]
    )  # generic-derived, shares update_resource_definition's row


@pytest.mark.asyncio
async def test_rerun_pipeline_needs_approval_like_any_other_mutating_tool(
    chat_db_factory,
):
    """rerun_pipeline has no special-casing (dropped 2026-07-28, along with the dedicated
    idempotency/freshness/outcome-polling module that used to wrap it) — it goes through the
    same generic gateway wrapper as every other tool, gated only by its own rbac_permissions
    row like the rest."""
    await _seed_all_rbac_rows(chat_db_factory)
    tools = await build_chat_tools(
        _STATE,
        chat_db_factory,
        "please rerun the orders pipeline",
        user_id="alice@acme.com",
    )
    by_name = {t.name: t for t in tools}

    assert "rerun_pipeline" in by_name
    assert await _asks_approval(by_name["rerun_pipeline"])


def test_trigger_a_run_phrasing_does_not_penalize_rerun_pipeline():
    """Regression test: "trigger a run of it" used to trip _detected_resource_kind's bare
    "trigger" marker (treating it as the Trigger RESOURCE, not the verb), which penalized
    rerun_pipeline (-1, name contains "pipeline", a different kind) and bonused actual
    Trigger-resource tools (+3) — even though the phrase-synonym logic separately and
    correctly recognizes this exact phrasing as meaning "rerun"."""
    index = build_keyword_index(SPECS)
    selected = retrieve_relevant_tools(
        "please trigger a run of it",
        SPECS,
        index,
        top_k=6,
        always_include={"list_pipelines", "get_pipeline_definition"},
    )
    selected_names = {spec.name for spec in selected}
    assert "rerun_pipeline" in selected_names


def test_semantic_scoring_surfaces_linked_service_tools_for_indirect_phrasing():
    """message_embedding is optional and additive — omitted (as in every test above), retrieval
    is pure keyword, unchanged from before this was added. When supplied (the real
    build_chat_tools path), it should meaningfully favor the actually-relevant tool for a
    message that never says its name/resource-kind words directly."""
    index = build_keyword_index(SPECS)
    message = "someone changed the connection details for the sql server we read from"
    always_include = {"list_pipelines", "get_pipeline_definition"}

    message_embedding = embed_texts([message])[0]
    selected = retrieve_relevant_tools(
        message,
        SPECS,
        index,
        top_k=6,
        always_include=always_include,
        message_embedding=message_embedding,
    )
    selected_names = {spec.name for spec in selected}
    assert (
        "get_linked_service" in selected_names
        or "get_linked_service_definition_raw" in selected_names
    )


@pytest.mark.asyncio
async def test_call_missing_arguments_skips_approval_and_fails(chat_db_factory):
    """No human is asked to approve a call that can't run anyway; the model gets the error."""
    await _seed_all_rbac_rows(chat_db_factory)
    tools = await build_chat_tools(
        _STATE,
        chat_db_factory,
        "please update the orders dataset's definition to fix the schema drift",
        user_id="alice@acme.com",
    )
    update = {t.name: t for t in tools}["update_dataset_definition"]

    assert not await _asks_approval(update, dataset_name="orders")
    result = await update.on_invoke_tool(None, '{"dataset_name": "orders"}')
    assert result.startswith("Tool error: missing required argument(s)")
