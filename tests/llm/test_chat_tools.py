"""
Tests for llm.tools — the platform-agnostic half of tool-building: the failure-pattern tools
(llm/memory/tools.py) and build_tools_for_platform, the dispatcher that adds each platform's
own tool set on top. ADF-specific tool-building (retrieval, rbac_permissions filtering,
needs_approval) is covered in test_tool_search_tool.py.
"""

import json
from dataclasses import asdict
from datetime import UTC, datetime

import pytest
from agents.tool_context import ToolContext
from sqlalchemy import select

from db import failure_patterns
from db.models import (
    AuditLog,
    FailureEvent,
    FailurePattern,
    ProjectMetadata,
    RBACPermission,
)
from intake.signature import parse
from llm.tools import build_tools_for_platform
from platform_tools.adf.schemas import SPECS

_MESSAGE = "ErrorCode=TypeConversionFailure,Exception occurred when converting value 'x' for column name 'amount'."
_STATE = {
    "investigation_id": "inv-1",
    "thread_id": None,
    "pipeline_name": "orders_pipeline",
    "project": "acme",
    "platform": "adf",
    "pattern_id": None,
}


def _ctx(tool_name: str) -> ToolContext:
    return ToolContext(
        context=None, tool_name=tool_name, tool_call_id="t", tool_arguments="{}"
    )


async def _seed_failure(db_factory) -> int:
    """A project with one failure and the pattern intake would have created for it."""
    sig = parse("adf", "2200", _MESSAGE)
    async with db_factory() as db:
        db.add(ProjectMetadata(project="acme", platform="adf"))
        await db.flush()
        pattern, _ = await failure_patterns.match_or_create(
            db, "acme", sig, "orders_pipeline"
        )
        db.add(
            FailureEvent(
                investigation_id="inv-1",
                project="acme",
                platform="adf",
                pipeline_name="orders_pipeline",
                run_status="Failed",
                start_time=datetime.now(UTC),
                created_at=datetime.now(UTC),
                pattern_id=pattern.id,
                matched_by="new",
                signature=asdict(sig),
            )
        )
        await db.commit()
        return pattern.id


async def _tools(db_factory, platform: str = "unknown_future_platform", **state):
    return await build_tools_for_platform(
        platform,
        {**_STATE, **state},
        db_factory,
        "some question",
        user_id="5f0c2b7e-9a41-4c8e-b1d3-7e2a6c4f9d10",
    )


@pytest.mark.asyncio
async def test_failure_pattern_tools_present_without_platform_tools(chat_db_factory):
    names = [t.name for t in await _tools(chat_db_factory)]
    assert names == [
        "get_failure_patterns",
        "propose_failure_pattern",
        "propose_memory",
        "search_sop",
    ]


@pytest.mark.asyncio
async def test_failure_pattern_tools_present_alongside_adf_tools(chat_db_factory):
    async with chat_db_factory() as db:
        for name in {spec.name for spec in SPECS}:
            db.add(RBACPermission(tool_name=name, allowed=True, requires_consent=False))
        await db.commit()
    names = [t.name for t in await _tools(chat_db_factory, platform="adf")]
    assert {"get_failure_patterns", "propose_failure_pattern"} <= set(names)
    assert len(names) > 2


@pytest.mark.asyncio
async def test_propose_needs_approval_and_updates_the_pattern(chat_db_factory):
    pattern_id = await _seed_failure(chat_db_factory)
    tools = {t.name: t for t in await _tools(chat_db_factory, pattern_id=pattern_id)}
    propose = tools["propose_failure_pattern"]
    assert propose.needs_approval is True

    await propose.on_invoke_tool(
        _ctx("propose_failure_pattern"),
        json.dumps(
            {
                "cause": "Source sends text in the numeric amount column.",
                "category": "data_quality",
                "verify_with": ["get_dataset_definition"],
                "fix_actions": ["fix_source_value", "rerun_pipeline"],
                "outcome": "fixed",
                "reason": "Row 42 has 'x' in amount.",
            }
        ),
    )

    async with chat_db_factory() as db:
        pattern = await db.get(FailurePattern, pattern_id)
        assert (pattern.status, pattern.category) == ("active", "data_quality")
        assert pattern.fix_actions == ["fix_source_value", "rerun_pipeline"]
        assert (await db.get(FailureEvent, "inv-1")).outcome == "fixed"
        audit = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.event_type == "failure_pattern_approved"
                )
            )
        ).scalar_one()
        assert (
            audit.detail["changes"]["cause"]["after"]
            == "Source sends text in the numeric amount column."
        )


@pytest.mark.asyncio
async def test_get_failure_patterns_reports_history(chat_db_factory):
    pattern_id = await _seed_failure(chat_db_factory)
    tools = {t.name: t for t in await _tools(chat_db_factory, pattern_id=pattern_id)}
    result = json.loads(
        await tools["get_failure_patterns"].on_invoke_tool(
            _ctx("get_failure_patterns"), "{}"
        )
    )
    assert result[0]["pattern"] == f"FP-{pattern_id}"
    assert result[0]["code"] == "TypeConversionFailure"
    assert result[0]["seen"] == 1


@pytest.mark.asyncio
async def test_repeat_failure_matches_the_same_pattern(chat_db_factory):
    pattern_id = await _seed_failure(chat_db_factory)
    other = parse("adf", "2200", _MESSAGE.replace("'amount'", "'price'"))
    async with chat_db_factory() as db:
        pattern, matched_by = await failure_patterns.match_or_create(
            db, "acme", other, "billing_pipeline"
        )
        await db.commit()
        assert (pattern.id, matched_by) == (pattern_id, "code")
        assert pattern.pipelines == ["orders_pipeline", "billing_pipeline"]
