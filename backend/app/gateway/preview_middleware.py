"""Bind the visitor's cloud preview to each Gateway request.

In ``DEPLOY_MODE=cloud`` every Vectoree call must use the visitor's own project
key. This middleware resolves the preview cookie, exposes it on
``request.state.preview`` and binds its credentials to the ContextVar that the
model factory, catalog and Vectoree client read. Requests without a live
preview are rejected with ``preview_required`` unless the route works without
a project (health, preview entry/status, setup-status, logout).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME, is_valid_internal_auth_token
from app.gateway.request_path import get_request_route_path
from app.gateway.routers.preview import resolve_preview
from deerflow.community.vectoree.credentials import is_cloud_mode, reset_credentials, set_credentials

PREVIEW_REQUIRED = "preview_required"

_PREVIEW_OPTIONAL_PREFIXES: tuple[str, ...] = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/preview/",
    "/api/webhooks/",
)
_PREVIEW_OPTIONAL_EXACT: frozenset[str] = frozenset(
    {
        "/api/v1/auth/setup-status",
        "/api/v1/auth/logout",
    }
)


def _preview_optional(path: str) -> bool:
    if path.rstrip("/") in _PREVIEW_OPTIONAL_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in _PREVIEW_OPTIONAL_PREFIXES)


def preview_required_response() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": {"code": PREVIEW_REQUIRED, "message": "Open DeerFlow from the Vectoree console Preview button."}},
    )


class PreviewMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not is_cloud_mode():
            return await call_next(request)
        record = await resolve_preview(request)
        if record is None:
            path = get_request_route_path(request)
            if _preview_optional(path) or is_valid_internal_auth_token(request.headers.get(INTERNAL_AUTH_HEADER_NAME)):
                return await call_next(request)
            return preview_required_response()
        token = set_credentials(record.credentials())
        try:
            return await call_next(request)
        finally:
            reset_credentials(token)
