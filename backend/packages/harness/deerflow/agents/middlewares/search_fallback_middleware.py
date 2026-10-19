"""Append recent search results when a paired page-fetch tool returns empty content."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.message_utils import is_genuine_user_message
from deerflow.agents.middlewares.tool_transform_meta import append_tool_transform

_WEB_FETCH_TOOL = "web_fetch"
_WEB_SEARCH_TOOL = "web_search"
# Each fetch tool only attaches snippets from its own search tool. A Vectoree
# fetch must not pick up a historical web_search result, and the reverse.
_FETCH_TO_SEARCH = {
    _WEB_FETCH_TOOL: _WEB_SEARCH_TOOL,
    "web-fetch": "web-search",
}
_MAX_FALLBACK_CHARS = 8192
_FALLBACK_HEADER = "## Search results (fallback because fetch returned no content)"


def _suggest_search(search_tool_name: str) -> str:
    return f"Page extract returned no content. Call `{search_tool_name}` with the user's topic before answering."


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def is_empty_web_fetch_content(content: object) -> bool:
    """Return True when every extract row in a web_fetch payload has empty raw_content."""
    text = _message_text(content).strip()
    if not text:
        return True
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return not text
    if not isinstance(data, dict):
        return not text
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return True
    saw_row = False
    for item in results:
        if not isinstance(item, dict):
            continue
        saw_row = True
        raw = item.get("raw_content", "")
        if isinstance(raw, str) and raw.strip():
            return False
    return saw_row or not text


def _latest_user_turn_start(messages: list[object]) -> int:
    latest = -1
    for index, message in enumerate(messages):
        if is_genuine_user_message(message):
            latest = index
    return latest


def find_recent_web_search_content(messages: list[object], search_tool_name: str = _WEB_SEARCH_TOOL) -> str | None:
    """Return the latest matching search ToolMessage content in the current user turn."""
    turn_start = _latest_user_turn_start(messages)
    turn_messages = messages[turn_start + 1 :] if turn_start >= 0 else messages
    for message in reversed(turn_messages):
        if isinstance(message, ToolMessage) and message.name == search_tool_name:
            text = _message_text(message.content).strip()
            if text:
                return text
    return None


def build_search_fallback_content(original: str, search_content: str | None, search_tool_name: str = _WEB_SEARCH_TOOL) -> str:
    """Merge fetch output with search fallback guidance for the model."""
    if search_content:
        clipped = search_content[:_MAX_FALLBACK_CHARS]
        suffix = "…" if len(search_content) > _MAX_FALLBACK_CHARS else ""
        return f"{original.rstrip()}\n\n{_FALLBACK_HEADER}\n\n{clipped}{suffix}\n\nUse the search snippets above to answer the user even though page extract failed."
    return f"{original.rstrip()}\n\n{_suggest_search(search_tool_name)}"


def augment_empty_fetch_message(message: ToolMessage, messages: list[object]) -> ToolMessage:
    search_tool_name = _FETCH_TO_SEARCH.get(message.name or "")
    if search_tool_name is None:
        return message
    if not is_empty_web_fetch_content(message.content):
        return message
    original = _message_text(message.content)
    merged = build_search_fallback_content(original, find_recent_web_search_content(messages, search_tool_name), search_tool_name)
    kwargs = dict(message.additional_kwargs or {})
    append_tool_transform(kwargs, "search_fallback", by="SearchFallbackMiddleware")
    return message.model_copy(update={"content": merged, "additional_kwargs": kwargs})


def _augment_result(result: ToolMessage | Command, messages: list[object]) -> ToolMessage | Command:
    if isinstance(result, ToolMessage):
        return augment_empty_fetch_message(result, messages)
    update = getattr(result, "update", None)
    if not isinstance(update, dict):
        return result
    nested_messages = update.get("messages")
    if not isinstance(nested_messages, list):
        return result
    augmented = [augment_empty_fetch_message(message, messages) if isinstance(message, ToolMessage) else message for message in nested_messages]
    return Command(update={**update, "messages": augmented})


class SearchFallbackMiddleware(AgentMiddleware[AgentState]):
    """When a paired fetch tool is empty, attach the current turn's matching search snippets."""

    def _messages(self, request: ToolCallRequest) -> list[object]:
        state = request.state or {}
        messages = state.get("messages")
        if isinstance(messages, list):
            return messages
        runtime_messages = getattr(request, "messages", None)
        if isinstance(runtime_messages, list):
            return runtime_messages
        return []

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") not in _FETCH_TO_SEARCH:
            return handler(request)
        return _augment_result(handler(request), self._messages(request))

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") not in _FETCH_TO_SEARCH:
            return await handler(request)
        return _augment_result(await handler(request), self._messages(request))
