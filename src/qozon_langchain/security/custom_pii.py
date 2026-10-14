"""Local English/U.S. training regexes, not exhaustive PII detection.

SSNs are nine-digit shapes, not verified identities. Street matches cover a
bounded selection of numbered addresses, including unit details but not whole
postal addresses. Medical-card IDs and birth dates require explicit labels;
unlabeled values can pass. Names are deliberately excluded. Matches contain
sensitive text for middleware transformation only: never log or serialize them.
"""

import re

from langchain.agents.middleware.pii import PIIMatch

from qozon_langchain.security.policies import CUSTOM_PII_TYPES, PIIType


_STREET_WORD = r"[A-Za-z][A-Za-z'’-]{0,39}"
_STREET_SUFFIX = (
    r"(?:boulevard|street|avenue|circle|drive|place|lane|line|road|court|way|"
    r"blvd|st|ave|cir|dr|pl|ln|rd|ct)"
)
_PATTERNS: dict[PIIType, re.Pattern[str]] = {
    "ssn": re.compile(
        r"(?<![\w-])(?P<value>(?:[0-9]{3}-[0-9]{2}-[0-9]{4}|[0-9]{9}))(?![\w-])"
    ),
    "address": re.compile(
        rf"(?<![\w-])(?P<value>[0-9]{{1,6}}[A-Za-z]?\s+"
        rf"(?:{_STREET_WORD}\s+){{1,6}}{_STREET_SUFFIX}\b\.?"
        r"(?:[ ,]+(?:apt\.?|apartment|suite|unit|#)\s*#?\s*[A-Za-z0-9-]{1,12}\b)?)(?!\w)",
        re.IGNORECASE,
    ),
    "medical_card": re.compile(
        r"\bmedical\s+card(?:\s+(?:number|no\.?|id))?\s*[:#=]?\s*#?\s*"
        r"(?P<value>(?=[A-Za-z0-9-]{0,39}[0-9])[A-Za-z0-9][A-Za-z0-9-]{3,39})(?![\w-])",
        re.IGNORECASE,
    ),
    "date_of_birth": re.compile(
        r"\b(?:date\s+of\s+birth|birth\s*date|dob)\s*[:#=]?\s*"
        r"(?P<value>(?:0[1-9]|1[0-2])(?P<separator>[/.-])(?:0[1-9]|[12][0-9]|3[01])"
        r"(?P=separator)(?:[0-9]{4}|[0-9]{2}))(?![\w/-]|\.[0-9])",
        re.IGNORECASE,
    ),
    "age": re.compile(
        r"(?<![\w.-])(?P<value>[0-9]{1,3})(?:\s+years?\s+old|[- ]years?[- ]old)\b",
        re.IGNORECASE,
    ),
}


def custom_pii(text: str, *, pii_type: PIIType) -> list[PIIMatch]:
    """Return exact value spans for one custom type; middleware handles policy.

    Regex matching is deliberately conservative about context for dates and
    medical-card IDs. No model calls, logging, or external verification occur.
    Invalid requests raise fixed errors that the PII checker handles safely.
    """
    if not isinstance(text, str):
        raise ValueError("invalid_custom_pii_text")
    if pii_type not in CUSTOM_PII_TYPES:
        raise ValueError("unsupported_custom_pii_type")
    return [
        PIIMatch(
            type=pii_type,
            value=match.group("value"),
            start=match.start("value"),
            end=match.end("value"),
        )
        for match in _PATTERNS[pii_type].finditer(text)
    ]
