"""Tests for SearchFallbackMiddleware empty web_fetch recovery."""

from __future__ import annotations

import json
from types import SimpleNamespace

from langchain_core.messages import HumanMessage, ToolMessage

from deerflow.agents.middlewares.search_fallback_middleware import (
    SearchFallbackMiddleware,
    augment_empty_fetch_message,
    build_search_fallback_content,
    find_recent_web_search_content,
    is_empty_web_fetch_content,
)


def _fetch_payload(*, raw: str = "") -> str:
    return json.dumps({"results": [{"url": "https://example.com", "raw_content": raw}]})


def _search_payload() -> str:
    return json.dumps(
        {
            "query": "today AI news",
            "results": [
                {"title": "AI headline", "url": "https://news.example/a", "snippet": "Breaking AI news"},
            ],
        }
    )


class TestEmptyFetchDetection:
    def test_empty_raw_content_is_empty_fetch(self):
        assert is_empty_web_fetch_content(_fetch_payload(raw=""))

    def test_non_empty_raw_content_is_not_empty_fetch(self):
        assert not is_empty_web_fetch_content(_fetch_payload(raw="Hello world"))


class TestSearchFallbackHelpers:
    def test_find_recent_web_search_in_current_turn(self):
        messages = [
            HumanMessage(content="older turn"),
            ToolMessage(content=_search_payload(), tool_call_id="s0", name="web_search"),
            HumanMessage(content="today AI news"),
            ToolMessage(content=_search_payload(), tool_call_id="s1", name="web_search"),
        ]
        assert find_recent_web_search_content(messages) == _search_payload()

    def test_find_recent_web_search_ignores_previous_turn(self):
        messages = [
            HumanMessage(content="older turn"),
            ToolMessage(content=_search_payload(), tool_call_id="s0", name="web_search"),
            HumanMessage(content="new question"),
        ]
        assert find_recent_web_search_content(messages) is None

    def test_build_fallback_with_search(self):
        merged = build_search_fallback_content(_fetch_payload(), _search_payload())
        assert "Search results (fallback because fetch returned no content)" in merged
        assert "Breaking AI news" in merged

    def test_build_fallback_without_search(self):
        merged = build_search_fallback_content(_fetch_payload(), None)
        assert "Call `web_search`" in merged


class TestSearchFallbackMiddleware:
    def test_wrap_tool_call_appends_search_for_empty_fetch(self):
        middleware = SearchFallbackMiddleware()
        request = SimpleNamespace(
            tool_call={"name": "web_fetch", "id": "f1"},
            state={
                "messages": [
                    HumanMessage(content="today AI news"),
                    ToolMessage(content=_search_payload(), tool_call_id="s1", name="web_search"),
                ]
            },
        )
        result = middleware.wrap_tool_call(
            request,
            lambda _: ToolMessage(content=_fetch_payload(), tool_call_id="f1", name="web_fetch"),
        )
        assert isinstance(result, ToolMessage)
        assert "Breaking AI news" in result.content
        assert "deerflow_tool_transforms" in result.additional_kwargs

    def test_wrap_tool_call_skips_non_fetch_tools(self):
        middleware = SearchFallbackMiddleware()
        request = SimpleNamespace(tool_call={"name": "web_search", "id": "s1"}, state={"messages": []})
        original = ToolMessage(content="unchanged", tool_call_id="s1", name="web_search")
        result = middleware.wrap_tool_call(request, lambda _: original)
        assert result is original

    def test_augment_empty_fetch_without_prior_search(self):
        message = ToolMessage(content=_fetch_payload(), tool_call_id="f1", name="web_fetch")
        augmented = augment_empty_fetch_message(message, [HumanMessage(content="today AI news")])
        assert "Call `web_search`" in augmented.content

    def test_vectoree_fetch_attaches_only_vectoree_search(self):
        message = ToolMessage(content=_fetch_payload(), tool_call_id="f1", name="web-fetch")
        messages = [
            HumanMessage(content="today AI news"),
            ToolMessage(content=_search_payload(), tool_call_id="s1", name="web-search"),
        ]
        augmented = augment_empty_fetch_message(message, messages)
        assert "Breaking AI news" in augmented.content

    def test_cross_provider_search_is_not_attached(self):
        vectoree_fetch = ToolMessage(content=_fetch_payload(), tool_call_id="f1", name="web-fetch")
        historical_search = [
            HumanMessage(content="today AI news"),
            ToolMessage(content=_search_payload(), tool_call_id="s1", name="web_search"),
        ]
        vectoree_only = augment_empty_fetch_message(vectoree_fetch, historical_search)
        assert "Breaking AI news" not in vectoree_only.content
        assert "Call `web-search`" in vectoree_only.content

        historical_fetch = ToolMessage(content=_fetch_payload(), tool_call_id="f2", name="web_fetch")
        vectoree_search = [
            HumanMessage(content="today AI news"),
            ToolMessage(content=_search_payload(), tool_call_id="s2", name="web-search"),
        ]
        historical_only = augment_empty_fetch_message(historical_fetch, vectoree_search)
        assert "Breaking AI news" not in historical_only.content
        assert "Call `web_search`" in historical_only.content
