"""Server-side store for cloud preview sessions.

A preview maps an opaque browser cookie to the visitor's Vectoree project key.
The key never leaves the server; it is stored Fernet-encrypted with a key
derived from ``BETTER_AUTH_SECRET`` so a Redis dump alone does not leak it.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from deerflow.community.vectoree.credentials import VectoreeCredentials

logger = logging.getLogger(__name__)

PREVIEW_COOKIE = "deerflow_preview"
PREVIEW_IDLE_SECONDS = 12 * 60 * 60
_REDIS_PREFIX = "deerflow:preview:"
_HKDF_INFO = b"deerflow-preview-store-v1"


class PreviewStoreConfigError(RuntimeError):
    """Raised when cloud mode cannot build the preview store."""


@dataclass(frozen=True)
class PreviewRecord:
    api_url: str
    api_key: str
    project_id: str
    organization_id: str = ""

    def credentials(self) -> VectoreeCredentials:
        return VectoreeCredentials(api_url=self.api_url, api_key=self.api_key, project_id=self.project_id)


class PreviewStore(Protocol):
    async def get(self, preview_id: str) -> PreviewRecord | None: ...

    async def create(self, record: PreviewRecord, *, replace: str | None = None) -> str: ...

    async def delete(self, preview_id: str) -> None: ...


class PreviewCipher:
    def __init__(self, secret: str) -> None:
        if not secret:
            raise PreviewStoreConfigError("BETTER_AUTH_SECRET is required to store cloud previews")
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(secret.encode("utf-8"))
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def seal(self, record: PreviewRecord) -> str:
        data = asdict(record)
        data["api_key_enc"] = self._fernet.encrypt(data.pop("api_key").encode("utf-8")).decode("ascii")
        return json.dumps(data, separators=(",", ":"))

    def open(self, raw: str | bytes) -> PreviewRecord | None:
        try:
            data: dict[str, Any] = json.loads(raw)
            api_key = self._fernet.decrypt(str(data["api_key_enc"]).encode("ascii")).decode("utf-8")
            return PreviewRecord(
                api_url=str(data["api_url"]),
                api_key=api_key,
                project_id=str(data["project_id"]),
                organization_id=str(data.get("organization_id") or ""),
            )
        except (InvalidToken, KeyError, TypeError, ValueError):
            logger.warning("Discarding unreadable preview record")
            return None


def new_preview_id() -> str:
    return secrets.token_urlsafe(32)


def valid_preview_id(value: str | None) -> bool:
    return bool(value) and 20 <= len(value) <= 128 and value.replace("-", "").replace("_", "").isalnum()


class MemoryPreviewStore:
    """Single-process store for tests and local debugging; loses previews on restart."""

    def __init__(self, cipher: PreviewCipher, *, ttl: int = PREVIEW_IDLE_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._cipher = cipher
        self._ttl = ttl
        self._clock = clock
        self._items: dict[str, tuple[float, str]] = {}

    async def get(self, preview_id: str) -> PreviewRecord | None:
        item = self._items.get(preview_id)
        if item is None:
            return None
        expires_at, raw = item
        now = self._clock()
        if now >= expires_at:
            self._items.pop(preview_id, None)
            return None
        record = self._cipher.open(raw)
        if record is None:
            self._items.pop(preview_id, None)
            return None
        self._items[preview_id] = (now + self._ttl, raw)
        return record

    async def create(self, record: PreviewRecord, *, replace: str | None = None) -> str:
        if replace:
            self._items.pop(replace, None)
        preview_id = new_preview_id()
        self._items[preview_id] = (self._clock() + self._ttl, self._cipher.seal(record))
        return preview_id

    async def delete(self, preview_id: str) -> None:
        self._items.pop(preview_id, None)


class RedisPreviewStore:
    """Survives Gateway restarts and is shared by every worker."""

    def __init__(self, client: Any, cipher: PreviewCipher, *, ttl: int = PREVIEW_IDLE_SECONDS) -> None:
        self._client = client
        self._cipher = cipher
        self._ttl = ttl

    async def get(self, preview_id: str) -> PreviewRecord | None:
        key = _REDIS_PREFIX + preview_id
        raw = await self._client.getex(key, ex=self._ttl)
        if raw is None:
            return None
        record = self._cipher.open(raw)
        if record is None:
            await self._client.delete(key)
        return record

    async def create(self, record: PreviewRecord, *, replace: str | None = None) -> str:
        if replace:
            await self._client.delete(_REDIS_PREFIX + replace)
        preview_id = new_preview_id()
        await self._client.set(_REDIS_PREFIX + preview_id, self._cipher.seal(record), ex=self._ttl)
        return preview_id

    async def delete(self, preview_id: str) -> None:
        await self._client.delete(_REDIS_PREFIX + preview_id)


_store: PreviewStore | None = None


def build_preview_store(env: dict[str, str] | None = None) -> PreviewStore:
    source = env if env is not None else os.environ
    cipher = PreviewCipher(source.get("BETTER_AUTH_SECRET", "").strip())
    redis_url = source.get("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", "").strip()
    if not redis_url:
        logger.warning("No Redis URL configured; cloud previews are kept in memory and lost on restart")
        return MemoryPreviewStore(cipher)
    from redis.asyncio import Redis

    return RedisPreviewStore(Redis.from_url(redis_url), cipher)


def get_preview_store() -> PreviewStore:
    global _store
    if _store is None:
        _store = build_preview_store()
    return _store


def set_preview_store(store: PreviewStore | None) -> None:
    global _store
    _store = store
