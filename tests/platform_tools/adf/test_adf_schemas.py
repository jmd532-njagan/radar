"""
Unit tests for platform_tools.adf.schemas (the 44-distinct-tool declarative spec table, one file
per resource kind) and platform_tools.adf.tool_search_tool (the keyword-based tool selector) — see the
"Expose all ADF tools" plan and claude-desktop/toolsearch_prototype/vtests/
toolsearch_evaluation.md for the live evaluation this design is based on. These are
structural/spot-check tests, not a re-run of the full 57-case live evaluation (already done,
real Azure calls, documented separately).

The git-like checkpoint/rollback/back/forward versioning system (list_*_snapshots,
rollback_*_definition, back_*_definition, forward_*_definition — 24 tool names across 6
resource kinds) was removed 2026-08-12, shrinking the spec table from 68 to 44.
"""

import inspect
import re
from pathlib import Path

from platform_tools.adf.schemas import SPECS
from platform_tools.adf.tool_search_tool import (
    build_keyword_index,
    retrieve_relevant_tools,
)
from platform_tools.adf.tools import TOOL_REGISTRY

_RBAC_SEED_MIGRATION = (
    Path(__file__).parents[3]
    / "prisma"
    / "migrations"
    / "20260811000001_seed_all_adf_tool_permissions"
    / "migration.sql"
)
_RBAC_VERSIONING_REMOVAL_MIGRATION = (
    Path(__file__).parents[3]
    / "prisma"
    / "migrations"
    / "20260812000000_remove_resource_versioning"
    / "migration.sql"
)


def test_all_spec_names_are_unique():
    names = [spec.name for spec in SPECS]
    assert len(names) == 44
    assert len(set(names)) == 44


def test_every_spec_is_a_registered_tool():
    """A spec whose name isn't a TOOL_REGISTRY key would fail the first time a chat turn called
    it; a registered function with no spec would never be offered to the model."""
    assert {spec.name for spec in SPECS} == set(TOOL_REGISTRY)


def test_spec_arguments_match_the_tool_function():
    """The model's arguments are passed straight to the tool function, so every argument a
    spec declares must be a parameter of that function."""
    for spec in SPECS:
        params = inspect.signature(TOOL_REGISTRY[spec.name]).parameters
        assert set(spec.params_json_schema["properties"]) <= set(params), spec.name


def test_list_tools_take_no_arguments():
    list_datasets = next(spec for spec in SPECS if spec.name == "list_datasets")
    assert list_datasets.params_json_schema["properties"] == {}
    assert list_datasets.params_json_schema["required"] == []


def test_raw_definition_getters_exclude_trigger():
    names = {spec.name for spec in SPECS if spec.name.endswith("_definition_raw")}
    assert "get_trigger_definition_raw" not in names
    assert names == {
        "get_pipeline_definition_raw",
        "get_dataset_definition_raw",
        "get_linked_service_definition_raw",
        "get_data_flow_definition_raw",
        "get_global_parameter_definition_raw",
    }


def test_every_spec_has_a_seeded_rbac_permissions_row():
    """Regression test for the real bug this guards against: only 5 of 68 tool_name values ever
    had an rbac_permissions row, so tool_search_tool.py's allowed_specs filter silently made 63
    tools invisible in chat (a spec with no matching row is dropped entirely, not just denied).
    Parses the seed migration's literal tool_name values, then subtracts the 24 checkpoint-
    versioning tool names the later 20260812000000 migration deletes (SPECS shrank to 44 in the
    same change) — rather than re-deriving the current set from scratch, so this fails loudly if
    a new tool is ever added to SPECS without a matching seed row."""
    seed_sql = _RBAC_SEED_MIGRATION.read_text()
    seeded_names = set(
        re.findall(
            r"^\s*\('([a-z_]+)', (?:true|false), (?:true|false), 'adf'\),?$",
            seed_sql,
            re.MULTILINE,
        )
    )

    removal_sql = _RBAC_VERSIONING_REMOVAL_MIGRATION.read_text()
    removed_names = set(re.findall(r"'([a-z_]+)'", removal_sql))

    current_seeded_names = seeded_names - removed_names
    spec_names = {spec.name for spec in SPECS}
    assert current_seeded_names == spec_names, (
        f"missing from seed: {spec_names - current_seeded_names}; "
        f"seeded but no longer a real spec: {current_seeded_names - spec_names}"
    )


def test_retrieval_finds_the_expected_tool_for_representative_messages():
    """Spot-check, not a re-run of the full 57-case live evaluation (already done against the
    real model, see claude-desktop/toolsearch_prototype/vtests/toolsearch_evaluation.md) -
    this just confirms the ported algorithm still works against the real spec table."""
    index = build_keyword_index(SPECS)
    always_include = {"list_pipelines", "get_pipeline_definition"}

    cases = [
        (
            "Can you update the Foo dataset's definition to fix the schema drift?",
            "update_dataset_definition",
        ),
        ("that trigger run is hanging, cancel it", "cancel_trigger_run"),
        ("what datasets exist in this data factory", "list_datasets"),
        ("kill the pipeline run that's stuck", "cancel_pipeline_run"),
    ]
    for message, expected in cases:
        selected = retrieve_relevant_tools(
            message, SPECS, index, top_k=8, always_include=always_include
        )
        selected_names = [spec.name for spec in selected]
        assert expected in selected_names, (
            f"{expected!r} not retrieved for {message!r}: got {selected_names}"
        )
