"""Vectoree Google login routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.routers import auth as auth_router


class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    payload = {"user": {"email": "ada@example.com"}, "accessToken": "ve-access-token-secret", "refreshToken": "ve-refresh"}
    start = (200, {"authUrl": "https://accounts.google.com/o/oauth2/v2/auth?client=1"})
    calls = {"get": None, "post": None}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None, headers=None):
        _Client.calls["get"] = {"url": url, "params": params, "authorization": headers.get("Authorization")}
        return _Response(*_Client.start)

    async def post(self, url, params=None, json=None, headers=None):
        _Client.calls["post"] = {"url": url, "params": params, "json": json}
        return _Response(200, _Client.payload)


@pytest.fixture
def client(monkeypatch):
    set_auth_config(AuthConfig(jwt_secret="test-google-secret"))
    _Client.calls = {"get": None, "post": None}
    _Client.start = (200, {"authUrl": "https://accounts.google.com/o/oauth2/v2/auth?client=1"})
    _Client.payload = {"user": {"email": "ada@example.com"}, "accessToken": "ve-access-token-secret", "refreshToken": "ve-refresh"}
    monkeypatch.setattr("app.gateway.vectoree_google.httpx.AsyncClient", _Client)
    monkeypatch.setattr(
        "app.gateway.vectoree_google.resolve_vectoree_link",
        lambda: SimpleNamespace(api_url="https://vectoree.ai", api_key="sk-ve-v1-test"),
    )

    async def upsert(email):
        return SimpleNamespace(id="user-1", token_version=0, email=email)

    monkeypatch.setattr(auth_router, "_upsert_vectoree_user", upsert)
    app = FastAPI()
    app.include_router(auth_router.router)
    return TestClient(app)


def _start(client: TestClient, remember_me: str = "true"):
    return client.get(
        "/api/v1/auth/vectoree/google/start",
        params={"next": "/workspace/agents", "remember_me": remember_me},
        follow_redirects=False,
    )


def test_google_login_issues_deerflow_session(client):
    started = _start(client, "false")
    assert started.status_code == 302
    assert started.headers["location"].startswith("https://accounts.google.com/")
    assert "code_verifier" not in started.headers["location"]
    cookie = started.headers["set-cookie"]
    assert "df_vectoree_google=" in cookie
    assert "httponly" in cookie.lower()
    assert _Client.calls["get"]["url"] == "https://vectoree.ai/api/auth/oauth/google"
    assert _Client.calls["get"]["authorization"] == "Bearer sk-ve-v1-test"

    finished = client.get(
        "/api/v1/auth/vectoree/google/callback",
        params={"vectoree_code": "code-1"},
        follow_redirects=False,
    )
    assert finished.status_code == 302
    assert finished.headers["location"] == "/workspace/agents"
    assert "access_token=" in finished.headers["set-cookie"]
    assert "ve-access-token-secret" not in finished.headers["set-cookie"]
    assert "ve-refresh" not in finished.text
    assert _Client.calls["post"]["params"]["client_type"] == "server"
    assert _Client.calls["post"]["json"]["code"] == "code-1"


def test_google_cancel_or_missing_email_does_not_issue_session(client):
    _start(client)
    cancelled = client.get(
        "/api/v1/auth/vectoree/google/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )
    assert cancelled.status_code == 302
    assert cancelled.headers["location"].endswith("/login?error=google_failed")
    assert "access_token=" not in cancelled.headers.get("set-cookie", "")

    _start(client)
    _Client.payload = {"user": {}, "accessToken": "ve-access-token-secret"}
    missing = client.get(
        "/api/v1/auth/vectoree/google/callback",
        params={"vectoree_code": "code-2"},
        follow_redirects=False,
    )
    assert missing.status_code == 302
    assert missing.headers["location"].endswith("/login?error=google_failed")
    assert "access_token=" not in missing.headers.get("set-cookie", "")
    assert "ve-access-token-secret" not in missing.headers.get("set-cookie", "")


def test_google_login_with_registered_email_explains_why(client, caplog):
    import logging

    _start(client)
    with caplog.at_level(logging.WARNING, logger="app.gateway.vectoree_google"):
        rejected = client.get(
            "/api/v1/auth/vectoree/google/callback",
            params={
                "error": "This email is already registered.",
                "error_code": "AUTH_EMAIL_EXISTS",
            },
            follow_redirects=False,
        )
    assert rejected.status_code == 302
    assert rejected.headers["location"].endswith("/login?error=google_email_exists")
    assert "access_token=" not in rejected.headers.get("set-cookie", "")
    assert "AUTH_EMAIL_EXISTS" in caplog.text


def test_google_callback_failures_are_logged(client, caplog):
    import logging

    _start(client)
    _Client.payload = {"user": {}, "accessToken": "ve-access-token-secret"}
    with caplog.at_level(logging.WARNING, logger="app.gateway.vectoree_google"):
        missing = client.get(
            "/api/v1/auth/vectoree/google/callback",
            params={"vectoree_code": "code-3"},
            follow_redirects=False,
        )
    assert missing.headers["location"].endswith("/login?error=google_failed")
    assert "Vectoree Google login" in caplog.text
    assert "ve-access-token-secret" not in caplog.text
    assert "code-3" not in caplog.text


def test_google_start_sends_unconfigured_project_back_to_login(client):
    _Client.start = (
        400,
        {"error": "AUTH_OAUTH_CONFIG_ERROR", "message": "Google/GitHub is not configured for this project."},
    )
    started = _start(client)
    assert started.status_code == 302
    assert started.headers["location"].endswith("/login?error=google_not_configured")
    assert "access_token=" not in started.headers.get("set-cookie", "")


def test_google_start_other_failures_go_back_to_login(client):
    _Client.start = (500, {"error": "INTERNAL"})
    started = _start(client)
    assert started.status_code == 302
    assert started.headers["location"].endswith("/login?error=google_failed")


def test_google_login_rejects_unlinked_project(client, monkeypatch):
    monkeypatch.setattr("app.gateway.vectoree_google.resolve_vectoree_link", lambda: None)
    started = _start(client)
    assert started.status_code == 404
    assert "access_token=" not in started.headers.get("set-cookie", "")
    assert _Client.calls["get"] is None
