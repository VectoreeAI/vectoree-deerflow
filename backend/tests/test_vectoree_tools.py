"""Vectoree Tool Hub client used by the default web_search and web_fetch tools."""

import json

import pytest

from deerflow.community.vectoree.client import EXTRACT_PATH, SEARCH_PATH, VectoreeConfigError, post_json
from deerflow.community.vectoree.tools import web_fetch_tool, web_search_tool


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_vectoree_tool_names_and_search_body(monkeypatch):
    from types import SimpleNamespace

    assert web_search_tool.name == "web-search"
    assert web_fetch_tool.name == "web-fetch"
    monkeypatch.setenv("VECTOREE_API_KEY", "sk-ve-v1-test")
    monkeypatch.setenv("VECTOREE_API_URL", "https://vectoree.ai")
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return _Response({"query": json["query"], "results": [{"title": "ok"}]})

    looked_up = {}

    def get_tool_config(name):
        looked_up["name"] = name
        return SimpleNamespace(model_extra={"max_results": 3})

    monkeypatch.setattr("deerflow.community.vectoree.client.httpx.post", fake_post)
    monkeypatch.setattr("deerflow.community.vectoree.tools.get_app_config", lambda: SimpleNamespace(get_tool_config=get_tool_config))
    payload = json.loads(web_search_tool.invoke({"query": "vectoree", "max_results": 5}))

    assert looked_up["name"] == "web-search"
    assert captured["json"] == {"query": "vectoree", "max_results": 3}
    assert payload["query"] == "vectoree"


def test_search_posts_project_api_key(monkeypatch):
    monkeypatch.setenv("VECTOREE_API_KEY", "sk-ve-v1-test")
    monkeypatch.setenv("VECTOREE_API_URL", "https://vectoree.ai")
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _Response({"query": json["query"], "results": []})

    monkeypatch.setattr("deerflow.community.vectoree.client.httpx.post", fake_post)
    body = post_json(SEARCH_PATH, {"query": "vectoree", "max_results": 5})

    assert captured["url"] == "https://vectoree.ai/api/tools/v1/search"
    assert captured["headers"]["Authorization"] == "Bearer sk-ve-v1-test"
    assert captured["json"] == {"query": "vectoree", "max_results": 5}
    assert body["query"] == "vectoree"


def test_extract_posts_project_api_key(monkeypatch):
    monkeypatch.setenv("VECTOREE_API_KEY", "sk-ve-v1-test")
    monkeypatch.delenv("VECTOREE_API_URL", raising=False)
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _Response({"results": []})

    monkeypatch.setattr("deerflow.community.vectoree.client.httpx.post", fake_post)
    post_json(EXTRACT_PATH, {"urls": ["https://example.com"]})

    assert captured["url"] == "https://vectoree.ai/api/tools/v1/extract"
    assert captured["headers"]["Authorization"] == "Bearer sk-ve-v1-test"
    assert captured["json"]["urls"] == ["https://example.com"]


def test_web_fetch_marks_empty_extract_as_failed(monkeypatch):
    monkeypatch.setenv("VECTOREE_API_KEY", "sk-ve-v1-test")

    def fake_post(*_args, **_kwargs):
        return _Response({"results": [{"url": "https://example.com", "raw_content": ""}]})

    monkeypatch.setattr("deerflow.community.vectoree.client.httpx.post", fake_post)
    payload = json.loads(web_fetch_tool.invoke({"url": "https://example.com"}))
    row = payload["results"][0]
    assert row["fetch_failed"] is True
    assert row["message"] == "Page extract returned no content."


def test_missing_key_does_not_call_upstream(monkeypatch):
    monkeypatch.delenv("VECTOREE_API_KEY", raising=False)
    called = {"n": 0}

    def fake_post(*_args, **_kwargs):
        called["n"] += 1
        raise AssertionError("upstream should not be called")

    monkeypatch.setattr("deerflow.community.vectoree.client.httpx.post", fake_post)
    with pytest.raises(VectoreeConfigError, match="VECTOREE_API_KEY"):
        post_json(SEARCH_PATH, {"query": "x", "max_results": 1})
    assert called["n"] == 0
