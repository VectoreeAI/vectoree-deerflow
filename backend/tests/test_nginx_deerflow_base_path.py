"""The cloud site lives under ``/deerflow``; nginx must route the prefix.

The shared-domain reverse proxy forwards ``/deerflow/*`` without stripping it.
The frontend keeps the prefix (Next ``basePath``), Gateway routes have none,
and the preview entry ``/deerflow?ticket=…`` must reach the redeem endpoint.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIGS = ("docker/nginx/nginx.conf", "docker/nginx/nginx.local.conf")


def _location(config: str, matcher: str) -> str:
    match = re.search(rf"location {re.escape(matcher)} \{{(.*?)\n        \}}", config, re.S)
    assert match, f"missing location {matcher}"
    return match.group(1)


@pytest.fixture(params=NGINX_CONFIGS)
def config(request) -> str:
    return (REPO_ROOT / request.param).read_text(encoding="utf-8")


@pytest.mark.parametrize("matcher", ["= /deerflow", "= /deerflow/"])
def test_preview_entry_rewrites_tickets_to_the_redeem_endpoint(config, matcher):
    body = _location(config, matcher)
    assert re.search(r"if \(\$arg_ticket\) \{\s*rewrite \^ /api/v1/preview/enter last;\s*\}", body)
    assert re.search(r"proxy_pass http://\$?frontend", body)


def test_prefixed_vectoree_routes_stay_on_the_frontend(config):
    body = _location(config, "^~ /deerflow/api/vectoree/")
    assert re.search(r"proxy_pass http://\$?frontend", body)


def test_prefixed_api_is_stripped_and_rematched(config):
    body = _location(config, "^~ /deerflow/api/")
    assert "rewrite ^/deerflow(/api/.*)$ $1 last;" in body
    assert "proxy_pass" not in body
