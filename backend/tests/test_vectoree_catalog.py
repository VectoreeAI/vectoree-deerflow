"""Vectoree model catalog overlay."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.deps import get_config
from app.gateway.routers.models import router
from deerflow.community.vectoree.catalog import clear_catalog_cache, overlay_catalog_models
from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.models.factory import create_chat_model


def _yaml_models() -> list[ModelConfig]:
    return [
        ModelConfig(
            name="vectoree",
            display_name="Vectoree",
            use="langchain_openai:ChatOpenAI",
            model="vectoree/auto",
            api_key="sk-ve-v1-test",
            base_url="https://vectoree.ai/api/v1",
            supports_vision=True,
        ),
        ModelConfig(
            name="vectoree-deepseek-v4-pro",
            display_name="vectoree-deepseek-v4-pro",
            use="langchain_openai:ChatOpenAI",
            model="deepseek/deepseek-v4-pro",
            api_key="sk-ve-v1-test",
            base_url="https://vectoree.ai/api/v1",
            supports_vision=False,
        ),
    ]


def _catalog():
    return [
        {"id": "deepseek/deepseek-v4-pro", "inputModality": ["text"], "outputModality": ["text"]},
        {"id": "openai/gpt-4o", "inputModality": ["text", "image"], "outputModality": "text"},
        {"id": "provider/decider", "inputModality": ["text"], "outputModality": ["decisions"]},
        {"id": "provider/text-only", "inputModality": "text", "outputModality": ["text"]},
    ]


def _config() -> AppConfig:
    return AppConfig(models=_yaml_models(), sandbox=SandboxConfig(use="test"))


def test_overlay_adds_text_models_and_skips_duplicates(monkeypatch):
    monkeypatch.setenv("VECTOREE_API_KEY", "sk-ve-v1-test")
    clear_catalog_cache()
    monkeypatch.setattr("deerflow.community.vectoree.catalog.fetch_catalog_models", lambda: _catalog())
    original = _yaml_models()
    merged = overlay_catalog_models(original)

    assert [model.name for model in original] == ["vectoree", "vectoree-deepseek-v4-pro"]
    names = [model.name for model in merged]
    assert names[0] == "vectoree"
    assert "openai--gpt-4o" in names
    assert "provider--text-only" in names
    assert "provider--decider" not in names
    assert names.count("vectoree-deepseek-v4-pro") == 1
    vision = next(model for model in merged if model.name == "openai--gpt-4o")
    text_only = next(model for model in merged if model.name == "provider--text-only")
    assert vision.model == "openai/gpt-4o"
    assert vision.supports_vision is True
    assert text_only.supports_vision is False
    assert "/" not in vision.name


def test_catalog_failure_keeps_yaml_only(monkeypatch):
    monkeypatch.setenv("VECTOREE_API_KEY", "sk-ve-v1-test")
    clear_catalog_cache()

    def boom():
        raise RuntimeError("down")

    monkeypatch.setattr("deerflow.community.vectoree.catalog.httpx.get", boom)
    merged = overlay_catalog_models(_yaml_models())
    assert [model.name for model in merged] == ["vectoree", "vectoree-deepseek-v4-pro"]


def test_runtime_and_list_use_catalog_without_rewriting_yaml(monkeypatch):
    monkeypatch.setenv("VECTOREE_API_KEY", "sk-ve-v1-test")
    clear_catalog_cache()
    monkeypatch.setattr("deerflow.community.vectoree.catalog.fetch_catalog_models", lambda: _catalog())
    cfg = _config()
    assert cfg.models[0].name == "vectoree"
    assert cfg.models[0].model == "vectoree/auto"
    resolved = cfg.get_model_config("openai--gpt-4o")
    assert resolved is not None
    assert resolved.model == "openai/gpt-4o"
    assert "/" not in resolved.name
    chat = create_chat_model(name="openai--gpt-4o", app_config=cfg, attach_tracing=False)
    assert chat.model_name == "openai/gpt-4o"
    secret = chat.openai_api_key
    assert secret is not None
    assert secret.get_secret_value() == "sk-ve-v1-test"

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_config] = lambda: cfg
    response = TestClient(app).get("/api/models")
    assert response.status_code == 200
    listed = {item["name"]: item["model"] for item in response.json()["models"]}
    assert listed["vectoree"] == "vectoree/auto"
    assert listed["openai--gpt-4o"] == "openai/gpt-4o"
    vision = {item["name"]: item["supports_vision"] for item in response.json()["models"]}
    assert vision["openai--gpt-4o"] is True
    assert vision["vectoree-deepseek-v4-pro"] is False
    detail = TestClient(app).get("/api/models/openai--gpt-4o")
    assert detail.status_code == 200
    assert detail.json()["supports_vision"] is True
    assert "/" not in "openai--gpt-4o"
