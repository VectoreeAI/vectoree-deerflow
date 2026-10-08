from __future__ import annotations

import json

import httpx
import pytest

from app.gateway import vectoree_auth
from app.gateway.vectoree_auth import AuthProxyResult, VectoreeLink, proxy_vectoree_auth, resolve_vectoree_link, sanitize_auth_body


def test_resolve_link_from_project_files(tmp_path, monkeypatch):
    monkeypatch.delenv("VECTOREE_API_KEY", raising=False)
    monkeypatch.delenv("VECTOREE_API_URL", raising=False)
    (tmp_path / ".vectoree").mkdir()
    (tmp_path / ".vectoree" / "config.json").write_text(
        json.dumps({"apiKey": "sk-ve-v1-from-file", "apiUrl": "https://vectoree.ai"}),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("VECTOREE_API_KEY=\nOTHER=keep\n", encoding="utf-8")

    link = resolve_vectoree_link({"DEER_FLOW_PROJECT_ROOT": str(tmp_path)})

    assert link == VectoreeLink(api_url="https://vectoree.ai", api_key="sk-ve-v1-from-file")


def test_blank_key_is_not_linked(tmp_path):
    (tmp_path / ".env").write_text("VECTOREE_API_KEY=\nVECTOREE_API_URL=https://vectoree.ai\n", encoding="utf-8")

    assert resolve_vectoree_link({"DEER_FLOW_PROJECT_ROOT": str(tmp_path), "VECTOREE_API_KEY": ""}) is None


def test_sanitize_login_maps_username_and_rejects_otp_shape():
    assert sanitize_auth_body("login", {"username": "a@example.com", "password": "secret"}) == {
        "email": "a@example.com",
        "password": "secret",
    }
    with pytest.raises(ValueError, match="8 digits"):
        sanitize_auth_body("verify", {"email": "a@example.com", "otp": "1234"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "payload", "expected"),
    [
        (
            200,
            {"user": {"email": "a@example.com"}, "accessToken": "jwt-secret", "refreshToken": "refresh-secret"},
            AuthProxyResult(kind="session", http_status=200, email="a@example.com"),
        ),
        (
            403,
            {"error": "AUTH_NEED_VERIFICATION"},
            AuthProxyResult(kind="verify", http_status=200, message="Enter the 8-digit code sent to your email."),
        ),
        (
            401,
            {"message": "bad", "accessToken": "should-not-leak"},
            AuthProxyResult(kind="error", http_status=401, message="Incorrect email or password"),
        ),
    ],
)
async def test_proxy_login_hides_vectoree_tokens(monkeypatch, status_code, payload, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["client_type"] == "server"
        assert request.headers["authorization"] == "Bearer sk-ve-v1-test"
        assert b"jwt-secret" not in request.content
        return httpx.Response(status_code, json=payload)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    class _Client:
        def __init__(self, **kwargs):
            kwargs["transport"] = transport
            self._client = real_client(**kwargs)

        async def __aenter__(self):
            return self._client

        async def __aexit__(self, *args):
            await self._client.aclose()

    monkeypatch.setattr(vectoree_auth.httpx, "AsyncClient", _Client)
    result = await proxy_vectoree_auth(
        VectoreeLink(api_url="https://vectoree.ai", api_key="sk-ve-v1-test"),
        "login",
        {"email": "a@example.com", "password": "secret"},
    )

    assert result == expected
    assert "jwt-secret" not in result.message
    assert "refresh-secret" not in result.message
