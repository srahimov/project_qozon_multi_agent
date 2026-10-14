"""Local normalization checks with synthetic text and no provider calls."""

import pytest

from qozon_langchain.security.sanitization import SanitizationError, sanitize_question


def test_whitespace_is_normalized_without_changing_punctuation() -> None:
    assert sanitize_question("  ACME -- repair?\n\tUnder $50!  ") == "ACME -- repair? Under $50!"


def test_canonical_unicode_and_multilingual_text() -> None:
    assert sanitize_question("Cafe\u0301? Привет! Oʻzbek? Кыргыз? Қазақ? Тоҷик?") == "Café? Привет! Oʻzbek? Кыргыз? Қазақ? Тоҷик?"


def test_legitimate_joiners_are_preserved() -> None:
    value = "Help 👩\u200d💻 with x\u200cy?"
    assert sanitize_question(value) == value


def test_original_length_is_checked_before_cleanup() -> None:
    assert sanitize_question("a" + " " * 199) == "a"
    with pytest.raises(SanitizationError, match="invalid_length"):
        sanitize_question("a" + " " * 200)


@pytest.mark.parametrize("value,code", [
    ("", "invalid_length"),
    (" \t\n", "blank_question"),
    (123, "invalid_type"),
    (None, "invalid_type"),
])
def test_invalid_input_has_a_fixed_error(value, code) -> None:
    with pytest.raises(SanitizationError) as result:
        sanitize_question(value)
    assert result.value.code == code
    assert str(result.value) == code


@pytest.mark.parametrize("character", ["\x00", "\x1b", "\x7f", "\ud800", "\u200b", "\u202e", "\u2066", "\ufeff"])
def test_unwanted_characters_are_rejected_without_echoing_text(character) -> None:
    with pytest.raises(SanitizationError) as result:
        sanitize_question("synthetic-private-value" + character)
    assert str(result.value) == "disallowed_character"
    assert "synthetic-private-value" not in str(result.value)


def test_normalization_is_idempotent() -> None:
    value = sanitize_question("  Cafe\u0301\nrepair -- today? ")
    assert sanitize_question(value) == value
