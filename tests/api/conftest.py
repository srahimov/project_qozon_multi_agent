"""Keep every API test isolated from real local settings and provider clients."""

import pytest

from qozon_langchain.api import dependencies
from qozon_langchain.core.config import Settings


@pytest.fixture(autouse=True)
def offline_api_configuration(monkeypatch):
    settings = Settings(_env_file=None, openai_api_key=None, output_max_tokens=None)
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    dependencies._configured_model.cache_clear()
    yield
    dependencies._configured_model.cache_clear()
