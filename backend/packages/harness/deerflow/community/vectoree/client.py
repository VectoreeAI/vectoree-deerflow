"""HTTP client for Vectoree Tool Hub. Uses the project API key, never a console accessToken."""

from __future__ import annotations

import logging
import os

import httpx

from deerflow.community.vectoree.credentials import DEFAULT_API_URL, current_credentials, is_cloud_mode, normalize_api_url

logger = logging.getLogger(__name__)

DEFAULT_ORIGIN = DEFAULT_API_URL
RUN_PATH = "/api/tools/v1/vectoree.search/run"
MODELS_PATH = "/api/v1/models"
_WRAPPER_KEYS = ("output", "data", "result")
_ERROR_DETAIL_MAX_CHARS = 300


class VectoreeConfigError(RuntimeError):
    """Raised when the project API key required to call Vectoree is missing."""


class VectoreeToolError(RuntimeError):
    """Raised when Vectoree rejects a tool call; carries Vectoree's reason so the agent can adjust."""


def api_origin() -> str:
    credentials = current_credentials()
    if credentials is not None:
        return credentials.api_url
    return normalize_api_url(os.environ.get("VECTOREE_API_URL"))


def require_api_key() -> str:
    credentials = current_credentials()
    if credentials is not None:
        return credentials.api_key
    if is_cloud_mode():
        raise VectoreeConfigError("No active Vectoree preview. Reopen DeerFlow from the Vectoree console Preview button.")
    raise VectoreeConfigError("VECTOREE_API_KEY is not set. Create a project API key with `npx @vectoree/cli link` or in the Vectoree dashboard API Keys page. Do not paste the console accessToken.")


def post_json(path: str, body: dict) -> dict:
    key = require_api_key()
    url = f"{api_origin()}{path}"
    response = httpx.post(
        url,
        json=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    if response.status_code >= 400:
        detail = _error_detail(response)
        logger.warning(
            "Vectoree tool call failed: path=%s status=%s server=%s cf-ray=%s content-type=%s detail=%s",
            path,
            response.status_code,
            response.headers.get("server", ""),
            response.headers.get("cf-ray", ""),
            response.headers.get("content-type", ""),
            detail,
        )
        raise VectoreeToolError(f"Vectoree returned {response.status_code}: {detail}")
    payload = response.json()
    if isinstance(payload, dict):
        return unwrap_tool_payload(payload)
    return {"data": payload}


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("message"), str) and body["message"].strip():
        detail = body["message"].strip()
    else:
        detail = (response.text or "").strip() or "empty response body"
    return detail[:_ERROR_DETAIL_MAX_CHARS]


def unwrap_tool_payload(payload: dict) -> dict:
    """Return the search/extract body when the run endpoint wraps it."""
    if "results" in payload or "query" in payload:
        return payload
    for key in _WRAPPER_KEYS:
        inner = payload.get(key)
        if isinstance(inner, dict) and ("results" in inner or "query" in inner):
            return inner
    return payload
