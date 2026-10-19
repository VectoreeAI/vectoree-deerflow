"""Per-request Vectoree credentials: local fallback, cloud isolation, concurrency."""

import asyncio

import pytest

from deerflow.community.vectoree.credentials import (
    VectoreeCredentials,
    bound_credentials,
    current_credentials,
    use_credentials,
)


@pytest.fixture(autouse=True)
def _server_key(monkeypatch):
    monkeypatch.setenv("VECTOREE_API_KEY", "sk-server")
    monkeypatch.setenv("VECTOREE_API_URL", "https://vectoree.net/")


def test_local_mode_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "local")

    assert current_credentials() == VectoreeCredentials(api_url="https://vectoree.net", api_key="sk-server")
    assert bound_credentials() is None


def test_local_mode_without_key_has_no_credentials(monkeypatch):
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    monkeypatch.delenv("VECTOREE_API_KEY")

    assert current_credentials() is None


def test_cloud_mode_never_uses_the_server_key(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "cloud")

    assert current_credentials() is None


def test_bound_credentials_win_in_both_modes(monkeypatch):
    preview = VectoreeCredentials(api_url="https://vectoree.ai", api_key="sk-a", project_id="proj-a")
    for mode in ("local", "cloud"):
        monkeypatch.setenv("DEPLOY_MODE", mode)
        with use_credentials(preview):
            assert current_credentials() == preview
        assert bound_credentials() is None


def test_concurrent_tasks_do_not_share_credentials(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "cloud")

    async def visitor(name: str) -> list[str]:
        seen = []
        with use_credentials(VectoreeCredentials(api_url="https://vectoree.ai", api_key=f"sk-{name}", project_id=name)):
            for _ in range(5):
                await asyncio.sleep(0)
                seen.append(current_credentials().api_key)
        return seen

    async def main():
        return await asyncio.gather(visitor("a"), visitor("b"))

    seen_a, seen_b = asyncio.run(main())

    assert set(seen_a) == {"sk-a"}
    assert set(seen_b) == {"sk-b"}


def test_context_round_trip():
    original = VectoreeCredentials(api_url="https://vectoree.ai", api_key="sk-a", project_id="proj-a")

    assert VectoreeCredentials.from_context(original.to_context()) == original
    assert VectoreeCredentials.from_context(original) is original
    assert VectoreeCredentials.from_context({"api_key": " "}) is None
    assert VectoreeCredentials.from_context("sk-a") is None
    assert VectoreeCredentials.from_context({"api_key": "sk-b"}).api_url == "https://vectoree.ai"
