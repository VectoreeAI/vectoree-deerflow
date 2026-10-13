"""Gateway URLs and cookie paths follow ``DEER_FLOW_PUBLIC_BASE_PATH``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Response
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.gateway import vectoree_google
from app.gateway.auth.oidc_state import OIDCStatePayload, delete_state_cookie, set_state_cookie
from app.gateway.auth.session_cookie import set_session_cookie
from app.gateway.public_path import cookie_path, public_base_path, public_path
from app.gateway.routers import auth as auth_router


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "scheme": "https", "path": "/", "server": ("deerflow.test", 443), "headers": [(b"host", b"deerflow.test")]})


def _cookie_paths(response: Response) -> dict[str, str]:
    paths = {}
    for name, value in response.raw_headers:
        if name != b"set-cookie":
            continue
        text = value.decode()
        key = text.split("=", 1)[0]
        attrs = dict(part.strip().split("=", 1) for part in text.split(";")[1:] if "=" in part)
        paths[key] = attrs.get("Path", "")
    return paths


@pytest.fixture
def prefixed(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_PUBLIC_BASE_PATH", "deerflow/")


@pytest.mark.parametrize(("raw", "base"), [("", ""), ("/", ""), ("deerflow", "/deerflow"), ("/deerflow/", "/deerflow"), (" /a/b/ ", "/a/b")])
def test_base_path_is_normalized(monkeypatch, raw, base):
    monkeypatch.setenv("DEER_FLOW_PUBLIC_BASE_PATH", raw)
    assert public_base_path() == base
    assert public_path("/login") == f"{base}/login"
    assert cookie_path() == (base or "/")


def test_session_csrf_and_logout_cookies_use_the_base(prefixed):
    request = _request()
    response = Response()
    set_session_cookie(response, request, "token")
    auth_router._set_csrf_cookie(response, request)

    assert _cookie_paths(response) == {"access_token": "/deerflow", "deerflow_session_persistent": "/deerflow", "csrf_token": "/deerflow"}

    logout = Response()
    for name in ("access_token", "csrf_token", "deerflow_session_persistent"):
        logout.delete_cookie(name, path=cookie_path())
    assert set(_cookie_paths(logout).values()) == {"/deerflow"}


def test_logout_clears_cookies_at_the_base(prefixed):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(auth_router.router)
    response = TestClient(app).post("/api/v1/auth/logout")

    paths = {header.split("=", 1)[0]: header for header in response.headers.get_list("set-cookie")}
    assert set(paths) == {"access_token", "csrf_token", "deerflow_session_persistent"}
    assert all("Path=/deerflow" in header for header in paths.values())


def test_cookies_stay_at_root_without_a_base(monkeypatch):
    monkeypatch.delenv("DEER_FLOW_PUBLIC_BASE_PATH", raising=False)
    response = Response()
    set_session_cookie(response, _request(), "token")
    assert set(_cookie_paths(response).values()) == {"/"}


def test_oidc_state_cookie_and_redirects_use_the_base(prefixed):
    request = _request()
    response = Response()
    set_state_cookie(response, request, OIDCStatePayload(provider="okta", state="s" * 16, nonce="n" * 16, code_verifier="v" * 43))
    delete_state_cookie(response, request, "okta")

    assert set(_cookie_paths(response).values()) == {"/deerflow/api/v1/auth/callback/okta"}
    assert auth_router._build_error_redirect(None, "sso_failed") == "/deerflow/login?error=sso_failed"
    assert auth_router._build_error_redirect("https://sso.example", "sso_failed") == "https://sso.example/login?error=sso_failed"
    redirect_uri = auth_router._resolve_oidc_redirect_uri(request, "okta", SimpleNamespace(redirect_uri=None))
    assert redirect_uri == "https://deerflow.test/deerflow/api/v1/auth/callback/okta"


def test_google_login_paths_use_the_base(prefixed):
    request = _request()
    response = RedirectResponse("https://accounts.example")
    vectoree_google._set_state_cookie(response, request, vectoree_google.GoogleLoginState(code_verifier="v" * 43))

    assert _cookie_paths(response) == {vectoree_google.GOOGLE_STATE_COOKIE: "/deerflow/api/v1/auth/vectoree/google/callback"}
    assert vectoree_google._callback_url(request) == "https://deerflow.test/deerflow/api/v1/auth/vectoree/google/callback"


@pytest.mark.asyncio
async def test_google_finish_redirects_under_the_base(prefixed, monkeypatch):
    state = vectoree_google.GoogleLoginState(code_verifier="v" * 43, next_path="/workspace/chats")
    monkeypatch.setattr(vectoree_google, "_read_state", lambda request: state)
    monkeypatch.setattr(vectoree_google, "resolve_vectoree_link", lambda: SimpleNamespace(api_url="https://vectoree.test", api_key="sk-ve-x"))

    async def exchange(link, code, verifier):
        return "ada@example.com"

    async def upsert(email):
        return SimpleNamespace(id="u1", token_version=0, vectoree_project_id="")

    monkeypatch.setattr(vectoree_google, "_exchange_email", exchange)
    monkeypatch.setattr(auth_router, "_upsert_vectoree_user", upsert)

    response = await vectoree_google.finish_google_login(_request(), "code", None)

    assert response.headers["location"] == "/deerflow/workspace/chats"
    assert _cookie_paths(response)["access_token"] == "/deerflow"
