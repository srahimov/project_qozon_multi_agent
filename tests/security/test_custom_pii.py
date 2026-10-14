"""Synthetic custom PII coverage, exclusions, and gate integration."""

import pytest

from qozon_langchain.security.custom_pii import custom_pii
from qozon_langchain.security.input_gate import check_input
from qozon_langchain.security.output_gate import check_output
from qozon_langchain.security.pii import check_pii
from qozon_langchain.security.policies import training_policy


@pytest.mark.parametrize("kind,text,value", [
    ("ssn", "SSN: 000-12-3456", "000-12-3456"),
    ("ssn", "SSN: 000123456", "000123456"),
    ("address", "Address: 123 Example Street", "123 Example Street"),
    ("address", "Address: 123 North Example Blvd, Apt #4B", "123 North Example Blvd, Apt #4B"),
    ("medical_card", "Medical card number #TEST-1234", "TEST-1234"),
    ("medical_card", "medical card: 00001234", "00001234"),
    ("date_of_birth", "DOB: 01/02/2000", "01/02/2000"),
    ("date_of_birth", "Date of birth: 01-02-00", "01-02-00"),
    ("age", "I am 35 years old", "35"),
    ("age", "A 35-year-old customer", "35"),
])
def test_custom_values_have_exact_spans(kind, text, value) -> None:
    matches = custom_pii(text, pii_type=kind)
    assert len(matches) == 1
    match = matches[0]
    assert match["type"] == kind and match["value"] == value
    assert text[match["start"]:match["end"]] == value


@pytest.mark.parametrize("suffix", [
    "Drive", "Boulevard", "Street", "Place", "Lane", "Line", "Circle",
    "Avenue", "Road", "Court", "Way", "Dr", "Blvd", "St", "Pl", "Ln", "Cir",
])
def test_selected_numbered_street_suffixes(suffix) -> None:
    text = f"Address: 123 Example {suffix}"
    assert custom_pii(text, pii_type="address")[0]["value"] == f"123 Example {suffix}"


@pytest.mark.parametrize("kind,text", [
    ("ssn", "123456"),
    ("ssn", "1234567890"),
    ("ssn", "123-45-6"),
    ("ssn", "123-456-7890"),
    ("ssn", "x000123456y"),
    ("address", "Find businesses on Example Street"),
    ("address", "123 Example Streetwise"),
    ("medical_card", "How can I replace my medical card?"),
    ("medical_card", "Order number #00001234"),
    ("medical_card", "Medical card number #EXAMPLE"),
    ("date_of_birth", "Appointment: 01/02/2000"),
    ("date_of_birth", "DOB: 13/02/2000"),
    ("date_of_birth", "DOB: 01/32/2000"),
    ("date_of_birth", "DOB: 01/02-2000"),
    ("date_of_birth", "DOB: 01/02/20001"),
    ("age", "This service has 35 years of experience"),
    ("age", "Order 1234 years old"),
])
def test_ordinary_or_unsupported_formats_do_not_match(kind, text) -> None:
    assert custom_pii(text, pii_type=kind) == []


@pytest.mark.parametrize("direction", ["input", "output"])
@pytest.mark.parametrize("kind,text,value", [
    ("ssn", "SSN: 000-12-3456", "000-12-3456"),
    ("address", "Address: 123 Example Street", "123 Example Street"),
    ("medical_card", "Medical card number #TEST-1234", "TEST-1234"),
    ("date_of_birth", "DOB: 01/02/2000", "01/02/2000"),
    ("age", "I am 35 years old", "35"),
])
def test_custom_redaction_through_both_middleware_hooks(direction, kind, text, value) -> None:
    result = check_pii(text, policy=training_policy(), direction=direction)
    assert result.decision == "transform" and result.text is not None
    assert value not in result.text
    assert f"[REDACTED_{kind.upper()}]" in result.text
    assert kind in result.pii_types


@pytest.mark.parametrize("gate", [check_input, check_output])
def test_both_gates_apply_custom_redaction_and_preserve_names(gate) -> None:
    text = "My name is Example Person. DOB: 01/02/2000. I am 35 years old."
    result = gate(text, policy=training_policy())
    assert result.decision == "allow" and result.text is not None
    assert "Example Person" in result.text
    assert "01/02/2000" not in result.text and "35" not in result.text


def test_custom_block_policy_withholds_text_before_transform() -> None:
    result = check_pii("SSN: 000-12-3456", policy=training_policy("block"), direction="input")
    assert result.decision == "block" and result.text is None
    assert "ssn" in result.pii_types


def test_multiple_matches_redact_without_corrupting_other_text() -> None:
    text = "DOB: 01/02/2000; DOB: 03/04/2001. Keep this sentence."
    result = check_pii(text, policy=training_policy(), direction="output")
    assert result.text == "DOB: [REDACTED_DATE_OF_BIRTH]; DOB: [REDACTED_DATE_OF_BIRTH]. Keep this sentence."


@pytest.mark.parametrize("text,kind", [(None, "ssn"), ("text", "name"), ("text", "email")])
def test_invalid_custom_detector_requests_have_fixed_errors(text, kind) -> None:
    with pytest.raises(ValueError):
        custom_pii(text, pii_type=kind)
