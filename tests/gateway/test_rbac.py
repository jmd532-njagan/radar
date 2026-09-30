from unittest.mock import AsyncMock, MagicMock

import pytest
from azure.core.exceptions import ClientAuthenticationError

from gateway.rbac import call_tool


class _FakeDb:
    def __init__(self, allowed: bool):
        self._allowed = allowed
        self.commit = AsyncMock()
        self.add = lambda *_a, **_k: None

    async def execute(self, _stmt, *_args):
        return None

    async def scalar(self, _stmt):
        return self._allowed


def _patch_resolve(monkeypatch, client_secret="s3cr3t"):
    monkeypatch.setattr(
        "gateway.rbac.resolve_client_secret", AsyncMock(return_value=client_secret)
    )


def _patch_registry(monkeypatch, registry: dict):
    monkeypatch.setattr("gateway.rbac.adf_tools.TOOL_REGISTRY", registry)


async def _call(db, tool_name, arguments=None, infra=None, user_id="system"):
    return await call_tool(
        db,
        tool_name=tool_name,
        arguments=arguments or {},
        user_id=user_id,
        pipeline_id="pl",
        project="acme",
        platform="adf",
        infra_params_dict=infra or {},
        investigation_id=None,
    )


@pytest.mark.asyncio
async def test_dispatch_runs_sync_tool_via_executor(monkeypatch):
    def fake_sync_tool(**kwargs):
        return {"got": kwargs}

    _patch_registry(monkeypatch, {"fake_sync_tool": fake_sync_tool})
    _patch_resolve(monkeypatch)

    result = await _call(_FakeDb(allowed=True), "fake_sync_tool", {"x": 1})

    assert result["got"]["x"] == 1
    assert result["got"]["client_secret"] == "s3cr3t"


@pytest.mark.asyncio
async def test_dispatch_denies_disallowed_tool_before_calling_it(monkeypatch):
    _patch_resolve(monkeypatch)

    with pytest.raises(PermissionError):
        await _call(_FakeDb(allowed=False), "anything")


@pytest.mark.asyncio
async def test_client_authentication_error_invalidates_cache_entry_and_still_propagates(
    monkeypatch,
):
    """A stale/rotated credential surfaces as ClientAuthenticationError from the Azure SDK call
    inside a tool function. The gateway must evict that project's cached client (so the NEXT
    call rebuilds fresh) without swallowing the error — this call still fails, only the next
    one gets a chance to succeed."""

    def failing_tool(**kwargs):
        raise ClientAuthenticationError(message="invalid_client secret")

    _patch_registry(monkeypatch, {"failing_tool": failing_tool})
    _patch_resolve(monkeypatch, client_secret="rotated-secret")
    invalidate = MagicMock()
    monkeypatch.setattr("gateway.rbac.client_cache.invalidate", invalidate)

    with pytest.raises(ClientAuthenticationError):
        await _call(
            _FakeDb(allowed=True),
            "failing_tool",
            infra={"tenant_id": "t1", "client_id": "c1", "subscription_id": "s1"},
        )

    invalidate.assert_called_once_with("t1", "c1", "rotated-secret", "s1")


@pytest.mark.asyncio
async def test_enrich_arguments_cannot_override_trusted_infra_params(monkeypatch):
    """A model can't be schema-restricted from emitting extra keys (FunctionTool is built with
    strict_json_schema=False), so if it ever emits e.g. "tenant_id" as an extra argument, the
    gateway must not let it override the investigation's real project identity — that would
    let a chat turn for Project A silently execute the Azure call against Project B's tenant."""
    captured = {}

    def fake_sync_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    _patch_registry(monkeypatch, {"fake_sync_tool": fake_sync_tool})
    _patch_resolve(monkeypatch, client_secret="real-secret")

    await _call(
        _FakeDb(allowed=True),
        "fake_sync_tool",
        {"tenant_id": "attacker-tenant", "pipeline_name": "CustomerLoad"},
        infra={"tenant_id": "trusted-tenant", "subscription_id": "trusted-sub"},
    )

    assert captured["tenant_id"] == "trusted-tenant"
    assert captured["subscription_id"] == "trusted-sub"
    assert captured["pipeline_name"] == "CustomerLoad"
    assert captured["client_secret"] == "real-secret"


@pytest.mark.asyncio
async def test_enrich_resolves_client_secret_for_the_calling_project(monkeypatch):
    """resolve_client_secret must be asked about the tool call's actual project, not some
    other value — this is the trust boundary the whole cache design depends on."""
    resolve = AsyncMock(return_value="s3cr3t")
    monkeypatch.setattr("gateway.rbac.resolve_client_secret", resolve)
    _patch_registry(monkeypatch, {"fake_sync_tool": lambda **kwargs: {"ok": True}})

    await _call(_FakeDb(allowed=True), "fake_sync_tool")

    resolve.assert_called_once()
    args, _kwargs = resolve.call_args
    assert args[1] == "acme"


@pytest.mark.asyncio
async def test_log_includes_arguments_but_never_client_secret(monkeypatch):
    """The audit row's detail must include the caller-supplied arguments (so the audit trail
    can tell which resource a tool call touched), but never the client_secret added after."""
    added = []
    _patch_registry(
        monkeypatch, {"update_dataset_definition": lambda **kw: {"ok": True}}
    )
    _patch_resolve(monkeypatch)
    fake_db = _FakeDb(allowed=True)
    fake_db.add = added.append
    arguments = {
        "dataset_name": "Foo",
        "reason": "test",
        "definition": {"type": "AzureSqlTable"},
    }

    await _call(fake_db, "update_dataset_definition", arguments, user_id="alice")

    assert len(added) == 1
    entry = added[0]
    assert entry.detail == {"tool": "update_dataset_definition", "arguments": arguments}
    assert entry.user_id == "alice"
