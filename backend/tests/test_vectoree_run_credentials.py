"""Cloud preview credentials travel with a run: Gateway stamp, worker bind, background work."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from app.gateway.services import build_run_config, inject_authenticated_user_context, strip_internal_context_keys
from deerflow.agents.memory.backends.deermem.deermem.core.queue import MemoryUpdateQueue
from deerflow.community.vectoree.credentials import (
    RUN_CONTEXT_KEY,
    VectoreeCredentials,
    bound_credentials,
    current_credentials,
    use_credentials,
)
from deerflow.runtime.runs.worker import _bind_run_vectoree_credentials

PREVIEW_A = VectoreeCredentials(api_url="https://vectoree.net", api_key="sk-ve-a", project_id="proj-a")
PREVIEW_B = VectoreeCredentials(api_url="https://vectoree.net", api_key="sk-ve-b", project_id="proj-b")


def _request():
    return SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="user-1", system_role="user")))


def test_gateway_stamps_bound_preview_into_runtime_context_only():
    config = build_run_config("thread-1", None, None)

    with use_credentials(PREVIEW_A):
        inject_authenticated_user_context(config, _request())

    assert config["context"][RUN_CONTEXT_KEY] == PREVIEW_A.to_context()
    assert RUN_CONTEXT_KEY not in (config.get("configurable") or {})


def test_client_supplied_credentials_are_dropped():
    forged = {"api_url": "https://evil.example", "api_key": "sk-ve-forged", "project_id": "x"}
    config = build_run_config("thread-1", {"context": {RUN_CONTEXT_KEY: forged}, "configurable": {RUN_CONTEXT_KEY: forged}}, None)

    strip_internal_context_keys(config)
    inject_authenticated_user_context(config, _request())

    assert RUN_CONTEXT_KEY not in config["context"]
    assert RUN_CONTEXT_KEY not in config["configurable"]


def test_client_copy_is_replaced_by_the_bound_preview():
    forged = {"api_url": "https://evil.example", "api_key": "sk-ve-forged", "project_id": "x"}
    config = build_run_config("thread-1", {"context": {RUN_CONTEXT_KEY: forged}}, None)

    with use_credentials(PREVIEW_B):
        inject_authenticated_user_context(config, _request())

    assert config["context"][RUN_CONTEXT_KEY]["api_key"] == "sk-ve-b"


def test_worker_binds_stamped_credentials_inside_its_task(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "cloud")

    async def run(config):
        _bind_run_vectoree_credentials(config)
        await asyncio.sleep(0)
        return current_credentials()

    async def main():
        return await asyncio.create_task(run({"context": {RUN_CONTEXT_KEY: PREVIEW_A.to_context()}}))

    assert asyncio.run(main()) == PREVIEW_A
    assert bound_credentials() is None


def test_concurrent_runs_send_only_their_own_key(monkeypatch):
    """Two visitors' runs interleave; each Vectoree request carries its own key."""
    from deerflow.community.vectoree import client as vectoree_client

    monkeypatch.setenv("DEPLOY_MODE", "cloud")
    seen: list[tuple[str, str]] = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"query": "q", "results": []}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.append((json["query"], headers["Authorization"]))
        return _Response()

    monkeypatch.setattr(vectoree_client.httpx, "post", fake_post)

    async def run(name: str, credentials: VectoreeCredentials):
        _bind_run_vectoree_credentials({"context": {RUN_CONTEXT_KEY: credentials.to_context()}})
        for step in range(3):
            await asyncio.sleep(0)
            await asyncio.to_thread(vectoree_client.post_json, vectoree_client.RUN_PATH, {"action": "search", "query": f"{name}-{step}", "max_results": 1})

    async def main():
        await asyncio.gather(asyncio.create_task(run("a", PREVIEW_A)), asyncio.create_task(run("b", PREVIEW_B)))

    asyncio.run(main())

    assert len(seen) == 6
    for query, authorization in seen:
        assert authorization == ("Bearer sk-ve-a" if query.startswith("a-") else "Bearer sk-ve-b")


class _RecordingUpdater:
    def __init__(self):
        self.seen: list[tuple[str, str | None, str]] = []
        self.done = threading.Event()

    def update_memory(self, *, thread_id, **_kwargs):
        credentials = bound_credentials()
        self.seen.append((thread_id, credentials.api_key if credentials else None, threading.current_thread().name))
        self.done.set()
        return True


def test_memory_queue_timer_thread_keeps_the_enqueuers_credentials():
    updater = _RecordingUpdater()
    queue = MemoryUpdateQueue(SimpleNamespace(queue_max_depth=0, debounce_seconds=0), updater)

    with use_credentials(PREVIEW_A):
        queue.add_nowait("thread-a", [], user_id="user-1")

    assert updater.done.wait(5)
    thread_id, api_key, thread_name = updater.seen[0]
    assert (thread_id, api_key) == ("thread-a", "sk-ve-a")
    assert thread_name != threading.current_thread().name
