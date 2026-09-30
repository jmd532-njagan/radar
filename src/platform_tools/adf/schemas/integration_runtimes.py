"""Integration-runtime tool specs: status and start — an IR has no editable definition."""

from platform_tools.adf.schemas.base import REASON_PROP, ADFToolSpec, schema

TOOLS = [
    ADFToolSpec(
        name="get_integration_runtime_status",
        description=(
            "Get an integration runtime's state (works for Azure, self-hosted, and Azure-SSIS IR "
            "types). Use this before start_integration_runtime to check whether starting it is even "
            "applicable."
        ),
        params_json_schema=schema(
            {"integration_runtime_name": {"type": "string"}},
            ["integration_runtime_name"],
        ),
    ),
    ADFToolSpec(
        name="start_integration_runtime",
        description=(
            "Starts a stopped Azure-SSIS (managed) integration runtime. Does NOT work on self-hosted "
            "IRs — no remote-start API exists; that's human-only. Only call this after "
            "get_integration_runtime_status confirms the IR is a managed type and is Stopped."
        ),
        params_json_schema=schema(
            {
                "integration_runtime_name": {"type": "string"},
                "reason": REASON_PROP,
            },
            ["integration_runtime_name", "reason"],
        ),
    ),
]
