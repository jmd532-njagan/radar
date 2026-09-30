"""config/settings.py: a deployment with a blank secret must fail at startup."""

import pytest
from pydantic import ValidationError

from config.settings import Settings

_VALID = {
    "azure_openai_endpoint": "https://example.openai.azure.com",
    "azure_openai_deployment": "gpt-4o",
    "azure_openai_api_key": "key",
    "database_url": "postgresql+asyncpg://u:p@db:5432/watchtower",
    "hmac_secret": "hmac",
    "radar_assertion_secret": "assertion",
    "watchtower_credential_key": "credential-key",
}


def test_valid_settings_load():
    Settings(_env_file=None, **_VALID)


@pytest.mark.parametrize(
    "secret",
    [
        "azure_openai_api_key",
        "hmac_secret",
        "radar_assertion_secret",
        "watchtower_credential_key",
    ],
)
def test_blank_secret_is_rejected(secret):
    with pytest.raises(ValidationError, match=secret.upper()):
        Settings(_env_file=None, **{**_VALID, secret: "  "})
