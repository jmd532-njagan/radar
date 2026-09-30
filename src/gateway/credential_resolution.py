"""
Per-project ADF credential lookup — reads WatchTower's own public."Credential" table (the one
its Integrations tab writes) directly. It is the only source for a project's ADF connection
details: the non-secret identifiers (tenant/client/subscription/resource group/factory) and the
encrypted client_secret. Decryption is a local AES operation (no network I/O), the same scheme
as watch-Tower/src/lib/crypto.ts's decryptData: CryptoJS's AES.encrypt(JSON.stringify(data),
passphrase), i.e. OpenSSL's "Salted__" format (MD5 EVP_BytesToKey, AES-256-CBC) — verified
byte-for-byte against a real encrypted row.
"""

import base64
import hashlib
import json
from dataclasses import dataclass

from Crypto.Cipher import AES
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings


class CredentialResolutionError(RuntimeError):
    """Raised when a project has no ADF Credential row, or its secret fails to decrypt."""


@dataclass(frozen=True)
class ProjectCredential:
    tenant_id: str | None
    client_id: str | None
    subscription_id: str | None
    resource_group: str | None
    factory_name: str | None
    encrypted_client_secret: str | None


async def get_adf_credential(
    db: AsyncSession, project: str
) -> ProjectCredential | None:
    """The project's live ADF integration row. A project normally has one; if the
    Integrations tab ever holds several, the oldest wins so every caller picks the same row."""
    result = await db.execute(
        text(
            'SELECT c."tenantId", c."clientId", c."subscriptionId", c."resourceGroupName", '
            'c."dataFactoryName", c."clientSecret" FROM public."Credential" c '
            'JOIN public."Service" s ON s.id = c."serviceId" '
            'WHERE c."projectName" = :project AND s.name = \'adf\' AND NOT c."isDeleted" '
            'ORDER BY c."createdAt" LIMIT 1'
        ),
        {"project": project},
    )
    row = result.first()
    return ProjectCredential(*row) if row else None


async def resolve_client_secret(db: AsyncSession, project: str) -> str:
    """Takes the caller's already-open AsyncSession directly (not a factory) — this is a plain
    read alongside whatever else that session is already doing in the same request."""
    credential = await get_adf_credential(db, project)
    if credential is None or not credential.encrypted_client_secret:
        raise CredentialResolutionError(
            f"project='{project}' has no ADF Credential row in WatchTower's public.\"Credential\" table"
        )
    try:
        return decrypt_cryptojs_aes(
            credential.encrypted_client_secret, settings.watchtower_credential_key
        )
    except Exception as exc:
        raise CredentialResolutionError(
            f"Failed to decrypt client_secret for project='{project}': {exc}"
        ) from exc


def _evp_bytes_to_key(
    password: bytes, salt: bytes, key_len: int, iv_len: int
) -> tuple[bytes, bytes]:
    derived = b""
    block = b""
    while len(derived) < key_len + iv_len:
        block = hashlib.md5(block + password + salt).digest()
        derived += block
    return derived[:key_len], derived[key_len : key_len + iv_len]


def decrypt_cryptojs_aes(ciphertext_b64: str, passphrase: str) -> str:
    """Mirrors decryptData(ciphertext, key) exactly, including its JSON.parse of the decrypted
    plaintext — WatchTower always JSON.stringifies before encrypting, even a plain string."""
    raw = base64.b64decode(ciphertext_b64)
    if raw[:8] != b"Salted__":
        raise ValueError("Not a CryptoJS OpenSSL-salted payload")
    salt = raw[8:16]
    ciphertext = raw[16:]
    key, iv = _evp_bytes_to_key(passphrase.encode("utf-8"), salt, key_len=32, iv_len=16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = cipher.decrypt(ciphertext)
    plaintext = padded[: -padded[-1]].decode("utf-8")
    return json.loads(plaintext)
