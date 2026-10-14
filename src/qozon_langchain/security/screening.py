"""Bounded local signals, not proof of malicious intent or complete protection.

Review holds a question without a model call. An allow result still requires PII
policy and tool authorization. Documents use a separate scanning budget and a
narrow allowance for descriptive educational quotations.
"""

from dataclasses import dataclass
import re
from typing import Literal
import unicodedata

from qozon_langchain.security.sanitization import SanitizationError, sanitize_question
from qozon_langchain.security.sanitization import has_disallowed_characters

Decision = Literal["allow", "review", "reject"]
Category = Literal[
    "authority_spoofing", "internal_info_extraction", "private_data_disclosure",
    "conversation_spoofing", "obfuscated_instructions", "tool_misuse",
    "persistent_manipulation", "indirect_source_injection",
]
POLICY_VERSION = "local-screening-v3"


@dataclass(frozen=True)
class ScreeningResult:
    """Only decisions and fixed identifiers; never matched or submitted text."""

    decision: Decision
    rule_ids: tuple[str, ...] = ()
    categories: tuple[Category, ...] = ()


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    category: Category | None
    holds_request: bool
    pattern: re.Pattern[str]


def _rule(rule_id: str, category: Category | None, pattern: str, *, hold: bool = True) -> _Rule:
    return _Rule(rule_id, category, hold, re.compile(pattern, re.IGNORECASE | re.MULTILINE))


# General instruction-manipulation examples are separate from the eight training groups.
_RULES = (
    _rule("instruction_override", None, r"\bignore\s+(?:all\s+)?(?:(?:previous|prior|earlier)\s+)?instructions?\b"),
    _rule("spaced_instruction_override", "obfuscated_instructions", r"\bi[\s._-]+g[\s._-]+n[\s._-]+o[\s._-]+r[\s._-]+e\s+(?:all\s+)?(?:(?:previous|prior|earlier)\s+)?instructions?\b"),
    _rule("instruction_reset", None, r"\bforget\s+(?:all\s+)?(?:previous|prior|earlier)(?:\s+(?:instructions?|rules?))?\b"),
    _rule("restriction_bypass", None, r"\bbypass\s+(?:all\s+)?(?:restrictions?|rules?|safeguards?|filters?)\b"),
    _rule("claimed_authority", "authority_spoofing", r"\b(?:i\s+am|i['’]m)\s+(?:(?:the|your|an?)\s+)?(?:admin(?:istrator)?|developer|owner)\b"),
    _rule("claimed_priority", "authority_spoofing", r"\b(?:system|developer|admin(?:istrator)?)\s+(?:message|instruction|override)\b", hold=False),
    _rule("request_internal_instructions", "internal_info_extraction", r"\b(?:show|reveal|print|disclose|repeat)\s+(?:(?:me|your|the|original|hidden)\s+){0,3}(?:system\s+prompt|developer\s+instructions?|hidden\s+instructions?)\b"),
    _rule("request_other_users_data", "private_data_disclosure", r"\b(?:show|export|dump|give|reveal)\b.{0,60}\b(?:other\s+users?['’]?\s+(?:data|emails?|records?)|private\s+(?:records?|customer\s+data))\b"),
    _rule("spoofed_role_heading", "conversation_spoofing", r"^\s*(?:system|developer)\s*:"),
    _rule("encoded_execution", "obfuscated_instructions", r"\bdecode\b[\s\S]{0,40}\b(?:base64|hex|rot13)\b[\s\S]{0,40}\b(?:execute|obey|follow)\b"),
    _rule("disable_access_controls", "tool_misuse", r"\b(?:disable|bypass|turn\s+off)\s+(?:(?:the|all)\s+)?(?:authorization|authentication|row\s+level\s+security|rls|access\s+controls?)\b"),
    _rule("destructive_sql_execution", "tool_misuse", r"\b(?:run|execute)\s+(?:this\s+)?(?:sql\s+)?(?:drop\s+table|truncate\s+table|delete\s+from)\b"),
    _rule("persistent_override", "persistent_manipulation", r"\b(?:from\s+now\s+on|for\s+all\s+future\s+(?:requests?|messages?))\b.{0,60}\b(?:ignore|override|bypass)\b"),
    _rule("source_claimed_override", "indirect_source_injection", r"\b(?:the|this)\s+(?:document|page|pdf|website)\s+(?:says|instructs|requires)\b.{0,60}\b(?:ignore|override|bypass)\b"),
    _rule("instruction_heading", None, r"\bnew\s+instructions?\b", hold=False),
    _rule("prompt_reference", None, r"\bsystem\s+prompt\b", hold=False),
    _rule("prompt_boundary", None, r"\bend\s+of\s+(?:the\s+)?prompt\b", hold=False),
    _rule("roleplay", None, r"\b(?:pretend\s+you\s+are|act\s+as\s+if\s+you\s+are)\b", hold=False),
    _rule("dash_separator", None, r"-{2,}", hold=False),
)

# Only the instruction-override match inside this complete descriptive sentence
# is exempted for documents. Other rules and occurrences still hold the source.
_DOCUMENT_EXAMPLE = re.compile(
    r"""(?:^|(?<=[.!?\n]))\s*(?:security|training|educational)\s+(?:notes|guides?|materials?|texts?)\s+quotes?\s+(?P<quote>'[^'\n]{1,300}'|"[^"\n]{1,300}"|‘[^’\n]{1,300}’|“[^”\n]{1,300}”)\s+as\s+(?:an?\s+)?example\s+(?:attack|prompt\s+injection)\s*[.!?](?=\s|$)""",
    re.IGNORECASE,
)
_QUOTED_EXECUTION = re.compile(
    r"\b(?:follow|obey|execute|apply|use|do)\s+(?:(?:the|these|those|above|quoted)\s+){0,3}(?:instructions?|commands?|text|phrase|example|it|them|that|this)\b",
    re.IGNORECASE,
)


def screen_question(value: str) -> ScreeningResult:
    """Inspect a bounded scanning copy; invalid input rejects, strong signals hold.

    No model, file, network, or logging operations are performed. Weak signals
    alone allow progression to remaining checks. Quoted educational examples
    can still be held: regex cannot reliably infer intent. No automatic reviewer
    or bypass is implemented. The question service must honor review/reject.
    """
    try:
        normalized = sanitize_question(value)
    except SanitizationError as error:
        return ScreeningResult("reject", (error.code,))

    return _scan_text(normalized)


def screen_document_text(value: str) -> ScreeningResult:
    """Apply local source signals with a separate bounded document budget.

    This is heuristic screening, not a guarantee against source injection.
    Documents do not inherit the API's 200-character question limit.
    """
    if (
        not isinstance(value, str) or len(value) > 100_000
        or has_disallowed_characters(value)
    ):
        return ScreeningResult("reject", ("invalid_document_text",))
    return _scan_text(unicodedata.normalize("NFC", value), document=True)


def _scan_text(normalized: str, *, document: bool = False) -> ScreeningResult:
    # Compatibility matching is limited to this scanning copy, not source data.
    scan_text = unicodedata.normalize("NFKC", normalized)
    scan_text = scan_text.replace("\u200c", "").replace("\u200d", "")
    examples = [match.span("quote") for match in _DOCUMENT_EXAMPLE.finditer(scan_text)] if document else []
    if examples and _QUOTED_EXECUTION.search(scan_text):
        examples = []  # A request to enact the example removes the allowance.
    hits = tuple(rule for rule in _RULES if any(
        not (rule.rule_id == "instruction_override" and any(
            start <= match.start() and match.end() <= end for start, end in examples
        )) for match in rule.pattern.finditer(scan_text)
    ))
    categories = tuple(dict.fromkeys(rule.category for rule in hits if rule.category is not None))
    rule_ids = tuple(rule.rule_id for rule in hits)
    if scan_text != normalized:
        rule_ids += ("normalized_scanning_copy",)
    decision: Decision = "review" if any(rule.holds_request for rule in hits) else "allow"
    return ScreeningResult(decision, rule_ids, categories)
