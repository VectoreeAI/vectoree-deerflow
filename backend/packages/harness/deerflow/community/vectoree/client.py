"""HTTP client for Vectoree Tool Hub. Uses the project API key, never a console accessToken."""

from __future__ import annotations

import os

import httpx

DEFAULT_ORIGIN = "https://vectoree.ai"
SEARCH_PATH = "/api/tools/v1/search"
EXTRACT_PATH = "/api/tools/v1/extract"


class VectoreeConfigError(RuntimeError):
    """Raised when the project API key required to call Vectoree is missing."""


def api_origin() -> str:
    return os.environ.get("VECTOREE_API_URL", DEFAULT_ORIGIN).strip().rstrip("/") or DEFAULT_ORIGIN


def require_api_key() -> str:
    key = os.environ.get("VECTOREE_API_KEY", "").strip()
    if not key:
        raise VectoreeConfigError(
            "VECTOREE_API_KEY is not set. Create a project API key with "
            "`npx @vectoree/cli link` or in the Vectoree dashboard API Keys page. "
            "Do not paste the console accessToken."
        )
    return key


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
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        return payload
    return {"data": payload}
