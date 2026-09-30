from azure.core.exceptions import ResourceNotFoundError
from azure.mgmt.datafactory.models import LinkedServiceResource

from platform_tools.adf.tools._shared import (
    _client,
    _deserialize_checked,
    _to_wire_dict,
)


def get_linked_service(
    service_name: str,
    factory_name: str,
    subscription_id: str,
    resource_group: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
) -> dict:
    """
    Name and type only (e.g. "AzureSqlDatabase"). Does not include the configured host/
    port/connection string, which live in typeProperties. Use
    get_linked_service_definition_raw for the real connection details.
    """
    client = _client(tenant_id, client_id, client_secret, subscription_id)
    svc = client.linked_services.get(resource_group, factory_name, service_name)
    if svc is None:
        return {"name": service_name, "type": "unknown"}
    return {
        "name": svc.name,
        "type": svc.properties.type if svc.properties else "unknown",
    }


def list_linked_services(
    factory_name: str,
    subscription_id: str,
    resource_group: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
) -> dict:
    """
    Factory-wide linked-service sweep, vs. get_linked_service's single lookup. Useful when
    the failing linked service isn't known by name up front.
    """
    client = _client(tenant_id, client_id, client_secret, subscription_id)
    services = client.linked_services.list_by_factory(resource_group, factory_name)
    return {
        "linked_services": [
            {"name": s.name, "type": s.properties.type if s.properties else "unknown"}
            for s in services
        ]
    }


def get_linked_service_definition_raw(
    service_name: str,
    factory_name: str,
    subscription_id: str,
    resource_group: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
) -> dict:
    """
    Full linked-service definition, including the configured host/port/connection string
    (e.g. AzureSqlDatabase's typeProperties.connectionString). The editable structure to
    feed back into update_linked_service_definition.
    """
    client = _client(tenant_id, client_id, client_secret, subscription_id)
    svc = client.linked_services.get(resource_group, factory_name, service_name)
    return _to_wire_dict(svc)


def create_linked_service(
    service_name: str,
    factory_name: str,
    subscription_id: str,
    resource_group: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    definition: dict,
    reason: str,
) -> dict:
    """
    Creates a brand-new linked service. Fails with an explicit error if one with this name
    already exists — use update_linked_service_definition to modify an existing one instead.
    """
    client = _client(tenant_id, client_id, client_secret, subscription_id)

    try:
        client.linked_services.get(resource_group, factory_name, service_name)
        return {"error": "linked_service_already_exists", "service_name": service_name}
    except ResourceNotFoundError:
        pass

    linked_service_resource, error = _deserialize_checked(
        LinkedServiceResource, {"properties": definition}, "linked service"
    )
    if error:
        return error
    created = client.linked_services.create_or_update(
        resource_group, factory_name, service_name, linked_service_resource
    )

    return {
        "service_name": service_name,
        "created": True,
        "reason": reason,
        "etag": created.etag,
    }


def update_linked_service_definition(
    service_name: str,
    factory_name: str,
    subscription_id: str,
    resource_group: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    definition: dict,
    reason: str,
) -> dict:
    """Overwrites a linked service's full definition (e.g. to correct a wrong host/port in a `network`/`config` failure)."""
    client = _client(tenant_id, client_id, client_secret, subscription_id)

    linked_service_resource, error = _deserialize_checked(
        LinkedServiceResource, {"properties": definition}, "linked service"
    )
    if error:
        return error
    updated = client.linked_services.create_or_update(
        resource_group, factory_name, service_name, linked_service_resource
    )

    return {
        "service_name": service_name,
        "updated": True,
        "reason": reason,
        "etag": updated.etag,
    }
