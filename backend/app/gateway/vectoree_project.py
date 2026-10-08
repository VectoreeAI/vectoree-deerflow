"""Persist Vectoree link credentials inside this container's project directory."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from deerflow.config.app_config import reload_app_config

_ENV_KEYS = ("VECTOREE_API_URL", "VECTOREE_API_KEY", "VECTOREE_API_BASE")
_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")


def store_vectoree_project(root: Path, credentials: dict[str, str]) -> None:
    """Write `.vectoree/config.json` and the Vectoree keys in `.env`."""
    _reject_unsafe(credentials)
    directory = root / ".vectoree"
    directory.mkdir(mode=0o700, exist_ok=True)
    ordered = {
        key: credentials[key]
        for key in (
            "apiUrl",
            "accessToken",
            "refreshToken",
            "apiKey",
            "projectId",
            "projectName",
            "keyId",
        )
        if credentials.get(key)
    }
    temporary = directory / f".config.json.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(directory / "config.json")
    os.chmod(directory, 0o700)
    os.chmod(directory / "config.json", 0o600)

    env_path = root / ".env"
    current = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    updates = {
        "VECTOREE_API_URL": credentials["apiUrl"],
        "VECTOREE_API_KEY": credentials["apiKey"],
        "VECTOREE_API_BASE": credentials["apiBase"],
    }
    env_path.write_text(_upsert_env(current, updates), encoding="utf-8")
    os.chmod(env_path, 0o600)


def publish_vectoree_project(credentials: dict[str, str]) -> None:
    """Save credentials under DEER_FLOW_PROJECT_ROOT and reload model config."""
    root = Path(os.environ.get("DEER_FLOW_PROJECT_ROOT", "/app")).resolve()
    store_vectoree_project(root, credentials)
    os.environ["DEER_FLOW_DOTENV_PATH"] = str(root / ".env")
    reload_app_config()


def _upsert_env(content: str, updates: dict[str, str]) -> str:
    lines = content.split("\n")
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in lines:
        match = _ENV_LINE.match(line)
        if match is None:
            next_lines.append(line)
            continue
        key = match.group(1)
        value = updates.get(key)
        if value is None:
            next_lines.append(line)
            continue
        seen.add(key)
        next_lines.append(f"{key}={value}")
    for key, value in updates.items():
        if key not in seen:
            next_lines.append(f"{key}={value}")
    while next_lines and next_lines[-1] == "":
        next_lines.pop()
    return "\n".join(next_lines) + "\n"


def _reject_unsafe(credentials: dict[str, str]) -> None:
    required = ("apiUrl", "apiKey", "apiBase", "accessToken", "projectId")
    missing = [key for key in required if not credentials.get(key, "").strip()]
    if missing:
        raise ValueError(f"Missing Vectoree credential fields: {', '.join(missing)}")
    for key in (*required, "refreshToken", "projectName", "keyId", *_ENV_KEYS):
        value = credentials.get(key, "")
        if any(char in value for char in "\n\r\x00"):
            raise ValueError(f"{key} must be a single line")
