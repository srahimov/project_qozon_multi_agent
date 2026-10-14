"""Buffered output decisions; never invoke a live model."""

import pytest

from qozon_langchain.security import output_gate
from qozon_langchain.security.pii import PIIResult
from qozon_langchain.security.policies import GateResult, training_policy


def test_output_has_a_separate_budget_from_question_length() -> None:
    text = "An ordinary answer. " * 30
    result = output_gate.check_output(text, policy=training_policy())
    assert len(text) > 200
    assert result.decision == "allow" and result.text == text


@pytest.mark.parametrize("answer", [None, 42, "", " \n", "bad\x00text", "bad\u202etext"])
def test_invalid_answer_is_withheld(answer) -> None:
    result = output_gate.check_output(answer, policy=training_policy())
    assert result.decision == "block" and result.text is None


def test_secret_containing_output_is_withheld_without_echoing() -> None:
    result = output_gate.check_output("API_KEY=synthetic-private-value", policy=training_policy())
    assert result.code == "output_contains_secrets"
    assert result.text is None
    assert "synthetic-private-value" not in result.message
    assert "synthetic-private-value" not in repr(result)


def test_output_pii_is_redacted_before_release() -> None:
    result = output_gate.check_output("Email person@example.com", policy=training_policy())
    assert result.decision == "allow" and result.text is not None
    assert "person@example.com" not in result.text


@pytest.mark.parametrize("answer", [
    "<script>alert(1)</script>",
    "<b>Raw HTML</b>",
    "[help](javascript:alert(1))",
    "[help](data:text/html,example)",
])
def test_disallowed_display_content_is_withheld(answer) -> None:
    result = output_gate.check_output(answer, policy=training_policy())
    assert result.code == "unsafe_answer_display" and result.text is None


def test_plain_comparison_symbols_are_preserved() -> None:
    result = output_gate.check_output("1 < 2 and 3 > 2.", policy=training_policy())
    assert result.decision == "allow"


def test_checker_failure_withholds_answer_and_error(monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("synthetic-private-value")
    monkeypatch.setattr(output_gate, "check_pii", broken)
    result = output_gate.check_output("Ordinary answer", policy=training_policy())
    assert result.code == "output_check_unavailable" and result.text is None
    assert "synthetic-private-value" not in repr(result)


def test_checked_output_is_validated_again_before_release(monkeypatch) -> None:
    monkeypatch.setattr(output_gate, "check_pii", lambda *a, **k: PIIResult("transform", "API_KEY=synthetic-private-value"))
    result = output_gate.check_output("Ordinary answer", policy=training_policy())
    assert result.decision == "block" and result.text is None


def test_nonapproved_gate_result_cannot_carry_text() -> None:
    with pytest.raises(ValueError, match="unapproved_gate_result_cannot_carry_text"):
        GateResult("block", "blocked", "Blocked", text="private text")


def test_approved_gate_result_requires_nonblank_text() -> None:
    with pytest.raises(ValueError, match="approved_gate_result_requires_text"):
        GateResult("allow", "approved", "Approved", text=" ")
