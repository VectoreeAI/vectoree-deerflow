"""Vectoree registration: send a code, confirm it, then sign in separately."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import auth as auth_router
from app.gateway.vectoree_auth import AuthProxyResult, _interpret_auth


@pytest.fixture
def harness(monkeypatch):
    state = {"calls": [], "results": {}, "upserted": []}

    async def proxy(link, action, body=None):
        state["calls"].append((action, dict(body or {})))
        return state["results"][action]

    async def upsert(email):
        state["upserted"].append(email)
        return SimpleNamespace(id="user-1", token_version=0, email=email)

    monkeypatch.setattr(auth_router, "proxy_vectoree_auth", proxy)
    monkeypatch.setattr(auth_router, "_upsert_vectoree_user", upsert)
    monkeypatch.setattr(
        auth_router,
        "resolve_vectoree_link",
        lambda: SimpleNamespace(api_url="https://vectoree.ai", api_key="sk-ve-v1-test"),
    )
    app = FastAPI()
    app.include_router(auth_router.router)
    return TestClient(app), state


def test_register_code_sends_the_code_without_a_session(harness):
    client, state = harness
    state["results"]["register"] = AuthProxyResult(kind="verify", http_status=200, message="code")

    response = client.post(
        "/api/v1/auth/vectoree/register/code",
        json={"email": "ada@example.com", "password": "Secret123"},
    )

    assert response.status_code == 200
    assert response.json() == {"code_sent": True}
    assert "access_token=" not in response.headers.get("set-cookie", "")
    assert state["calls"] == [("register", {"email": "ada@example.com", "password": "Secret123"})]


def test_register_complete_creates_the_user_and_does_not_sign_in(harness):
    client, state = harness
    state["results"]["verify"] = AuthProxyResult(kind="session", http_status=200, email="ada@example.com")

    response = client.post(
        "/api/v1/auth/vectoree/register/complete",
        json={"email": "ada@example.com", "otp": "12345678"},
    )

    assert response.status_code == 200
    assert response.json() == {"created": True}
    assert "access_token=" not in response.headers.get("set-cookie", "")
    assert state["upserted"] == ["ada@example.com"]


def test_register_complete_rejects_a_wrong_code(harness):
    client, state = harness
    state["results"]["verify"] = AuthProxyResult(kind="error", http_status=400, message="Invalid verification code")

    response = client.post(
        "/api/v1/auth/vectoree/register/complete",
        json={"email": "ada@example.com", "otp": "00000000"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["message"] == "Invalid verification code"
    assert state["upserted"] == []


def test_register_code_reports_an_existing_email(harness):
    client, state = harness
    state["results"]["register"] = AuthProxyResult(kind="error", http_status=400, message="Email already registered")

    response = client.post(
        "/api/v1/auth/vectoree/register/code",
        json={"email": "ada@example.com", "password": "Secret123"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "email_already_exists"


def test_register_code_without_verification_creates_the_account(harness):
    client, state = harness
    state["results"]["register"] = AuthProxyResult(kind="session", http_status=200, email="ada@example.com")

    response = client.post(
        "/api/v1/auth/vectoree/register/code",
        json={"email": "ada@example.com", "password": "Secret123"},
    )

    assert response.json() == {"code_sent": False, "created": True}
    assert "access_token=" not in response.headers.get("set-cookie", "")
    assert state["upserted"] == ["ada@example.com"]


def test_register_requires_a_linked_project(harness, monkeypatch):
    client, _state = harness
    monkeypatch.setattr(auth_router, "resolve_vectoree_link", lambda: None)

    response = client.post(
        "/api/v1/auth/vectoree/register/code",
        json={"email": "ada@example.com", "password": "Secret123"},
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    ("status_code", "payload", "message"),
    [
        (409, {"error": "AUTH_EMAIL_EXISTS", "message": "User already exists"}, "Email already registered"),
        (400, {"error": "INVALID_INPUT", "message": "Password must be at least 8 characters"}, "Password must be at least 8 characters"),
        (500, None, "Could not create the account"),
    ],
)
def test_register_errors_keep_the_vectoree_reason(status_code, payload, message):
    assert _interpret_auth("register", status_code, payload).message == message
