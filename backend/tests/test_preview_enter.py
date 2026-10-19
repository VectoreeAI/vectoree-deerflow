"""Cloud preview entry: ticket redeem, cookie, redirects, local-mode rejection."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.preview_store import PREVIEW_COOKIE, MemoryPreviewStore, PreviewCipher, set_preview_store
from app.gateway.routers import preview as preview_router

TICKET = "t" * 32
PREVIEW_KEY = "sk-ve-v1-preview-secret"


class _Response:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Client:
    result: _Response | Exception = _Response(200, {"apiKey": PREVIEW_KEY, "projectId": "proj-a", "organizationId": "org-1"})
    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None):
        _Client.calls.append({"url": url, "json": json})
        if isinstance(_Client.result, Exception):
            raise _Client.result
        return _Client.result


@pytest.fixture
def store():
    store = MemoryPreviewStore(PreviewCipher("test-secret"))
    set_preview_store(store)
    yield store
    set_preview_store(None)


@pytest.fixture
def client(monkeypatch, store):
    monkeypatch.setenv("DEPLOY_MODE", "cloud")
    monkeypatch.setenv("VECTOREE_API_URL", "https://vectoree.net/")
    monkeypatch.delenv("DEER_FLOW_PUBLIC_BASE_PATH", raising=False)
    _Client.calls = []
    _Client.result = _Response(200, {"apiKey": PREVIEW_KEY, "projectId": "proj-a", "organizationId": "org-1"})
    monkeypatch.setattr("app.gateway.routers.preview.httpx.AsyncClient", _Client)
    app = FastAPI()
    app.include_router(preview_router.router)
    return TestClient(app, follow_redirects=False)


def _set_cookie_headers(response) -> list[str]:
    return response.headers.get_list("set-cookie")


def test_valid_ticket_sets_cookie_and_redirects_to_login(client, store):
    response = client.get("/api/v1/preview/enter", params={"ticket": TICKET})

    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    assert _Client.calls == [{"url": "https://vectoree.net/api/system/starter/preview/redeem", "json": {"ticket": TICKET}}]
    cookies = _set_cookie_headers(response)
    assert len(cookies) == 1 and cookies[0].startswith(f"{PREVIEW_COOKIE}=")
    assert "HttpOnly" in cookies[0] and "Path=/" in cookies[0]
    assert PREVIEW_KEY not in response.text and PREVIEW_KEY not in cookies[0] and PREVIEW_KEY not in response.headers["location"]
    preview_id = cookies[0].split(";")[0].split("=", 1)[1]
    record = asyncio.run(store.get(preview_id))
    assert (record.api_key, record.project_id, record.api_url) == (PREVIEW_KEY, "proj-a", "https://vectoree.net")


def test_base_path_prefixes_redirect_and_cookie_path(client, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_PUBLIC_BASE_PATH", "/deerflow/")

    response = client.get("/api/v1/preview/enter", params={"ticket": TICKET})

    assert response.headers["location"] == "/deerflow/login"
    assert "Path=/deerflow" in _set_cookie_headers(response)[0]


def test_new_ticket_replaces_previous_preview(client, store):
    first = client.get("/api/v1/preview/enter", params={"ticket": TICKET})
    old_id = _set_cookie_headers(first)[0].split(";")[0].split("=", 1)[1]
    client.cookies.set(PREVIEW_COOKIE, old_id)

    client.get("/api/v1/preview/enter", params={"ticket": TICKET})

    assert asyncio.run(store.get(old_id)) is None


@pytest.mark.parametrize(
    ("result", "location"),
    [
        (_Response(410, {"message": "used"}), "/preview-expired"),
        (_Response(400, {"message": "bad"}), "/preview-expired"),
        (_Response(502, {"message": "down"}), "/preview-expired?reason=unavailable"),
        (_Response(200, {"apiKey": "not-a-project-key", "projectId": "p"}), "/preview-expired?reason=unavailable"),
        (_Response(200, ValueError("not json")), "/preview-expired?reason=unavailable"),
        (httpx.ConnectError("boom"), "/preview-expired?reason=unavailable"),
    ],
)
def test_failed_redeem_redirects_without_cookie(client, result, location):
    _Client.result = result

    response = client.get("/api/v1/preview/enter", params={"ticket": TICKET})

    assert response.status_code == 302
    assert response.headers["location"] == location
    assert _set_cookie_headers(response) == []


@pytest.mark.parametrize("ticket", [None, "short", "has space in the middle ok", "x" * 513])
def test_malformed_ticket_is_not_sent_upstream(client, ticket):
    params = {"ticket": ticket} if ticket is not None else {}

    response = client.get("/api/v1/preview/enter", params=params)

    assert response.headers["location"] == "/preview-expired"
    assert _Client.calls == []


def test_local_mode_has_no_preview_entry(client, monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "local")

    response = client.get("/api/v1/preview/enter", params={"ticket": TICKET})

    assert response.status_code == 404
    assert _Client.calls == []
