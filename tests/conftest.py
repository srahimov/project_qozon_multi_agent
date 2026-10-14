"""Ordinary pytest runs never upload local data to LangSmith."""

import pytest

from qozon_langchain.core.config import get_settings
from qozon_langchain.core.observability import langsmith_client
from qozon_langchain.api.limits import configured_limits


@pytest.fixture(autouse=True)
def offline_langsmith(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    get_settings.cache_clear()
    configured_limits.cache_clear()
    langsmith_client.cache_clear()
    yield
    langsmith_client.cache_clear()
    get_settings.cache_clear()
    configured_limits.cache_clear()
