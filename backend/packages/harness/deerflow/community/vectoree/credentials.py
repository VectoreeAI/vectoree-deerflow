"""Per-request Vectoree project credentials.

Cloud deployments serve many Vectoree projects from one process, so the project
key cannot live in ``os.environ``. The Gateway resolves the visitor's preview and
binds it to a ContextVar for the request or run; every Vectoree caller reads
``current_credentials()`` instead of the environment.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

DEFAULT_API_URL = "https://vectoree.ai"
RUN_CONTEXT_KEY = "__vectoree_credentials"


@dataclass(frozen=True)
class VectoreeCredentials:
    api_url: str
    api_key: str
    project_id: str = ""

    def to_context(self) -> dict[str, str]:
        return {"api_url": self.api_url, "api_key": self.api_key, "project_id": self.project_id}

    @classmethod
    def from_context(cls, value: Any) -> VectoreeCredentials | None:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            return None
        api_key = str(value.get("api_key") or "").strip()
        if not api_key:
            return None
        api_url = normalize_api_url(str(value.get("api_url") or ""))
        return cls(api_url=api_url, api_key=api_key, project_id=str(value.get("project_id") or ""))


_current: ContextVar[VectoreeCredentials | None] = ContextVar("vectoree_credentials", default=None)


def normalize_api_url(value: str | None) -> str:
    return (value or "").strip().rstrip("/") or DEFAULT_API_URL


def is_cloud_mode(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return source.get("DEPLOY_MODE", "").strip().lower() == "cloud"


def bound_credentials() -> VectoreeCredentials | None:
    """Return only the credentials bound to this context, never the environment."""
    return _current.get()


def current_credentials() -> VectoreeCredentials | None:
    """Return the credentials for this request or run.

    Cloud mode only trusts the bound preview; the server's ``VECTOREE_API_KEY``
    must never stand in for a visitor. Local mode falls back to the environment.
    """
    bound = _current.get()
    if bound is not None:
        return bound
    if is_cloud_mode():
        return None
    api_key = os.environ.get("VECTOREE_API_KEY", "").strip()
    if not api_key:
        return None
    return VectoreeCredentials(api_url=normalize_api_url(os.environ.get("VECTOREE_API_URL")), api_key=api_key)


def set_credentials(credentials: VectoreeCredentials | None) -> Token:
    return _current.set(credentials)


def reset_credentials(token: Token) -> None:
    _current.reset(token)


@contextmanager
def use_credentials(credentials: VectoreeCredentials | None) -> Iterator[None]:
    token = _current.set(credentials)
    try:
        yield
    finally:
        _current.reset(token)
