"""Proxy DeerFlow login to the linked Vectoree Auth API.

The project API key stays on the server. Vectoree user tokens are read only
to decide whether a DeerFlow session may be issued; they are not returned.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

_DEFAULT_API_URL = "https://vectoree.ai"
_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_OTP = re.compile(r"^\d{8}$")

AUTH_PATHS = {
    "register": "/api/auth/users",
    "login": "/api/auth/sessions",
    "verify": "/api/auth/email/verify",
    "resend": "/api/auth/email/send-verification",
    "methods": "/api/auth/methods",
}


@dataclass(frozen=True)
class VectoreeLink:
    api_url: str
    api_key: str


@dataclass(frozen=True)
class AuthProxyResult:
    kind: Literal["session", "verify", "ok", "error"]
    http_status: int
    email: str | None = None
    message: str = ""
    code_length: int | None = None


def resolve_vectoree_link(env: Mapping[str, str] | None = None) -> VectoreeLink | None:
    """Return the project link when a non-empty project key is available."""
    source = env if env is not None else os.environ
    for root in _candidate_roots(source):
        file_env = _read_env_file(root / ".env")
        config = _read_config(root / ".vectoree" / "config.json")
        key = _first_nonempty(
            source.get("VECTOREE_API_KEY"),
            config.get("apiKey"),
            file_env.get("VECTOREE_API_KEY"),
        )
        if not key:
            continue
        api_url = _first_nonempty(
            source.get("VECTOREE_API_URL"),
            config.get("apiUrl"),
            file_env.get("VECTOREE_API_URL"),
            _DEFAULT_API_URL,
        )
        return VectoreeLink(api_url=api_url.rstrip("/"), api_key=key)
    return None


def sanitize_auth_body(action: str, body: Mapping[str, Any]) -> dict[str, str]:
    email = str(body.get("email") or body.get("username") or "").strip()
    if not email:
        raise ValueError("email is required")
    if action == "verify":
        otp = str(body.get("otp") or "").strip()
        if not _OTP.fullmatch(otp):
            raise ValueError("otp must be 8 digits")
        return {"email": email, "otp": otp}
    if action == "resend":
        return {"email": email}
    password = body.get("password")
    if not isinstance(password, str) or not password:
        raise ValueError("password is required")
    payload = {"email": email, "password": password}
    name = body.get("name")
    if action == "register" and isinstance(name, str) and name.strip():
        payload["name"] = name.strip()
    return payload


async def proxy_vectoree_auth(link: VectoreeLink, action: str, body: Mapping[str, Any] | None = None) -> AuthProxyResult:
    """Call Vectoree auth and return a result that contains no tokens."""
    path = AUTH_PATHS[action]
    payload = sanitize_auth_body(action, body or {}) if action != "methods" else None
    url = f"{link.api_url}{path}"
    if action != "methods":
        url = f"{url}?client_type=server"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.request(
                "GET" if action == "methods" else "POST",
                url,
                headers={
                    "Authorization": f"Bearer {link.api_key}",
                    "Accept": "application/json",
                    **({"Content-Type": "application/json"} if payload is not None else {}),
                },
                json=payload,
            )
    except httpx.HTTPError:
        return AuthProxyResult(kind="error", http_status=502, message="Could not reach Vectoree")

    data = _read_json(response)
    if action == "methods":
        if response.status_code >= 400:
            return AuthProxyResult(kind="error", http_status=response.status_code, message="Could not load auth methods")
        length = data.get("codeLength") if isinstance(data, dict) else None
        return AuthProxyResult(kind="ok", http_status=200, code_length=length if isinstance(length, int) else 8)
    if action == "resend":
        if response.status_code >= 400:
            return AuthProxyResult(kind="error", http_status=response.status_code, message="Could not resend the code")
        return AuthProxyResult(kind="ok", http_status=200, message="ok")
    return _interpret_auth(action, response.status_code, data)


def _interpret_auth(action: str, status: int, data: Any) -> AuthProxyResult:
    if _needs_email_verification(status, data):
        return AuthProxyResult(
            kind="verify",
            http_status=200,
            message="Enter the 8-digit code sent to your email.",
        )
    email = _read_email(data)
    if 200 <= status < 300 and email and _has_access_token(data):
        return AuthProxyResult(kind="session", http_status=200, email=email)
    if action == "login":
        return AuthProxyResult(kind="error", http_status=401, message="Incorrect email or password")
    if action == "verify":
        return AuthProxyResult(kind="error", http_status=400, message="Invalid verification code")
    if status in {400, 409}:
        return AuthProxyResult(kind="error", http_status=400, message="Email already registered")
    return AuthProxyResult(kind="error", http_status=400, message="Could not create the account")


def _needs_email_verification(status: int, data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("requireEmailVerification") is True:
        return True
    return status == 403 and data.get("error") == "AUTH_NEED_VERIFICATION"


def _has_access_token(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("accessToken"), str) and bool(data.get("accessToken"))


def _read_email(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    user = data.get("user")
    if not isinstance(user, dict):
        return None
    email = user.get("email")
    if isinstance(email, str) and email.strip():
        return email.strip()
    return None


def _read_json(response: httpx.Response) -> Any:
    text = response.text
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _candidate_roots(env: Mapping[str, str]) -> list[Path]:
    raw = [
        env.get("DEER_FLOW_PROJECT_ROOT", ""),
        "/app",
        str(Path.cwd()),
        str(Path.cwd().parent),
    ]
    roots: list[Path] = []
    seen: set[str] = set()
    for item in raw:
        text = item.strip()
        if not text:
            continue
        resolved = str(Path(text).resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(Path(resolved))
    return roots


def _read_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for source, target in (("apiKey", "apiKey"), ("api_key", "apiKey"), ("apiUrl", "apiUrl"), ("api_url", "apiUrl")):
        value = raw.get(source)
        if isinstance(value, str) and value.strip() and target not in out:
            out[target] = value.strip()
    return out


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LINE.match(stripped)
        if match is None:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        out[match.group(1)] = value
    return out


def _first_nonempty(*values: str | None) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
