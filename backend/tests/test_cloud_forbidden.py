"""Cloud preview visitors cannot change deployment-wide state (design D5)."""

from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.gateway import deps
from app.gateway.routers import auth as auth_router

ADMIN = SimpleNamespace(id="admin-1", email="admin@example.com", system_role="admin", vectoree_project_id="")

ADMIN_GATED_MODULES = ["managed_models", "mcp", "skills", "integrations", "capabilities", "channels", "channel_connections", "subagents"]

# Per-user actions: a visitor authorizes their own Lark account or IM
# connection. They write only that user's credentials, never shared state.
PER_USER_ROUTES = {
    ("integrations", "/api/integrations/lark/config/start"),
    ("integrations", "/api/integrations/lark/config/complete"),
    ("integrations", "/api/integrations/lark/config/credentials"),
    ("integrations", "/api/integrations/lark/auth/start"),
    ("integrations", "/api/integrations/lark/auth/complete"),
    ("channel_connections", "/api/channels/connections/{connection_id}"),
    ("channel_connections", "/api/channels/{provider}/connect"),
    ("channel_connections", "/api/channels/wechat/qr-login"),
    ("channel_connections", "/api/channels/wechat/qr-login/{session_id}/poll"),
    ("channel_connections", "/api/channels/wechat/qr-login/{session_id}"),
}


def _mutating_routes():
    for name in ADMIN_GATED_MODULES:
        module = importlib.import_module(f"app.gateway.routers.{name}")
        for route in module.router.routes:
            if getattr(route, "methods", set()) & {"POST", "PUT", "PATCH", "DELETE"}:
                yield name, route


@pytest.mark.parametrize(("module", "route"), list(_mutating_routes()), ids=lambda value: getattr(value, "path", value))
def test_every_shared_write_goes_through_the_admin_gate(module, route):
    if (module, route.path) in PER_USER_ROUTES:
        return
    assert "require_admin_user" in inspect.getsource(route.endpoint), f"{module} {route.path} must call require_admin_user"


def _admin_request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.user = ADMIN
    return request


@pytest.mark.asyncio
async def test_admin_gate_forbids_cloud_and_keeps_local(monkeypatch):
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    await deps.require_admin_user(_admin_request(), detail="admin only")
    assert await deps.is_admin_user(_admin_request()) is True

    monkeypatch.setenv("DEPLOY_MODE", "cloud")
    assert await deps.is_admin_user(_admin_request()) is False
    with pytest.raises(HTTPException) as excinfo:
        await deps.require_admin_user(_admin_request(), detail="admin only")
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail["code"] == deps.CLOUD_FORBIDDEN


def _client_as_admin(*routers) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def stamp_admin(request, call_next):
        request.state.user = ADMIN
        request.state.auth_source = "session"
        return await call_next(request)

    for router in routers:
        app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize(
    ("module", "method", "path"),
    [
        ("skills", "POST", "/api/skills/reload"),
        ("mcp", "POST", "/api/mcp/cache/reset"),
        ("mcp", "DELETE", "/api/mcp/config/servers/demo"),
        ("subagents", "DELETE", "/api/subagents/demo"),
        ("channels", "POST", "/api/channels/feishu/restart"),
    ],
)
def test_admin_routes_return_403_in_cloud(monkeypatch, module, method, path):
    monkeypatch.setenv("DEPLOY_MODE", "cloud")
    client = _client_as_admin(importlib.import_module(f"app.gateway.routers.{module}").router)

    response = client.request(method, path)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == deps.CLOUD_FORBIDDEN


def test_initialize_is_forbidden_in_cloud(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "cloud")

    async def no_admins():
        return 0

    monkeypatch.setattr(auth_router, "get_local_provider", lambda: SimpleNamespace(count_admin_users=no_admins))
    client = _client_as_admin(auth_router.router)

    response = client.post("/api/v1/auth/initialize", json={"email": "x@example.com", "password": "Str0ng-Passw0rd!"})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == deps.CLOUD_FORBIDDEN


@pytest.mark.parametrize("cloud", [True, False])
def test_publishing_project_credentials_is_forbidden_only_in_cloud(monkeypatch, cloud):
    from app.gateway.routers import vectoree_project

    if cloud:
        monkeypatch.setenv("DEPLOY_MODE", "cloud")
    else:
        monkeypatch.delenv("DEPLOY_MODE", raising=False)
    published = []
    monkeypatch.setattr(vectoree_project, "_is_internal_caller", lambda request, user: True)
    monkeypatch.setattr(vectoree_project, "publish_vectoree_project", published.append)
    client = _client_as_admin(vectoree_project.router)

    response = client.post(
        "/api/internal/vectoree/project-credentials",
        json={"apiUrl": "https://vectoree.test", "apiKey": "sk-ve-x", "apiBase": "https://vectoree.test/api/v1", "accessToken": "t", "projectId": "p"},
    )

    if cloud:
        assert response.status_code == 403
        assert published == []
    else:
        assert response.status_code == 200
        assert len(published) == 1


def test_extension_principal_is_never_admin_in_cloud(monkeypatch):
    from deerflow_extension_api import EXTENSION_PRINCIPAL_RESOLVER_KEY

    from app.gateway.app import create_app

    app = create_app()
    resolve = getattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, None)
    assert resolve is not None
    request = SimpleNamespace(state=SimpleNamespace(user=ADMIN, auth_source="session"))

    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    assert resolve(request).is_admin is True
    monkeypatch.setenv("DEPLOY_MODE", "cloud")
    assert resolve(request).is_admin is False
