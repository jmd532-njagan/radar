"""
The ADF tool registry: every public function in the per-kind modules below is one tool, keyed
by its own name — the same name as its spec (platform_tools/adf/schemas/) and its
rbac_permissions.tool_name. gateway/rbac.py calls these with the model's arguments plus the
gateway-injected credentials.
"""

import inspect
from collections.abc import Callable

from platform_tools.adf.tools import (
    data_flows,
    datasets,
    global_parameters,
    integration_runtimes,
    linked_services,
    pipelines,
    triggers,
)

TOOL_REGISTRY: dict[str, Callable[..., dict]] = {
    name: fn
    for module in (
        pipelines,
        datasets,
        linked_services,
        data_flows,
        triggers,
        global_parameters,
        integration_runtimes,
    )
    for name, fn in vars(module).items()
    if inspect.isfunction(fn)
    and fn.__module__ == module.__name__
    and not name.startswith("_")
}
