"""Public URL prefix when the site is mounted below a shared domain.

Cloud deployments live at ``https://<host>/deerflow`` next to Vectoree and the
starter. Nginx strips the prefix before requests reach the Gateway, so any URL
or cookie path the Gateway hands back to the browser must add it again.
"""

from __future__ import annotations

import os

BASE_PATH_ENV = "DEER_FLOW_PUBLIC_BASE_PATH"


def public_base_path() -> str:
    raw = os.environ.get(BASE_PATH_ENV, "").strip().strip("/")
    return f"/{raw}" if raw else ""


def public_path(path: str) -> str:
    """Prefix an absolute site path such as ``/login`` with the public base."""
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{public_base_path()}{path}"


def cookie_path() -> str:
    return public_base_path() or "/"
