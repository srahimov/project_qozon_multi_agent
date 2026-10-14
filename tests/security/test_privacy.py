"""Synthetic privacy checks using offline middleware hooks only."""

import pytest

from qozon_langchain.security import pii
from qozon_langchain.security.policies import BUILTIN_PII_TYPES, CUSTOM_PII_TYPES, SUPPORTED_PII_TYPES, PIIRule, PrivacyPolicy, training_policy
from qozon_langchain.security.secrets import check_secrets


@pytest.mark.parametrize("direction", ["input", "output"])
@pytest.mark.parametrize("text,kind", [
    ("Email person@example.com", "email"),
    ("Address 192.0.2.1", "ip"),
    ("Device 00:11:22:33:44:55", "mac_address"),
])
def test_mixed_policy_transforms_builtins_in_both_directions(direction, text, kind) -> None:
    result = pii.check_pii(text, policy=training_policy("mixed"), direction=direction)
    assert result.decision == "transform"
    assert result.text is not None and result.text != text
    assert kind in result.pii_types
    assert text not in repr(result)


@pytest.mark.parametrize("direction", ["input", "output"])
def test_mixed_policy_blocks_card_without_retaining_text(direction) -> None:
    result = pii.check_pii("Test card 4111 1111 1111 1111", policy=training_policy("mixed"), direction=direction)
    assert result.decision == "block"
    assert result.text is None
    assert "credit_card" in result.pii_types
    assert "4111" not in repr(result)


def test_ordinary_url_is_usable_under_explicit_mixed_policy() -> None:
    text = "Read https://en.wikipedia.org/wiki/Seattle"
    result = pii.check_pii(text, policy=training_policy("mixed"), direction="input")
    assert result.decision == "allow"
    assert result.text == text
    assert "url" in result.pii_types


def test_block_and_redact_profiles_are_configurable() -> None:
    text = "person@example.com"
    assert pii.check_pii(text, policy=training_policy("block"), direction="input").text is None
    redacted = pii.check_pii(text, policy=training_policy("redact"), direction="output")
    assert redacted.decision == "transform" and text not in redacted.text


def test_middleware_factory_explicitly_enables_input_and_output() -> None:
    middleware = pii.build_pii_middleware(training_policy("mixed"))
    assert {item.pii_type for item in middleware} == set(SUPPORTED_PII_TYPES) - {"url"}
    assert all(item.apply_to_input and item.apply_to_output for item in middleware)
    assert all(not item.apply_to_tool_results for item in middleware)


def test_blocking_type_is_checked_before_other_replacements() -> None:
    rules = tuple(PIIRule(kind, "redact" if kind == "url" else "block") for kind in BUILTIN_PII_TYPES)
    policy = PrivacyPolicy("overlap", rules)
    result = pii.check_pii("https://example.com/192.0.2.1", policy=policy, direction="output")
    assert result.decision == "block" and result.text is None


def test_middleware_failure_withholds_text_and_error(monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("synthetic-private-value")
    monkeypatch.setattr(pii, "_middleware", broken)
    result = pii.check_pii("synthetic-private-value", policy=training_policy(), direction="input")
    assert result.text is None
    assert result.reason == "checker_error"
    assert "synthetic-private-value" not in repr(result)


@pytest.mark.parametrize("text,direction", [(None, "input"), ("text", "invalid")])
def test_invalid_check_request_fails_closed(text, direction) -> None:
    assert pii.check_pii(text, policy=training_policy(), direction=direction).text is None


def test_missing_or_duplicate_policy_rules_are_rejected() -> None:
    with pytest.raises(ValueError, match="policy_requires_each_builtin_type_once"):
        PrivacyPolicy("bad", (PIIRule("email", "redact"),))
    with pytest.raises(ValueError, match="policy_requires_each_builtin_type_once"):
        PrivacyPolicy("bad", tuple(PIIRule("email", "redact") for _ in BUILTIN_PII_TYPES))


@pytest.mark.parametrize("profile", ["mixed", "block", "redact"])
def test_profiles_cover_builtins_and_custom_types(profile) -> None:
    assert {rule.pii_type for rule in training_policy(profile).rules} == set(SUPPORTED_PII_TYPES)


def test_user_selected_default_redacts_all_supported_types() -> None:
    policy = training_policy()
    assert policy.name == "training_redact"
    assert all(rule.action == "redact" for rule in policy.rules)
    assert len(pii.build_pii_middleware(policy)) == 10


@pytest.mark.parametrize("kind", ["name", "unknown"])
def test_unknown_or_removed_custom_policy_types_are_rejected(kind) -> None:
    rules = tuple(PIIRule(item, "redact") for item in BUILTIN_PII_TYPES)
    with pytest.raises(ValueError, match="invalid_custom_policy_rules"):
        PrivacyPolicy("bad", rules + (PIIRule(kind, "redact"),))


def test_duplicate_custom_rule_is_rejected() -> None:
    rules = training_policy().rules
    with pytest.raises(ValueError, match="invalid_custom_policy_rules"):
        PrivacyPolicy("bad", rules + (PIIRule(CUSTOM_PII_TYPES[0], "redact"),))


@pytest.mark.parametrize("text", [
    "sk-proj-" + "SyntheticNotARealSecret1234567890",
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "ghp_" + "SyntheticToken12345678901234567890",
    "Authorization: Bearer synthetic-token-123456789",
    "-----BEGIN PRIVATE KEY-----",
    "OPENAI_API_KEY=synthetic-private-value",
    "https://user:synthetic-password@example.com",
    "My password is example-password-123. What is in the book?",
    "Our API key is synthetic-private-value",
])
def test_selected_secret_signals_block_without_retaining_value(text) -> None:
    result = check_secrets(text)
    assert result.decision == "block" and result.rule_ids
    assert text not in repr(result)


@pytest.mark.parametrize("text", [
    "How do I configure an API key?",
    "OPENAI_API_KEY=your-key-here",
    "Find https://example.com/contact",
    "Which business offers password recovery support?",
    "What is a password and why is it useful?",
    "My password is [REDACTED]",
])
def test_ordinary_text_and_documented_placeholders_do_not_block(text) -> None:
    assert check_secrets(text).decision == "allow"


def test_secret_check_invalid_input_blocks() -> None:
    assert check_secrets(None).decision == "block"
