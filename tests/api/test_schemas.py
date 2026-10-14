"""Synthetic contract tests; no settings, credential files, gates, or model calls."""

import pytest
from pydantic import ValidationError

from qozon_langchain.api.schemas import QuestionRequest, QuestionResponse


@pytest.mark.parametrize(
    "text",
    ["x" * 200, " " + "x" * 198 + "?", "🙂" * 199 + "?", "e\u0301" * 100],
)
def test_200_original_unicode_characters_are_accepted(text: str) -> None:
    assert len(text) == 200
    assert QuestionRequest(question=text).question == text


@pytest.mark.parametrize(
    "text", ["x" * 201, "x" * 199 + " ?", " " + "x" * 199 + " "]
)
def test_201_characters_are_rejected_before_any_trimming(text: str) -> None:
    assert len(text) == 201
    with pytest.raises(ValidationError):
        QuestionRequest(question=text)


@pytest.mark.parametrize("text", ["", " ", " \t\n", "\u2003"])
@pytest.mark.parametrize(
    "model,field", [(QuestionRequest, "question"), (QuestionResponse, "answer")]
)
def test_empty_or_whitespace_only_text_is_rejected(model, field, text) -> None:
    with pytest.raises(ValidationError):
        model(**{field: text})


@pytest.mark.parametrize("value", [42, True, None, b"text", ["text"], {"value": "text"}])
@pytest.mark.parametrize(
    "model,field", [(QuestionRequest, "question"), (QuestionResponse, "answer")]
)
def test_non_string_values_are_not_coerced(model, field, value) -> None:
    with pytest.raises(ValidationError):
        model(**{field: value})


@pytest.mark.parametrize(
    "model,field", [(QuestionRequest, "question"), (QuestionResponse, "answer")]
)
def test_field_is_required_and_extra_fields_are_rejected(model, field) -> None:
    with pytest.raises(ValidationError):
        model()
    with pytest.raises(ValidationError):
        model(**{field: "Synthetic text", "unexpected": "synthetic-extra-value"})


def test_question_preserves_leading_trailing_whitespace_and_punctuation() -> None:
    original = "  What is a service-based business?  "
    assert QuestionRequest(question=original).question == original


def test_response_preserves_text_without_an_invented_length_limit() -> None:
    original = "  A synthetic answer.  "
    assert QuestionResponse(answer=original).answer == original
    long_answer = "Synthetic answer. " * 1000
    assert QuestionResponse(answer=long_answer).answer == long_answer


@pytest.mark.parametrize(
    "model,field", [(QuestionRequest, "question"), (QuestionResponse, "answer")]
)
def test_error_strings_do_not_include_rejected_input(model, field) -> None:
    marker = "synthetic-private-value"
    with pytest.raises(ValidationError) as error:
        model(**{field: {"value": marker}})
    assert marker not in str(error.value)
    print(f"ValidationError for {model.__name__}.{field}:\n{error.value}")
