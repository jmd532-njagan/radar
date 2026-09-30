"""
ADFToolSpec — the declarative shape every ADF tool spec is built as — plus the small
JSON-schema-fragment helpers shared by the per-kind schema files in this package
(pipelines.py, datasets.py, linked_services.py, data_flows.py, triggers.py,
global_parameters.py, integration_runtimes.py). Kept separate from schemas/__init__.py so
those per-kind files can import it without a circular import back to __init__.py (which
imports all of THEM to build the final SPECS list).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ADFToolSpec:
    # The tool's name: also its TOOL_REGISTRY key, implementing function and
    # rbac_permissions.tool_name, e.g. "update_dataset_definition".
    name: str
    description: str
    params_json_schema: dict


def schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


REASON_PROP = {
    "type": "string",
    "description": "Why this change is being made — shown to the approver.",
}
