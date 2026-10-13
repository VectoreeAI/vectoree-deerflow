"""Vectoree Google login. Issues a DeerFlow session and discards Vectoree tokens."""

from __future__ import annotations

import logging
import time

import httpx
import jwt
from fastapi import HTTPException, Request, status
from pydantic import BaseModel, Field
from starlette.responses import RedirectResponse

from app.gateway.auth.config import get_auth_config
from app.gateway.auth.oidc_state import compute_code_challenge, generate_code_verifier
from app.gateway.csrf_middleware import _request_origin, is_secure_request
from app.gateway.public_path import public_path
from app.gateway.vectoree_auth import VectoreeLink, resolve_vectoree_link

logger = logging.getLogger(__name__)

GOOGLE_STATE_COOKIE = "df_vectoree_google"
GOOGLE_STATE_MAX_AGE = 300
GOOGLE_STATE_PATH = "/api/v1/auth/vectoree/google/callback"


class GoogleLoginState(BaseModel):
    code_verifier: str
    next_path: str = "/workspace"
    remember_me: bool = True
    issued_at: float = Field(default_factory=time.time)


def _sign(payload: GoogleLoginState) -> str:
    return jwt.encode(payload.model_dump(), get_auth_config().jwt_secret, algorithm="HS256")


def _read_state(request: Request) -> GoogleLoginState | None:
    signed = request.cookies.get(GOOGLE_STATE_COOKIE)
    if not signed:
        return None
    try:
        decoded = jwt.decode(signed, get_auth_config().jwt_secret, algorithms=["HS256"])
        payload = GoogleLoginState(**decoded)
    except jwt.PyJWTError:
        return None
    if time.time() - payload.issued_at > GOOGLE_STATE_MAX_AGE:
        return None
    return payload


def _set_state_cookie(response: RedirectResponse, request: Request, payload: GoogleLoginState) -> None:
    response.set_cookie(
        key=GOOGLE_STATE_COOKIE,
        value=_sign(payload),
        httponly=True,
        secure=is_secure_request(request),
        samesite="lax",
        max_age=GOOGLE_STATE_MAX_AGE,
        path=public_path(GOOGLE_STATE_PATH),
    )


def _clear_state_cookie(response: RedirectResponse, request: Request) -> None:
    response.delete_cookie(
        key=GOOGLE_STATE_COOKIE,
        secure=is_secure_request(request),
        samesite="lax",
        path=public_path(GOOGLE_STATE_PATH),
    )


def _callback_url(request: Request) -> str:
    origin = _request_origin(request)
    if not origin:
        origin = f"{request.url.scheme}://{request.headers.get('host', 'localhost')}"
    return f"{origin}{public_path(GOOGLE_STATE_PATH)}"


async def _auth_url(link: VectoreeLink, redirect_uri: str, challenge: str) -> tuple[str | None, str]:
    """Return ``(auth_url, error_code)``; ``error_code`` is a login-page error key."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{link.api_url}/api/auth/oauth/google",
                params={"redirect_uri": redirect_uri, "code_challenge": challenge},
                headers={"Authorization": f"Bearer {link.api_key}", "Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        logger.warning("Vectoree Google login start failed: %s", exc)
        return None, "google_failed"
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.status_code >= 400:
        code = data.get("error") if isinstance(data, dict) else None
        message = data.get("message") if isinstance(data, dict) else None
        logger.warning("Vectoree Google login start returned %s %s: %s", response.status_code, code, message)
        if code == "AUTH_OAUTH_CONFIG_ERROR":
            return None, "google_not_configured"
        return None, "google_failed"
    auth_url = data.get("authUrl") if isinstance(data, dict) else None
    if isinstance(auth_url, str) and auth_url.startswith(("https://", "http://")):
        return auth_url, ""
    return None, "google_failed"


async def _exchange_email(link: VectoreeLink, code: str, verifier: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{link.api_url}/api/auth/oauth/exchange",
                params={"client_type": "server"},
                json={"code": code, "code_verifier": verifier},
                headers={
                    "Authorization": f"Bearer {link.api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError:
        return None
    if response.status_code >= 400:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    user = data.get("user") if isinstance(data, dict) else None
    email = user.get("email") if isinstance(user, dict) else None
    if isinstance(email, str) and email.strip():
        return email.strip()
    return None


def _failure(request: Request, error_code: str = "google_failed") -> RedirectResponse:
    from app.gateway.routers.auth import _build_error_redirect

    response = RedirectResponse(_build_error_redirect(None, error_code), status_code=status.HTTP_302_FOUND)
    _clear_state_cookie(response, request)
    return response


async def start_google_login(request: Request, next_path: str | None, remember_me: bool) -> RedirectResponse:
    link = resolve_vectoree_link()
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vectoree is not linked")
    from app.gateway.routers.auth import validate_next_param

    verifier = generate_code_verifier()
    auth_url, error_code = await _auth_url(link, _callback_url(request), compute_code_challenge(verifier))
    if not auth_url:
        return _failure(request, error_code)
    response = RedirectResponse(auth_url, status_code=status.HTTP_302_FOUND)
    _set_state_cookie(
        response,
        request,
        GoogleLoginState(
            code_verifier=verifier,
            next_path=validate_next_param(next_path) or "/workspace",
            remember_me=remember_me,
        ),
    )
    return response


async def finish_google_login(request: Request, vectoree_code: str | None, error: str | None) -> RedirectResponse:
    if error or not vectoree_code:
        return _failure(request)
    state = _read_state(request)
    link = resolve_vectoree_link()
    if state is None or link is None:
        return _failure(request)
    email = await _exchange_email(link, vectoree_code, state.code_verifier)
    if not email:
        return _failure(request)
    from app.gateway.routers.auth import _issue_session, _set_csrf_cookie, _upsert_vectoree_user

    user = await _upsert_vectoree_user(email)
    response = RedirectResponse(public_path(state.next_path), status_code=status.HTTP_302_FOUND)
    _issue_session(user, request, response, state.remember_me)
    _set_csrf_cookie(response, request)
    _clear_state_cookie(response, request)
    return response
