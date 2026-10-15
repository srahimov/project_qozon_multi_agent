"""Shape validation only; PII, injection, and safety gates remain separate.

Error strings hide input values. Structured errors still require sanitization
at the future API boundary before they are returned or logged.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal


class APIErrorDetail(BaseModel):
    code: str
    message: str


class APIErrorResponse(BaseModel):
    """Document the fixed public error envelope used by the API handlers."""
    detail: APIErrorDetail


class QuestionRequest(BaseModel):
    """Validate original question shape/length without trimming or normalization."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    question: str = Field(strict=True, min_length=1, max_length=200)

    @field_validator("question", mode="after")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must contain non-whitespace text.")
        return value


class SourceCitation(BaseModel):
    """Application-resolved evidence identifiers; no local file paths."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    citation_id: str
    chunk_id: str
    document_id: str
    source: str
    physical_pages: list[int] = Field(min_length=1)
    content_type: Literal["text", "table_summary", "image_description"]
    asset_id: str | None = None
    factually_verified: bool
    url: str | None = None
    image_url: str | None = None
    structured_url: str | None = None

    @field_validator("physical_pages")
    @classmethod
    def positive_pages(cls, values):
        if any(p < 1 for p in values):
            raise ValueError("Physical page numbers must be positive.")
        return values


class QuestionResponse(BaseModel):
    """Validate nonblank answer shape; this is not the output safety gate."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    answer: str = Field(strict=True, min_length=1)
    sources: list[SourceCitation] = Field(default_factory=list)

    @field_validator("answer", mode="after")
    @classmethod
    def reject_blank_answer(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Answer must contain non-whitespace text.")
        return value
