"""Local configuration defaults; loading settings does not create a model client."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load the working directory's .env only when Settings is constructed.

    pydantic-settings uses python-dotenv directly; a separate import-time
    load_dotenv() call is unnecessary. Process environment values take priority.
    Run project commands from project_Qozon, or pass _env_file explicitly.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="QOZON_",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    language: Literal["en"] = "en"
    cors_origins: list[str] = Field(default_factory=list)
    model_provider: Literal["openai"] = "openai"
    model_name: str = "gpt-6-luna"
    max_question_characters: Literal[200] = 200
    output_max_tokens: int | None = Field(default=None, gt=0)
    question_limits_enabled: bool = False
    question_limits_backend: Literal["local", "cloudflare"] = "local"
    question_limits_database: Path = Path("data/request-limits.sqlite3")
    question_limit_key: SecretStr | None = Field(default=None, repr=False, min_length=32)
    questions_per_minute: int = Field(default=5, ge=1, le=100)
    questions_per_day: int = Field(default=100, ge=1, le=10_000)
    table_model_name: str = Field(default="gpt-5.6-terra", min_length=1)
    image_model_name: str = Field(default="gpt-5.6-terra", min_length=1)
    table_output_max_tokens: int = Field(default=512, gt=0)
    image_output_max_tokens: int = Field(default=512, gt=0)
    embedding_model_name: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, gt=0)
    rag_enabled: bool = False
    rag_backend: Literal["chroma", "supabase"] = "chroma"
    rag_chunks_directory: Path = Path("data/pdf-chunks")
    rag_vector_directory: Path = Path("data/chroma")
    rag_top_k: int = Field(default=4, gt=0, le=12)
    rag_max_distance: float = Field(default=0.65, ge=0, le=2)
    rag_context_characters: int = Field(default=16_000, ge=1000, le=100_000)
    rag_publication_manifest: Path = Path("data/pdf-assets/publication.json")
    langsmith_tracing: bool = Field(default=False, validation_alias="LANGSMITH_TRACING")
    langsmith_api_key: SecretStr | None = Field(
        default=None, validation_alias="LANGSMITH_API_KEY", repr=False
    )
    langsmith_project: str = Field(default="project_qozon", validation_alias="LANGSMITH_PROJECT")
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com", validation_alias="LANGSMITH_ENDPOINT"
    )
    langsmith_workspace_id: str | None = Field(default=None, validation_alias="LANGSMITH_WORKSPACE_ID")
    langsmith_trace_content: bool = False
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias="OPENAI_API_KEY", repr=False
    )
    supabase_url: str | None = Field(default=None, validation_alias="SUPABASE_URL")
    supabase_secret_key: SecretStr | None = Field(
        default=None, validation_alias="SUPABASE_SECRET_KEY", repr=False
    )
    supabase_publishable_key: SecretStr | None = Field(
        default=None, validation_alias="SUPABASE_PUBLISHABLE_KEY", repr=False
    )
    supabase_storage_bucket: str | None = Field(
        default=None, validation_alias="SUPABASE_STORAGE_BUCKET"
    )
    supabase_assets_bucket: str | None = Field(
        default=None, validation_alias="SUPABASE_ASSETS_BUCKET"
    )

    @field_validator("openai_api_key", "supabase_secret_key", "supabase_publishable_key", "langsmith_api_key", "question_limit_key", mode="before")
    @classmethod
    def empty_key_is_unconfigured(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    """Read configuration lazily; restart or clear this cache after local edits."""
    return Settings()
