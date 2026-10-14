"""Local LangChain PII checks and explicit agent middleware factory.

Text-only built-ins and selected custom regexes, with no exhaustive coverage
or compliance guarantees. Gates must also apply secrets, screening, and scope
policy. Do not serialize or trace unchecked messages or returned text objects.
"""

from dataclasses import dataclass, field
from functools import partial
from typing import Literal

from langchain.agents.middleware import PIIMiddleware
from langchain.agents.middleware.pii import PIIDetectionError
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from qozon_langchain.security.custom_pii import custom_pii
from qozon_langchain.security.policies import CUSTOM_PII_TYPES, Direction, PIIRule, PIIType, PrivacyPolicy


@dataclass(frozen=True)
class PIIResult:
    """Checked text is hidden from repr; blocked/error results contain no text."""

    decision: Literal["allow", "transform", "block"]
    text: str | None = field(repr=False)
    pii_types: tuple[PIIType, ...] = ()
    reason: str | None = None


def _middleware(rule: PIIRule) -> PIIMiddleware:
    return PIIMiddleware(
        rule.pii_type,
        detector=partial(custom_pii, pii_type=rule.pii_type) if rule.pii_type in CUSTOM_PII_TYPES else None,
        strategy=rule.action if rule.action != "allow" else "redact",
        apply_to_input=True,
        apply_to_output=True,
        apply_to_tool_results=False,
    )


def build_pii_middleware(policy: PrivacyPolicy) -> tuple[PIIMiddleware, ...]:
    """Explicitly enable input/output on configured rules for a future agent.

    Allow rules are omitted; tools and their result checks are a later phase.
    No agent is created or configured by this factory. Hashing is deterministic
    pseudonymization, not guaranteed anonymity.
    """
    if not isinstance(policy, PrivacyPolicy):
        raise ValueError("invalid_privacy_policy")
    return tuple(_middleware(rule) for rule in policy.rules if rule.action != "allow")


def check_pii(text: str, *, policy: PrivacyPolicy, direction: Direction) -> PIIResult:
    """Run public middleware hooks locally, withholding text on checker errors.

    Detect all configured types before rewriting so a blocking type cannot be
    hidden by an earlier replacement. Nothing is logged, persisted or sent to a
    provider. Callers must deliberately select a policy and input/output scope.
    """
    if not isinstance(text, str) or not isinstance(policy, PrivacyPolicy) or direction not in {"input", "output"}:
        return PIIResult("block", None, reason="invalid_check_request")

    try:
        rules = tuple((rule, _middleware(rule)) for rule in policy.rules)
        found = tuple(rule.pii_type for rule, middleware in rules if middleware.detector(text))
        if any(rule.action == "block" and rule.pii_type in found for rule, _ in rules):
            return PIIResult("block", None, found, "pii_blocked")

        message = HumanMessage(content=text) if direction == "input" else AIMessage(content=text)
        runtime = Runtime()
        for rule, middleware in rules:
            if rule.action == "allow":
                continue
            state = {"messages": [message]}
            update = middleware.before_model(state, runtime) if direction == "input" else middleware.after_model(state, runtime)
            if update is not None:
                message = update["messages"][-1]

        checked = message.content
        if not isinstance(checked, str):
            return PIIResult("block", None, found, "checker_error")
        return PIIResult("transform" if checked != text else "allow", checked, found)
    except PIIDetectionError:
        return PIIResult("block", None, reason="pii_blocked")
    except Exception:
        # Middleware failures can embed matched data; do not expose their errors.
        return PIIResult("block", None, reason="checker_error")
