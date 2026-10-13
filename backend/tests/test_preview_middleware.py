"""Preview middleware and status endpoint: binding, preview_required, expiry."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.preview_middleware import PreviewMiddleware
from app.gateway.preview_store import PREVIEW_COOKIE, MemoryPreviewStore, PreviewCipher, PreviewRecord, set_preview_store
from app.gateway.routers import preview as preview_router
from deerflow.community.vectoree.credentials import bound_credentials


class _Clock:
    now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def store(clock):
    store = MemoryPreviewStore(PreviewCipher("s"), ttl=100, clock=clock)
    set_preview_store(store)
    yield store
    set_preview_store(None)


@pytest.fixture
def client(monkeypatch, store):
    monkeypatch.setenv("DEPLOY_MODE", "cloud")
    app = FastAPI()
    app.add_middleware(PreviewMiddleware)
    app.include_router(preview_router.router)

    @app.get("/api/models")
    async def models():
        credentials = bound_credentials()
        return {"key": credentials.api_key if credentials else None}

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/api/v1/auth/setup-status")
    async def setup_status():
        return {"bound": bound_credentials() is not None}

    return TestClient(app)


def _preview(store, key="sk-ve-a", project="proj-a") -> str:
    return asyncio.run(store.create(PreviewRecord(api_url="https://vectoree.net", api_key=key, project_id=project)))


def test_no_preview_rejects_project_routes(client):
    response = client.get("/api/models")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "preview_required"


def test_routes_that_work_without_a_preview(client):
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/auth/setup-status").json() == {"bound": False}
    assert client.get("/api/v1/preview/status").json() == {"active": False}


def test_live_preview_binds_its_credentials(client, store):
    client.cookies.set(PREVIEW_COOKIE, _preview(store))

    assert client.get("/api/models").json() == {"key": "sk-ve-a"}
    assert client.get("/api/v1/preview/status").json() == {"active": True}
    assert bound_credentials() is None


def test_each_cookie_gets_its_own_project(client, store):
    a, b = _preview(store, "sk-ve-a", "a"), _preview(store, "sk-ve-b", "b")

    client.cookies.set(PREVIEW_COOKIE, a)
    assert client.get("/api/models").json() == {"key": "sk-ve-a"}
    client.cookies.set(PREVIEW_COOKIE, b)
    assert client.get("/api/models").json() == {"key": "sk-ve-b"}


def test_idle_preview_expires_and_activity_extends_it(client, store, clock):
    client.cookies.set(PREVIEW_COOKIE, _preview(store))

    clock.now = 90
    assert client.get("/api/v1/preview/status").json() == {"active": True}
    clock.now = 180
    assert client.get("/api/models").status_code == 200
    clock.now = 281
    assert client.get("/api/v1/preview/status").json() == {"active": False}
    assert client.get("/api/models").status_code == 401


def test_garbage_cookie_counts_as_no_preview(client):
    client.cookies.set(PREVIEW_COOKIE, "../../etc/passwd")

    assert client.get("/api/models").status_code == 401


def test_local_mode_passes_through_without_binding(client, monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "local")

    assert client.get("/api/models").json() == {"key": None}
    assert client.get("/api/v1/preview/status").status_code == 404
