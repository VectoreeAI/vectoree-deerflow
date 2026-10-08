from __future__ import annotations

import json

import pytest

from app.gateway.vectoree_project import store_vectoree_project

CREDENTIALS = {
    "apiUrl": "https://vectoree.ai",
    "apiKey": "sk-ve-v1-minted",
    "apiBase": "https://vectoree.ai/api/v1",
    "accessToken": "jwt-secret",
    "refreshToken": "refresh-secret",
    "projectId": "11111111-1111-4111-8111-111111111111",
    "projectName": "Demo",
}


def test_store_vectoree_project_writes_inside_the_container_project(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER=keep\n", encoding="utf-8")

    store_vectoree_project(tmp_path, CREDENTIALS)

    config = json.loads((tmp_path / ".vectoree" / "config.json").read_text(encoding="utf-8"))
    env_text = env_file.read_text(encoding="utf-8")
    assert config["apiKey"] == "sk-ve-v1-minted"
    assert config["accessToken"] == "jwt-secret"
    assert "VECTOREE_API_KEY=sk-ve-v1-minted" in env_text
    assert "VECTOREE_API_URL=https://vectoree.ai" in env_text
    assert "VECTOREE_API_BASE=https://vectoree.ai/api/v1" in env_text
    assert "OTHER=keep" in env_text
    assert "jwt-secret" not in env_text
    assert "refresh-secret" not in env_text


def test_store_vectoree_project_rejects_multiline_values(tmp_path):
    poisoned = {**CREDENTIALS, "apiKey": "sk-ve-v1-minted\nEVIL=1"}
    with pytest.raises(ValueError, match="single line"):
        store_vectoree_project(tmp_path, poisoned)
    assert not (tmp_path / ".env").exists()
