"""Cloud preview entry: redeem a Vectoree ticket for a server-side preview."""

from __future__ import annotations

import logging
import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from starlette.requests import HTTPConnection
from starlette.responses import RedirectResponse

from app.gateway.csrf_middleware import is_secure_request
from app.gateway.preview_store import PREVIEW_COOKIE, PreviewRecord, get_preview_store, valid_preview_id
from app.gateway.public_path import cookie_path, public_path
from deerflow.community.vectoree.credentials import is_cloud_mode, normalize_api_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/preview", tags=["preview"])

REDEEM_PATH = "/api/system/starter/preview/redeem"
_TICKET = re.compile(r"^\S{16,512}$")
_REDEEM_TIMEOUT_SECONDS = 20.0
# The server-side record owns the 12h idle expiry; the cookie only has to outlive it.
PREVIEW_COOKIE_MAX_AGE = 30 * 24 * 60 * 60


class PreviewRedeemError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _require_cloud() -> None:
    if not is_cloud_mode():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


async def redeem_ticket(api_url: str, ticket: str) -> PreviewRecord:
    try:
        async with httpx.AsyncClient(timeout=_REDEEM_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{api_url}{REDEEM_PATH}", json={"ticket": ticket}, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        logger.warning("Vectoree preview redeem unreachable: %s", type(exc).__name__)
        raise PreviewRedeemError("unavailable") from exc
    if 400 <= response.status_code < 500:
        raise PreviewRedeemError("expired")
    if response.status_code >= 300:
        logger.warning("Vectoree preview redeem failed with status %s", response.status_code)
        raise PreviewRedeemError("unavailable")
    try:
        data = response.json()
    except ValueError:
        data = None
    data = data if isinstance(data, dict) else {}
    api_key = data.get("apiKey") if isinstance(data.get("apiKey"), str) else ""
    project_id = str(data.get("projectId") or "").strip()
    organization_id = str(data.get("organizationId") or "").strip()
    if not api_key.startswith("sk-ve-") or not project_id:
        logger.warning("Vectoree preview redeem returned an unexpected body")
        raise PreviewRedeemError("unavailable")
    return PreviewRecord(api_url=api_url, api_key=api_key, project_id=project_id, organization_id=organization_id)


def _expired_redirect(reason: str) -> RedirectResponse:
    target = public_path("/preview-expired")
    if reason != "expired":
        target = f"{target}?reason={reason}"
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND, headers={"Cache-Control": "no-store"})


async def resolve_preview(request: HTTPConnection) -> PreviewRecord | None:
    """Return the request's live preview, refreshing its idle expiry."""
    cached = getattr(request.state, "preview", None)
    if cached is not None:
        return cached
    preview_id = request.cookies.get(PREVIEW_COOKIE)
    if not valid_preview_id(preview_id):
        return None
    record = await get_preview_store().get(preview_id)
    request.state.preview = record
    return record


@router.get("/status")
async def preview_status(request: Request) -> dict[str, bool]:
    _require_cloud()
    return {"active": await resolve_preview(request) is not None}


@router.get("/enter", include_in_schema=False)
async def enter_preview(request: Request, ticket: str | None = None) -> RedirectResponse:
    """Nginx rewrites ``{base}?ticket=…`` here; the ticket never reaches the frontend."""
    _require_cloud()
    if not ticket or not _TICKET.fullmatch(ticket):
        return _expired_redirect("expired")
    api_url = normalize_api_url(os.environ.get("VECTOREE_API_URL"))
    try:
        record = await redeem_ticket(api_url, ticket)
    except PreviewRedeemError as exc:
        return _expired_redirect(exc.reason)
    previous = request.cookies.get(PREVIEW_COOKIE)
    preview_id = await get_preview_store().create(record, replace=previous if valid_preview_id(previous) else None)
    response = RedirectResponse(url=public_path("/login"), status_code=status.HTTP_302_FOUND, headers={"Cache-Control": "no-store"})
    response.set_cookie(
        key=PREVIEW_COOKIE,
        value=preview_id,
        httponly=True,
        secure=is_secure_request(request),
        samesite="lax",
        max_age=PREVIEW_COOKIE_MAX_AGE,
        path=cookie_path(),
    )
    return response
