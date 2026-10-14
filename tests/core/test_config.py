"""Configuration checks without reading local credentials."""

from qozon_langchain.core.config import Settings


def test_configuration_defaults_do_not_require_credentials(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.model_provider == "openai"
    assert settings.model_name == "gpt-6-luna"
    assert settings.language == "en"
    assert settings.max_question_characters == 200
    assert settings.output_max_tokens is None
    assert settings.openai_api_key is None
    assert Settings(_env_file=None, OPENAI_API_KEY="").openai_api_key is None


def test_configuration_repr_excludes_key_field() -> None:
    settings = Settings(_env_file=None, openai_api_key="synthetic-test-value")
    assert "synthetic-test-value" not in repr(settings)
    assert "openai_api_key" not in repr(settings)


