"""The bash tool hands generation skills the run's Vectoree project key."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deerflow.community.vectoree.credentials import RUN_CONTEXT_KEY, VectoreeCredentials
from deerflow.sandbox.env_policy import build_sandbox_env
from deerflow.sandbox.tools import bash_tool

SKILL_COMMAND = "python /mnt/skills/public/image-generation/scripts/generate.py --prompt cat"
PREVIEW = VectoreeCredentials(api_url="https://vectoree.net", api_key="sk-preview", project_id="p").to_context()


def _run(monkeypatch: pytest.MonkeyPatch, command: str, context: dict) -> dict:
    runtime = SimpleNamespace(state={"sandbox": {"sandbox_id": "aio:xyz"}}, context={"thread_id": "t1", **context}, config={})
    captured: dict = {}

    class _Sandbox:
        def execute_command(self, command, env=None, timeout=None):
            captured["env"] = env
            return "done"

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: _Sandbox())
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    bash_tool.func(runtime=runtime, description="run", command=command)
    return captured


def test_skill_command_receives_preview_key(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "cloud")
    monkeypatch.setenv("VECTOREE_API_KEY", "sk-server")

    env = _run(monkeypatch, SKILL_COMMAND, {RUN_CONTEXT_KEY: PREVIEW})["env"]

    assert env == {"VECTOREE_API_KEY": "sk-preview", "VECTOREE_API_URL": "https://vectoree.net"}


def test_local_skill_command_receives_linked_key(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "local")
    monkeypatch.setenv("VECTOREE_API_KEY", "sk-linked")
    monkeypatch.setenv("VECTOREE_API_URL", "https://vectoree.ai")

    env = _run(monkeypatch, SKILL_COMMAND, {})["env"]

    assert env == {"VECTOREE_API_KEY": "sk-linked", "VECTOREE_API_URL": "https://vectoree.ai"}


def test_cloud_without_preview_gets_no_server_key(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "cloud")
    monkeypatch.setenv("VECTOREE_API_KEY", "sk-server")

    assert _run(monkeypatch, SKILL_COMMAND, {})["env"] is None


def test_plain_aio_command_keeps_the_persistent_shell(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "cloud")

    assert _run(monkeypatch, "ls", {RUN_CONTEXT_KEY: PREVIEW})["env"] is None


def test_other_secrets_stay_filtered(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("VECTOREE_API_KEY", "sk-server")

    env = build_sandbox_env({"VECTOREE_API_KEY": "sk-preview", "VECTOREE_API_URL": "https://vectoree.net"})

    assert env["VECTOREE_API_KEY"] == "sk-preview"
    assert "OPENAI_API_KEY" not in env
