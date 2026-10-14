"""Explicit training policies, separate from detection and API enforcement.

These profiles are not GDPR/HIPAA compliance or public-contact authorization.
No profile is automatically activated in the currently unavailable question API.
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from typing import Literal

PIIType = Literal[
    "email", "credit_card", "ip", "mac_address", "url",
    "ssn", "address", "medical_card", "date_of_birth", "age",
]
PIIAction = Literal["allow", "block", "redact", "mask", "hash"]
Direction = Literal["input", "output"]
BUILTIN_PII_TYPES: tuple[PIIType, ...] = ("email", "credit_card", "ip", "mac_address", "url")
# Local regex detectors for these categories live in custom_pii.py.
CUSTOM_PII_TYPES: tuple[PIIType, ...] = (
    "ssn", "address", "medical_card", "date_of_birth", "age",
)
SUPPORTED_PII_TYPES: tuple[PIIType, ...] = BUILTIN_PII_TYPES + CUSTOM_PII_TYPES


@dataclass(frozen=True)
class GateResult:
    """Only approved results may carry text; representations never show it."""

    decision: Literal["allow", "review", "block"]
    code: str
    message: str
    text: str | None = field(default=None, repr=False)
    rule_ids: tuple[str, ...] = ()
    pii_types: tuple[PIIType, ...] = ()

    def __post_init__(self) -> None:
        if self.decision not in {"allow", "review", "block"}:
            raise ValueError("invalid_gate_decision")
        if self.decision != "allow" and self.text is not None:
            raise ValueError("unapproved_gate_result_cannot_carry_text")
        if self.decision == "allow" and (not isinstance(self.text, str) or not self.text.strip()):
            raise ValueError("approved_gate_result_requires_text")


class _HTMLTagCheck(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.has_tag = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.has_tag = True

    def handle_endtag(self, tag: str) -> None:
        self.has_tag = True


_UNSAFE_SCHEME = re.compile(r"(?:^|[\s(\"'<])(?:javascript|data|vbscript)\s*:", re.IGNORECASE)


def permits_answer_display(text: str) -> bool:
    """Plain text/Markdown only: reject HTML tags and selected active URI schemes.

    Client rendering must also escape text and constrain links. This local policy
    is not a browser sanitizer, general content classifier, or factual verifier.
    """
    parser = _HTMLTagCheck()
    parser.feed(text)
    parser.close()
    return not parser.has_tag and not _UNSAFE_SCHEME.search(text)


@dataclass(frozen=True)
class PIIRule:
    pii_type: PIIType
    action: PIIAction


@dataclass(frozen=True)
class PrivacyPolicy:
    """Required built-ins and optional custom rules for input/output checks.

    Secrets always block, review always holds, and checker failures always
    withhold text. Different directional policies may be supplied to each gate.
    """

    name: str
    rules: tuple[PIIRule, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("invalid_policy_name")
        if not isinstance(self.rules, tuple) or any(not isinstance(rule, PIIRule) for rule in self.rules):
            raise ValueError("invalid_policy_rules")
        types = tuple(rule.pii_type for rule in self.rules)
        if any(types.count(kind) != 1 for kind in BUILTIN_PII_TYPES):
            raise ValueError("policy_requires_each_builtin_type_once")
        if len(types) != len(set(types)) or any(kind not in SUPPORTED_PII_TYPES for kind in types):
            raise ValueError("invalid_custom_policy_rules")
        if any(rule.action not in {"allow", "block", "redact", "mask", "hash"} for rule in self.rules):
            raise ValueError("invalid_pii_action")


def training_policy(profile: Literal["mixed", "block", "redact"] = "redact") -> PrivacyPolicy:
    """Build an explicit profile; callers must deliberately supply it to checks.

    Redaction is the user's selected default for built-in and custom PII types.
    Mixed preserves URLs, redacts email/IP/MAC, and blocks payment cards.
    All custom types are redacted in the mixed profile.
    URL allowance does not permit credentials inside a URL or authorize access.
    Names are deliberately excluded. Public business contact exceptions and
    broader detectors remain future work.
    """
    if profile not in {"mixed", "block", "redact"}:
        raise ValueError("invalid_policy_profile")
    rules = tuple(
        PIIRule(
            pii_type,
            ("allow" if pii_type == "url" else "block" if pii_type == "credit_card" else "redact")
            if profile == "mixed" else profile,
        )
        for pii_type in SUPPORTED_PII_TYPES
    )
    return PrivacyPolicy(f"training_{profile}", rules)
