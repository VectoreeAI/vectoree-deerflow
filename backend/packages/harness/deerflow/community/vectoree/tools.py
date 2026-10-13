"""Web search and page extract backed by Vectoree Tool Hub."""

import json

from langchain.tools import tool

from deerflow.community.vectoree.client import EXTRACT_PATH, SEARCH_PATH, post_json
from deerflow.config import get_app_config

_EMPTY_FETCH_MESSAGE = "Page extract returned no content."


def _normalize_extract_payload(payload: dict) -> dict:
    """Mark empty extract rows so agents can distinguish failed fetches from blank pages."""
    results = payload.get("results")
    if not isinstance(results, list):
        return payload
    normalized: list[object] = []
    for item in results:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        entry = dict(item)
        raw = entry.get("raw_content", "")
        if not isinstance(raw, str) or not raw.strip():
            entry["fetch_failed"] = True
            entry["message"] = _EMPTY_FETCH_MESSAGE
        normalized.append(entry)
    return {**payload, "results": normalized}


def _max_results(default: int) -> int:
    config = get_app_config().get_tool_config("web-search")
    if config is None:
        return default
    configured = config.model_extra.get("max_results", default)
    try:
        value = int(configured)
    except (TypeError, ValueError):
        return default
    return value if 1 <= value <= 20 else default


@tool("web-search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = 5) -> str:
    """Search the web using Vectoree Tool Hub.

    Args:
        query: Search keywords describing what you want to find.
        max_results: Maximum number of results to return. Default is 5.
    """
    limit = _max_results(max_results)
    payload = post_json(SEARCH_PATH, {"query": query, "max_results": limit})
    return json.dumps(payload, indent=2, ensure_ascii=False)


@tool("web-fetch", parse_docstring=True)
def web_fetch_tool(url: str) -> str:
    """Fetch the main content of a web page using Vectoree Tool Hub.

    Args:
        url: Absolute URL to extract, including the https:// scheme.
    """
    payload = _normalize_extract_payload(post_json(EXTRACT_PATH, {"urls": [url]}))
    return json.dumps(payload, indent=2, ensure_ascii=False)
