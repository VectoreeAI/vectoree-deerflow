"""Read-time overlay of the Vectoree model catalog. Never writes config.yaml."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from deerflow.community.vectoree.client import MODELS_PATH, VectoreeConfigError, api_origin, require_api_key
from deerflow.config.model_config import ModelConfig

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60.0
_FAILURE_TTL_SECONDS = 30.0
_FETCH_TIMEOUT_SECONDS = 5.0
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, list[dict[str, Any]] | None]] = {}


def clear_catalog_cache() -> None:
    with _cache_lock:
        _cache.clear()


def modality_tokens(value: Any) -> set[str]:
    if isinstance(value, str):
        token = value.strip().lower()
        return {token} if token else set()
    if isinstance(value, list):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    return set()


def catalog_model_id(entry: dict[str, Any]) -> str | None:
    for key in ("id", "model"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def is_chat_catalog_entry(entry: dict[str, Any]) -> bool:
    output = modality_tokens(entry.get("outputModality", entry.get("output_modality")))
    if "decisions" in output:
        return False
    return "text" in output


def catalog_supports_vision(entry: dict[str, Any]) -> bool:
    return "image" in modality_tokens(entry.get("inputModality", entry.get("input_modality")))


def deerflow_catalog_name(model_id: str) -> str:
    return model_id.replace("/", "--")


def select_first_model(entries: list[dict[str, Any]], output_tokens: set[str]) -> str | None:
    wanted = {token.lower() for token in output_tokens}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        output = modality_tokens(entry.get("outputModality", entry.get("output_modality")))
        if not output & wanted:
            continue
        model_id = catalog_model_id(entry)
        if model_id:
            return model_id
    return None


def parse_catalog_payload(payload: Any) -> list[dict[str, Any]]:
    rows: Any = payload
    if isinstance(payload, dict):
        for key in ("data", "models", "items"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                rows = candidate
                break
        else:
            return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def fetch_catalog_models() -> list[dict[str, Any]] | None:
    """Return catalog entries, or None when the key is missing or the request fails."""
    try:
        key = require_api_key()
    except VectoreeConfigError:
        return None
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and now - cached[0] < (_CACHE_TTL_SECONDS if cached[1] is not None else _FAILURE_TTL_SECONDS):
            return cached[1]
    entries: list[dict[str, Any]] | None
    try:
        response = httpx.get(
            f"{api_origin()}{MODELS_PATH}",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=_FETCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        entries = parse_catalog_payload(response.json())
    except Exception:
        logger.warning("Vectoree model catalog request failed; using configured models only")
        entries = None
    with _cache_lock:
        _cache[key] = (time.monotonic(), entries)
    return entries


def _vectoree_template(models: list[ModelConfig]) -> ModelConfig | None:
    for model in models:
        if model.name == "vectoree" or model.name.startswith("vectoree-") or str(model.model).startswith("vectoree/"):
            return model
    return None


def overlay_catalog_models(models: list[ModelConfig]) -> list[ModelConfig]:
    """Append chat models from the catalog. YAML entries stay first and are not mutated."""
    template = _vectoree_template(models)
    if template is None:
        return list(models)
    entries = fetch_catalog_models()
    if not entries:
        return list(models)
    template_fields = template.model_dump()
    existing_ids = {model.model for model in models}
    existing_names = {model.name for model in models}
    added: list[ModelConfig] = []
    for entry in entries:
        if not is_chat_catalog_entry(entry):
            continue
        model_id = catalog_model_id(entry)
        if model_id is None or model_id in existing_ids:
            continue
        name = deerflow_catalog_name(model_id)
        if "/" in name or name in existing_names:
            continue
        added.append(
            ModelConfig(
                name=name,
                display_name=model_id,
                description=None,
                use=str(template_fields.get("use") or template.use),
                model=model_id,
                api_key=template_fields.get("api_key"),
                base_url=template_fields.get("base_url"),
                timeout=template_fields.get("timeout"),
                max_retries=template_fields.get("max_retries"),
                supports_vision=catalog_supports_vision(entry),
                supports_thinking=False,
            )
        )
        existing_ids.add(model_id)
        existing_names.add(name)
    return [*models, *added]
