"""Global-parameter tool specs."""

from platform_tools.adf.schemas.base import REASON_PROP, ADFToolSpec, schema

TOOLS = [
    ADFToolSpec(
        name="get_global_parameter_definition_raw",
        description=(
            'Full global parameter definition ({"type": ..., "value": ...}). Feed the returned dict '
            "back into update_global_parameter_definition (with edits applied) to apply a fix."
        ),
        params_json_schema=schema(
            {"global_parameter_name": {"type": "string"}}, ["global_parameter_name"]
        ),
    ),
    ADFToolSpec(
        name="create_global_parameter",
        description=(
            "Creates a brand-new global parameter. Fails with an explicit error if one with this name "
            "already exists — use update_global_parameter_definition to modify an existing one instead. "
            '`definition` should be {"type": ..., "value": ...}, the same flat shape '
            "get_global_parameter_definition_raw uses."
        ),
        params_json_schema=schema(
            {
                "global_parameter_name": {"type": "string"},
                "definition": {
                    "type": "object",
                    "description": '{"type": ..., "value": ...} global parameter definition.',
                },
                "reason": REASON_PROP,
            },
            ["global_parameter_name", "definition", "reason"],
        ),
    ),
    ADFToolSpec(
        name="list_global_parameters",
        description=(
            "Factory-wide global parameter sweep — name, type, and value for each. These are the "
            "factory-level parameters referenced by pipelines/datasets/linked services via "
            "@pipeline().globalParameters.<name>."
        ),
        params_json_schema=schema({}, []),
    ),
    ADFToolSpec(
        name="update_global_parameter_definition",
        description=(
            "Overwrites a global parameter's type/value (e.g. to fix a stale connection string or a "
            "flipped environment flag baked in as a global). `definition` must be "
            "get_global_parameter_definition_raw's output with edits applied."
        ),
        params_json_schema=schema(
            {
                "global_parameter_name": {"type": "string"},
                "definition": {
                    "type": "object",
                    "description": "Modified output of get_global_parameter_definition_raw.",
                },
                "reason": REASON_PROP,
            },
            ["global_parameter_name", "definition", "reason"],
        ),
    ),
]
