"""Lazy construction and configuration-only health checks without live clients."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from qozon_langchain.api import dependencies
from qozon_langchain.api.app import create_app
from qozon_langchain.core.config import Settings
from qozon_langchain.services.question_service import ModelInvocationError


def test_dependency_creation_does_not_load_settings(monkeypatch) -> None:
    def forbidden():
        pytest.fail("Dependency creation must not load settings")
    monkeypatch.setattr(dependencies, "get_settings", forbidden)
    assert isinstance(dependencies.get_answer_model(), dependencies.ConfiguredAnswerModel)


def test_configured_client_is_constructed_once_when_generation_starts(monkeypatch) -> None:
    builds = []
    class FakeClient:
        async def generate_answer(self, question):
            return "Synthetic answer"
    def build(settings):
        builds.append(settings)
        return FakeClient()
    monkeypatch.setattr(dependencies, "build_openai_model", build)
    model = dependencies.get_answer_model()
    assert builds == []
    assert asyncio.run(model.generate_answer("Approved question")) == "Synthetic answer"
    assert asyncio.run(model.generate_answer("Another approved question")) == "Synthetic answer"
    assert len(builds) == 1


def test_configuration_errors_have_no_private_details(monkeypatch) -> None:
    def broken():
        raise RuntimeError("synthetic-config-private-value")
    monkeypatch.setattr(dependencies, "get_settings", broken)
    with pytest.raises(ModelInvocationError) as caught:
        asyncio.run(dependencies.get_answer_model().generate_answer("Approved question"))
    assert caught.value.code == "model_not_configured"
    assert "synthetic-config-private-value" not in str(caught.value)


def test_health_reports_configured_without_constructing_provider(monkeypatch) -> None:
    settings = Settings(_env_file=None, openai_api_key="synthetic-test-value", output_max_tokens=128)
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    def forbidden(*args, **kwargs):
        pytest.fail("Health checks must not construct or call a provider")
    monkeypatch.setattr(dependencies, "build_openai_model", forbidden)
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.json()["model_calls_enabled"] is True
    assert response.json()["provider_connection"] == "not_checked"
    assert "synthetic-test-value" not in response.text
