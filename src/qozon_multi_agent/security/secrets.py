"""Selected local credential signals; no exhaustive secret-detection claim."""

from dataclasses import dataclass
import re
from typing import Literal


@dataclass(frozen=True)
class SecretResult:
    """Fixed identifiers only; no credential values, locations or raw text."""

    decision: Literal["allow", "block"]
    rule_ids: tuple[str, ...] = ()


_RULES = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("provider_secret_key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b")),
    ("cloud_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("source_control_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*", re.IGNORECASE)),
    ("credential_url", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)),
)
_ASSIGNMENT = re.compile(
    r"\b(?:[a-z][a-z0-9]*[_-])?(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
    r"\s*[:=]\s*[\"']?([^\s\"']{8,})",
    re.IGNORECASE,
)
_PLACEHOLDERS = frozenset({"your-key-here", "your_api_key", "changeme", "placeholder", "[redacted]"})
_DISCLOSURE = re.compile(
    r"\b(?:my|our)\s+(?:password|api[ _-]?key|access[ _-]?token|client[ _-]?secret)"
    r"\s+is\s+[\"']?([^\s\"']{8,})",
    re.IGNORECASE,
)


def check_secrets(text: str) -> SecretResult:
    """Block selected secret-shaped values on either input or buffered output.

    A match is a signal, not verification that a credential is valid. No external
    lookups, logging or API calls occur. Unsupported input fails closed.
    """
    if not isinstance(text, str):
        return SecretResult("block", ("invalid_type",))
    hits = tuple(name for name, pattern in _RULES if pattern.search(text))
    if any(match.group(1).casefold() not in _PLACEHOLDERS for match in _ASSIGNMENT.finditer(text)):
        hits += ("credential_assignment",)
    if any(match.group(1).casefold() not in _PLACEHOLDERS for match in _DISCLOSURE.finditer(text)):
        hits += ("credential_disclosure",)
    return SecretResult("block" if hits else "allow", hits)
