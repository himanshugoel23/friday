"""Recording storage (S-6, SECURITY-14/19): object store adapter + erasure.

* ``S3ObjectStore`` - ``Settings.object_store_url = s3://bucket/prefix`` (India region,
  ``ap-south-1``). Objects are private; clients get short-lived **signed URLs**
  (``signed_url``, default 24 h, PRD US-7.2). Retention = a bucket lifecycle rule
  (``lifecycle_rule(days)``) so recordings expire even if a job is missed.
* ``LocalObjectStore`` - ``<media_dir>/recordings`` for the simulator/dev only; never in
  live mode (``build_object_store`` refuses).
* ``delete_recording(url)`` - erasure for any URL Friday stored: ``s3://`` -> the store,
  ``file://`` -> unlink (only under allowed roots, regular files, never symlinks),
  provider ``https://`` URLs -> ``telephony.delete_recording`` when the provider has it.

Voice owns the upload path (``put``); Backend A owns this adapter and erasure.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from urllib.parse import unquote, urlparse

from friday.core.config import Settings
from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)

DEFAULT_REGION = "ap-south-1"
SIGNED_URL_TTL_S = 24 * 3600
RECORDING_SUFFIXES = frozenset({".wav", ".mp3", ".ogg", ".opus", ".m4a", ".webm", ".txt", ".json"})


@runtime_checkable
class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        """Store privately; returns the canonical URL to persist (s3:// or file://)."""
        ...

    async def delete(self, url: str) -> bool:
        """True if deleted (or already gone); False if the URL isn't ours."""
        ...

    async def signed_url(self, url: str, *, expires_s: int = SIGNED_URL_TTL_S) -> str: ...


def _safe_key(key: str) -> str:
    parts = [p for p in key.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if not parts:
        raise ValueError("empty object key")
    return "/".join(parts)


class S3ObjectStore:
    def __init__(
        self, bucket: str, prefix: str = "", *, region: str = DEFAULT_REGION, client: Any = None
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.region = region
        if client is None:  # pragma: no cover - real AWS
            import boto3

            client = boto3.client("s3", region_name=region)
        self.client = client

    @classmethod
    def from_url(cls, url: str, **kw: Any) -> S3ObjectStore:
        u = urlparse(url)
        if u.scheme != "s3" or not u.netloc:
            raise ValueError("object_store_url must look like s3://bucket/prefix")
        return cls(u.netloc, u.path, **kw)

    def _key(self, key: str) -> str:
        key = _safe_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def owns(self, url: str) -> bool:
        u = urlparse(url)
        return u.scheme == "s3" and u.netloc == self.bucket

    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        k = self._key(key)
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=k,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="aws:kms",
        )
        return f"s3://{self.bucket}/{k}"

    async def delete(self, url: str) -> bool:
        if not self.owns(url):
            return False
        key = urlparse(url).path.lstrip("/")
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)
        return True

    async def signed_url(self, url: str, *, expires_s: int = SIGNED_URL_TTL_S) -> str:
        if not self.owns(url):
            raise ValueError("not an object of this store")
        key = urlparse(url).path.lstrip("/")
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=int(expires_s),
        )

    def lifecycle_rule(self, days: int) -> dict[str, Any]:
        """Bucket lifecycle = recording retention (apply with put_bucket_lifecycle_configuration)."""
        return {
            "Rules": [
                {
                    "ID": f"friday-recordings-{days}d",
                    "Filter": {"Prefix": f"{self.prefix}/" if self.prefix else ""},
                    "Status": "Enabled",
                    "Expiration": {"Days": int(days)},
                }
            ]
        }


class LocalObjectStore:
    """Dev/simulator store under ``root``. ``extra_roots`` are other local folders whose
    recordings Friday may erase (the simulator writes to ``<media_dir>/recordings``)."""

    def __init__(self, root: str | Path, *, extra_roots: Sequence[str | Path] = ()) -> None:
        self.root = Path(root).expanduser().resolve()
        self.roots = [self.root, *(Path(r).expanduser().resolve() for r in extra_roots)]

    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        path = self.root / _safe_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return path.as_uri()

    def _path(self, url: str) -> Path | None:
        u = urlparse(url)
        if u.scheme != "file":
            return None
        raw = Path(unquote(u.path))
        if raw.is_symlink():
            return None
        path = raw.resolve()
        if path.suffix.lower() not in RECORDING_SUFFIXES:
            return None
        if not any(path.is_relative_to(r) for r in self.roots):
            return None
        return path

    def owns(self, url: str) -> bool:
        return self._path(url) is not None

    async def delete(self, url: str) -> bool:
        path = self._path(url)
        if path is None:
            return False
        if path.exists() and not path.is_file():
            return False
        path.unlink(missing_ok=True)
        return True

    async def signed_url(self, url: str, *, expires_s: int = SIGNED_URL_TTL_S) -> str:
        if self._path(url) is None:
            raise ValueError("not an object of this store")
        return url  # dev only: served by the simulator's local route


def build_object_store(settings: Settings, *, s3_client: Any = None) -> ObjectStore:
    if settings.object_store_url:
        return S3ObjectStore.from_url(settings.object_store_url, client=s3_client)
    if settings.is_live:
        raise ProviderError(
            "object_store", "FRIDAY_OBJECT_STORE_URL (s3://...) is required in live mode"
        )
    media = Path(settings.media_dir)
    # Dev/test only: simulator recordings may also sit in the system temp dir.
    return LocalObjectStore(media / "recordings", extra_roots=[media, tempfile.gettempdir()])


def build_object_store_component(c: Container) -> ObjectStore:
    return build_object_store(c.settings)


async def delete_recording(url: str, *, store: ObjectStore, telephony: Any = None) -> bool:
    """Erase one recording wherever it lives. True = gone; False = must be retried."""
    try:
        if await store.delete(url):
            return True
        scheme = urlparse(url).scheme
        if scheme in ("http", "https"):
            deleter = getattr(telephony, "delete_recording", None)
            if callable(deleter):
                await deleter(url)
                return True
            return False
        if scheme in ("file", "s3"):
            log.warning("refusing to delete a recording outside Friday's stores")
            return False
    except Exception as e:  # noqa: BLE001 - erasure is retried via pending_deletions
        log.warning("recording deletion failed: %s", type(e).__name__)
        return False
    return False
