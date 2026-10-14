"""Local text normalization; this does not detect injection, PII, or secrets."""

import unicodedata

MAX_QUESTION_CHARACTERS = 200

# Explicit direction overrides and invisible separators are rejected, not deleted.
# Joiners used in legitimate writing and emoji are preserved.
_DISALLOWED_FORMAT_CHARACTERS = frozenset(
    "\u00ad\u200b\u202a\u202b\u202c\u202d\u202e\u2060\u2066\u2067\u2068\u2069\ufeff"
)


class SanitizationError(ValueError):
    """A fixed error code with no copy of the submitted question."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def has_disallowed_characters(text: str) -> bool:
    """Shared character policy; does not impose the user-question length cap."""
    return any(
        (unicodedata.category(character) in {"Cc", "Cs"} and character not in "\t\n\r")
        or character in _DISALLOWED_FORMAT_CHARACTERS
        for character in text
    )


def sanitize_question(value: str) -> str:
    """Check original input, then apply NFC and collapse whitespace.

    The 200-character limit applies before normalization, including spaces and
    punctuation. Punctuation and letter case are preserved. Line breaks and
    tabs become ordinary spaces for this single-question interface.
    """
    if not isinstance(value, str):
        raise SanitizationError("invalid_type")
    if not 1 <= len(value) <= MAX_QUESTION_CHARACTERS:
        raise SanitizationError("invalid_length")

    if has_disallowed_characters(value):
        raise SanitizationError("disallowed_character")

    normalized = unicodedata.normalize("NFC", value)
    normalized = " ".join(normalized.split())
    if not normalized:
        raise SanitizationError("blank_question")
    return normalized
