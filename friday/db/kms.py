"""KMS envelope-encryption key provider (SECURITY-12 live path, OPS-1).

``build_kms_key_provider`` (FACTORIES["key_provider"]["kms"]) is selected in live mode
when ``FRIDAY_FIELD_KEY_ID`` (the KMS key id/ARN) is set.

* Data keys (DEKs) are stored only KMS-wrapped, in the environment:
  ``FRIDAY_KMS_WRAPPED_KEYS`` = JSON ``{"<key_id>": "<base64 wrapped DEK>", ...}`` and
  ``FRIDAY_KMS_CURRENT_KEY_ID`` = the key id new values are encrypted with (defaults to
  the last entry). Rotation = generate a new DEK (``kms generate-data-key``), append it
  and make it current; old ciphertext stays readable by its key id, and
  ``friday.db.rotation.reencrypt_columns`` moves rows to the current key.
* ``unwrap`` calls KMS Decrypt once per key id (cached in memory, never logged).
* The blind-index key is separate (``Settings.key_material("index_key")``, SECURITY-30).

Owner: Backend Engineer A (+ Ops for the KMS keys).
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from typing import TYPE_CHECKING

from friday.core.crypto import KmsKeyProvider
from friday.core.interfaces import ProviderError

if TYPE_CHECKING:
    from friday.core.container import Container

Unwrap = Callable[[bytes], bytes]
DEFAULT_REGION = "ap-south-1"  # India (Mumbai) - data residency


def parse_wrapped_keys(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        raise ValueError("FRIDAY_KMS_WRAPPED_KEYS must be a JSON object of base64 strings")
    for kid in data:
        if ":" in kid:
            raise ValueError("key ids must not contain ':'")
    return data


def aws_kms_unwrap(key_id: str, *, region: str = DEFAULT_REGION) -> Unwrap:  # pragma: no cover
    """KMS Decrypt via boto3 (credentials from the instance role / env)."""
    import boto3

    client = boto3.client("kms", region_name=region)

    def unwrap(wrapped: bytes) -> bytes:
        resp = client.decrypt(CiphertextBlob=wrapped, KeyId=key_id)
        key = resp["Plaintext"]
        if len(key) != 32:
            raise ProviderError("kms", "data key must be 32 bytes (AES-256)")
        return key

    return unwrap


def make_kms_provider(
    wrapped: dict[str, str], *, current: str | None, unwrap: Unwrap, index_key: bytes
) -> KmsKeyProvider:
    if not wrapped:
        raise ProviderError("kms", "no wrapped data keys configured (FRIDAY_KMS_WRAPPED_KEYS)")
    current = current or list(wrapped)[-1]
    if current not in wrapped:
        raise ProviderError("kms", "current key id is not among the wrapped keys")
    for v in wrapped.values():
        base64.b64decode(v, validate=True)  # fail fast on malformed config
    return KmsKeyProvider(wrapped, current, unwrap, index_key)


def build_kms_key_provider(c: Container, *, unwrap: Unwrap | None = None) -> KmsKeyProvider:
    s = c.settings
    if not s.field_key_id:
        raise ProviderError("kms", "FRIDAY_FIELD_KEY_ID not set")
    wrapped = parse_wrapped_keys(os.environ.get("FRIDAY_KMS_WRAPPED_KEYS"))
    region = os.environ.get("FRIDAY_KMS_REGION", DEFAULT_REGION)
    return make_kms_provider(
        wrapped,
        current=os.environ.get("FRIDAY_KMS_CURRENT_KEY_ID"),
        unwrap=unwrap or aws_kms_unwrap(s.field_key_id, region=region),
        index_key=s.key_material("index_key"),
    )
