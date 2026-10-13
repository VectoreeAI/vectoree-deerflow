"""Cloud preview users are scoped to the Vectoree project of the preview."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.gateway import deps
from app.gateway.auth.jwt import create_access_token, decode_token
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.gateway.routers import auth as auth_router
from app.gateway.vectoree_auth import AuthProxyResult, resolve_vectoree_link
from deerflow.community.vectoree.credentials import VectoreeCredentials, reset_credentials, set_credentials, use_credentials

PROJECT_A = VectoreeCredentials(api_url="https://vectoree.test", api_key="sk-ve-a", project_id="proj-a")
PROJECT_B = VectoreeCredentials(api_url="https://vectoree.test", api_key="sk-ve-b", project_id="proj-b")


@pytest_asyncio.fixture
async def provider(tmp_path, monkeypatch):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path}/users.db", sqlite_dir=str(tmp_path))
    local = LocalAuthProvider(repository=SQLiteUserRepository(get_session_factory()))
    monkeypatch.setattr(auth_router, "get_local_provider", lambda: local)
    monkeypatch.setattr(deps, "get_local_provider", lambda: local)
    try:
        yield local
    finally:
        await close_engine()


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "cloud")


def _cookie_request(token: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"cookie", f"access_token={token}".encode())]})


@pytest.mark.asyncio
async def test_same_email_in_two_projects_is_two_plain_users(provider, cloud):
    with use_credentials(PROJECT_A):
        first = await auth_router._upsert_vectoree_user("ada@example.com")
        again = await auth_router._upsert_vectoree_user("ada@example.com")
    with use_credentials(PROJECT_B):
        second = await auth_router._upsert_vectoree_user("ada@example.com")

    assert first.id == again.id
    assert first.id != second.id
    assert (first.vectoree_project_id, second.vectoree_project_id) == ("proj-a", "proj-b")
    assert first.system_role == second.system_role == "user"
    assert await provider.get_user_by_email("ada@example.com") is None


@pytest.mark.asyncio
async def test_cloud_upsert_without_a_preview_is_refused(provider, cloud):
    with pytest.raises(HTTPException) as excinfo:
        await auth_router._upsert_vectoree_user("ada@example.com")
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_local_upsert_keeps_first_user_admin(provider, monkeypatch):
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    user = await auth_router._upsert_vectoree_user("owner@example.com")
    assert (user.system_role, user.vectoree_project_id) == ("admin", "")


@pytest.mark.asyncio
async def test_session_is_valid_only_under_its_own_preview(provider, cloud):
    with use_credentials(PROJECT_A):
        user = await auth_router._upsert_vectoree_user("ada@example.com")
    token = create_access_token(str(user.id), token_version=user.token_version, vectoree_project_id=user.vectoree_project_id)
    assert decode_token(token).vp == "proj-a"

    with use_credentials(PROJECT_A):
        assert (await deps.get_current_user_from_request(_cookie_request(token))).id == user.id

    for credentials in (PROJECT_B, None):
        with use_credentials(credentials), pytest.raises(HTTPException) as excinfo:
            await deps.get_current_user_from_request(_cookie_request(token))
        assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_cloud_rejects_a_token_without_the_project_claim(provider, cloud):
    with use_credentials(PROJECT_A):
        user = await auth_router._upsert_vectoree_user("ada@example.com")
        token = create_access_token(str(user.id), token_version=user.token_version)
        with pytest.raises(HTTPException):
            await deps.get_current_user_from_request(_cookie_request(token))


def test_user_matches_preview_rules(monkeypatch):
    from app.gateway.auth.preview_session import user_matches_preview

    user = SimpleNamespace(vectoree_project_id="proj-a")
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    assert user_matches_preview(SimpleNamespace(vectoree_project_id=""), token_project="")

    monkeypatch.setenv("DEPLOY_MODE", "cloud")
    assert user_matches_preview(user, preview_project="proj-a")  # PAT: no claim to compare
    assert not user_matches_preview(user, preview_project="proj-b")
    assert not user_matches_preview(user, token_project="proj-b", preview_project="proj-a")
    assert not user_matches_preview(SimpleNamespace(vectoree_project_id=""), preview_project="")


def test_link_comes_from_the_bound_preview(monkeypatch, tmp_path):
    env = {"DEPLOY_MODE": "cloud", "VECTOREE_API_KEY": "sk-ve-server", "DEER_FLOW_PROJECT_ROOT": str(tmp_path)}
    assert resolve_vectoree_link(env) is None
    with use_credentials(PROJECT_A):
        assert resolve_vectoree_link(env).api_key == "sk-ve-a"
    with use_credentials(PROJECT_B):
        assert resolve_vectoree_link(env).api_key == "sk-ve-b"


def test_login_and_setup_status_proxy_with_each_previews_key(monkeypatch, cloud):
    seen: list[str] = []

    async def proxy(link, action, body=None):
        seen.append(link.api_key)
        return AuthProxyResult(kind="session", http_status=200, email=body["email"])

    async def upsert(email):
        project = auth_router.current_preview_project()
        return SimpleNamespace(id=f"{project}-user", token_version=0, email=email, needs_setup=False, vectoree_project_id=project)

    monkeypatch.setattr(auth_router, "proxy_vectoree_auth", proxy)
    monkeypatch.setattr(auth_router, "_upsert_vectoree_user", upsert)
    monkeypatch.setattr(auth_router, "_record_login_success", lambda ip: None)

    async def _no_rate_limit(ip):
        return None

    monkeypatch.setattr(auth_router, "_check_rate_limit", _no_rate_limit)

    app = FastAPI()
    projects = {"a": PROJECT_A, "b": PROJECT_B}

    @app.middleware("http")
    async def bind_preview(request, call_next):
        token = set_credentials(projects.get(request.headers.get("x-preview", "")))
        try:
            return await call_next(request)
        finally:
            reset_credentials(token)

    app.include_router(auth_router.router)
    client = TestClient(app)

    for name in ("a", "b"):
        response = client.post("/api/v1/auth/login/local", data={"username": "ada@example.com", "password": "pw"}, headers={"x-preview": name})
        assert response.status_code == 200
        token = response.cookies.get("access_token") or client.cookies.get("access_token")
        assert decode_token(token).vp == f"proj-{name}"
    assert seen == ["sk-ve-a", "sk-ve-b"]

    status_live = client.get("/api/v1/auth/setup-status", headers={"x-preview": "a"}).json()
    status_none = client.get("/api/v1/auth/setup-status").json()
    assert status_live == {"needs_setup": False, "registration_enabled": True, "vectoree_linked": True, "deploy_mode": "cloud"}
    assert status_none["vectoree_linked"] is False and status_none["needs_setup"] is False
