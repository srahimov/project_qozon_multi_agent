import pytest

from qozon_langchain.knowledge_base.pdf.retrieval import Evidence
from qozon_langchain.security.evidence_verification import EvidenceVerificationError, verify_evidence


def source(text, page=11):
    return Evidence("chunk", "book", "fixture.txt", (page,), "text", "", text)


def test_supported_unicode_sentence_keeps_negation_and_canonical_source():
    result = verify_evidence("The café is not open. [S1]", [source("The cafe\u0301 is not open.")])
    assert result.cited == (1,) and result.mode == "extractive_support"
    assert "not open" in result.text


@pytest.mark.parametrize("text", [
    'The source says: "The box is red."',
    '"The box is red."',
    '“Precautions” concerns travel.',
    '"The box is red." Chapter 2.1',
])
def test_exact_source_quote_characters_are_preserved(text):
    answer = text + " [S1]"
    assert verify_evidence(answer, [source(text)]).text == answer


@pytest.mark.parametrize("text,answer", [
    ("The gate is not open.", "The gate is open. [S1]"),
    ("The red box contains five stones.", "The blue box contains five stones. [S1]"),
    ("It is false that the box contains five stones.", "The box contains five stones. [S1]"),
    ("The gate is open?", "The gate is open. [S1]"),
    ("The box contains five stones.", "The box contains fifty stones. [S1]"),
    ("The box contains five stones.", "The box contains five stones. [S1] It weighs two kilograms."),
    ("The box contains five stones.", "It weighs two kilograms. The box contains five stones. [S1]"),
    ("The box contains five stones.", "The box contains five stones and is red. [S1]"),
    ("5 mg is the stated amount.", ".5 mg is the stated amount. [S1]"),
    ("The box is red.", "The box [REDACTED_ADDRESS] is red. [S1]"),
])
def test_token_overlap_substrings_and_uncited_extras_are_not_support(text, answer):
    with pytest.raises(EvidenceVerificationError, match="unsupported_answer"):
        verify_evidence(answer, [source(text)])


def test_each_citation_group_is_checked_against_its_own_passage():
    evidence = [source("The box is red."), source("The box contains five stones.", 12)]
    assert verify_evidence("The box is red. [S1] The box contains five stones. [S2]", evidence).cited == (1, 2)
    for answer in ["The box is red. [S2] The box contains five stones. [S1]",
                   "The box contains five stones. [S1] [S2]"]:
        with pytest.raises(EvidenceVerificationError, match="unsupported_answer"):
            verify_evidence(answer, evidence)


def test_privacy_checked_source_sentence_can_preserve_its_placeholder():
    text = "The private code is [REDACTED_SSN]."
    assert verify_evidence(text + " [S1]", [source(text)]).mode == "extractive_support"


@pytest.mark.parametrize("answer", ["The box is red. [S0]", "The box is red. [S2]",
                                    "The box is red.", "The box is red. [S1] [s 2]"])
def test_unknown_and_malformed_citations_fail_closed(answer):
    with pytest.raises(EvidenceVerificationError, match="invalid_source_citation"):
        verify_evidence(answer, [source("The box is red.")])


def test_page_claim_is_checked_against_locally_cited_pages():
    evidence = [source("The box is red.", 11), source("The box is red.", 12)]
    assert verify_evidence("On physical page 11, the box is red. [S1]", evidence).cited == (1,)
    with pytest.raises(EvidenceVerificationError, match="invalid_source_page"):
        verify_evidence("On physical page 11, the box is red. [S2]", evidence)


def test_printed_page_cross_reference_is_not_confused_with_physical_metadata():
    result = verify_evidence("See page 97 for the diagram. [S1]", [source("See page 97 for the diagram.", 11)])
    assert result.cited == (1,)


def test_numeric_conflict_cannot_be_resolved_by_a_single_valid_quote():
    evidence = [source("The jar contains four stones."), source("The same jar contains six stones.", 12)]
    with pytest.raises(EvidenceVerificationError, match="evidence_conflict"):
        verify_evidence("The jar contains four stones. [S1]", evidence)
    result = verify_evidence("The sources conflict: four [S1] versus six [S2]. I cannot determine the count. Also aliens exist.", evidence)
    assert result.mode == "conflict_disclosure" and result.cited == (1, 2)
    assert "four stones" in result.text and "six stones" in result.text
    assert "aliens" not in result.text  # Unverified generated prose is replaced, not approved.


def test_different_subjects_are_not_a_count_conflict():
    evidence = [source("The jar contains four stones."), source("The box contains six stones.")]
    assert verify_evidence("The jar contains four stones. [S1]", evidence).mode == "extractive_support"


def test_explicit_negation_conflict_is_withheld():
    evidence = [source("The gate is open."), source("The gate is not open.", 12)]
    with pytest.raises(EvidenceVerificationError, match="evidence_conflict"):
        verify_evidence("The gate is open. [S1]", evidence)


def test_only_a_pure_refusal_is_exempt_from_text_support():
    evidence = [source("The box is red.")]
    result = verify_evidence("I cannot determine the answer from the supplied evidence. [S1]", evidence)
    assert result.mode == "abstention" and result.cited == ()
    with pytest.raises(EvidenceVerificationError, match="unsupported_answer"):
        verify_evidence("I cannot determine the answer from the supplied evidence. The box contains five stones. [S1]", evidence)


def test_long_inputs_are_withheld_instead_of_partial_verification():
    with pytest.raises(EvidenceVerificationError, match="evidence_verification_limit"):
        verify_evidence("The box is red. [S1]", [source("x" * 100_001)])


def test_unsupported_pixel_interpretation_is_not_verified_by_text_summary():
    evidence = [Evidence("picture", "book", "fixture.txt", (11,), "image_description", "asset",
                         "The picture shows a box.", image=b"synthetic-pixels")]
    with pytest.raises(EvidenceVerificationError, match="unsupported_answer"):
        verify_evidence("The picture shows a red box. [S1]", evidence)
