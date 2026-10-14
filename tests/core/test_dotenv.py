"""Dotenv checks use isolated temporary files and synthetic values only."""

import pytest
from pydantic import ValidationError

from qozon_langchain.core.config import Settings


def test_project_working_directory_dotenv_loads_lazily(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=synthetic-file-value\n", encoding="utf-8"
    )

    settings = Settings()

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "synthetic-file-value"
    assert "synthetic-file-value" not in repr(settings)
    assert "synthetic-file-value" not in settings.model_dump_json()


def test_process_environment_overrides_dotenv(tmp_path, monkeypatch) -> None:
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY=synthetic-file-value\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-environment-value")

    settings = Settings(_env_file=path)

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "synthetic-environment-value"
    assert "synthetic-environment-value" not in repr(settings)


def test_settings_error_text_hides_invalid_secret_input(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValidationError) as result:
        Settings(
            _env_file=None,
            OPENAI_API_KEY={"value": "synthetic-invalid-input"},
        )

    assert "synthetic-invalid-input" not in str(result.value)
