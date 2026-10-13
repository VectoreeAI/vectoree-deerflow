"""Cloud preview store: encryption, sliding TTL, replacement, Redis wiring."""

from __future__ import annotations

import asyncio

import pytest

from app.gateway.preview_store import (
    MemoryPreviewStore,
    PreviewCipher,
    PreviewRecord,
    PreviewStoreConfigError,
    RedisPreviewStore,
    build_preview_store,
    valid_preview_id,
)

RECORD = PreviewRecord(api_url="https://vectoree.net", api_key="sk-ve-v1-secret", project_id="proj-a", organization_id="org-1")


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _FakeRedis:
    """Implements the handful of async redis commands the store uses."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex

    async def getex(self, key, ex=None):
        if key not in self.values:
            return None
        self.ttls[key] = ex
        return self.values[key].encode("utf-8")

    async def delete(self, key):
        self.values.pop(key, None)
        self.ttls.pop(key, None)


def _run(coro):
    return asyncio.run(coro)


def test_cipher_round_trip_and_never_stores_plain_key():
    cipher = PreviewCipher("secret-a")
    sealed = cipher.seal(RECORD)

    assert "sk-ve-v1-secret" not in sealed
    assert cipher.open(sealed) == RECORD
    assert PreviewCipher("secret-b").open(sealed) is None


def test_cipher_requires_secret():
    with pytest.raises(PreviewStoreConfigError):
        PreviewCipher("")


def test_memory_store_slides_ttl_on_read():
    clock = _Clock()
    store = MemoryPreviewStore(PreviewCipher("s"), ttl=100, clock=clock)
    preview_id = _run(store.create(RECORD))

    clock.now += 90
    assert _run(store.get(preview_id)) == RECORD
    clock.now += 90
    assert _run(store.get(preview_id)) == RECORD
    clock.now += 101
    assert _run(store.get(preview_id)) is None


def test_new_preview_replaces_the_old_one():
    store = MemoryPreviewStore(PreviewCipher("s"))
    old_id = _run(store.create(RECORD))
    new_id = _run(store.create(PreviewRecord(api_url="https://vectoree.net", api_key="sk-b", project_id="proj-b"), replace=old_id))

    assert new_id != old_id
    assert _run(store.get(old_id)) is None
    assert _run(store.get(new_id)).project_id == "proj-b"


def test_redis_store_encrypts_refreshes_and_replaces():
    client = _FakeRedis()
    store = RedisPreviewStore(client, PreviewCipher("s"), ttl=43200)
    preview_id = _run(store.create(RECORD))
    key = f"deerflow:preview:{preview_id}"

    assert "sk-ve-v1-secret" not in client.values[key]
    assert client.ttls[key] == 43200
    client.ttls[key] = 5
    assert _run(store.get(preview_id)) == RECORD
    assert client.ttls[key] == 43200

    replacement = _run(store.create(RECORD, replace=preview_id))
    assert key not in client.values
    assert _run(store.get(replacement)) == RECORD


def test_redis_store_drops_unreadable_records():
    client = _FakeRedis()
    store = RedisPreviewStore(client, PreviewCipher("s"))
    preview_id = _run(store.create(RECORD))
    other = RedisPreviewStore(client, PreviewCipher("rotated"))

    assert _run(other.get(preview_id)) is None
    assert f"deerflow:preview:{preview_id}" not in client.values


def test_build_store_picks_backend():
    assert isinstance(build_preview_store({"BETTER_AUTH_SECRET": "s"}), MemoryPreviewStore)
    assert isinstance(build_preview_store({"BETTER_AUTH_SECRET": "s", "DEER_FLOW_STREAM_BRIDGE_REDIS_URL": "redis://localhost:6379/0"}), RedisPreviewStore)
    with pytest.raises(PreviewStoreConfigError):
        build_preview_store({"DEER_FLOW_STREAM_BRIDGE_REDIS_URL": "redis://localhost:6379/0"})


def test_preview_id_shape():
    assert valid_preview_id("a" * 43)
    assert not valid_preview_id("short")
    assert not valid_preview_id("x" * 40 + "/../")
    assert not valid_preview_id(None)
