"""Buffered output enforcement; never call this on chunks released to a user."""

from pydantic import ValidationError

from qozon_langchain.api.schemas import QuestionResponse
from qozon_langchain.security.pii import check_pii
from qozon_langchain.security.policies import GateResult, PrivacyPolicy, permits_answer_display
from qozon_langchain.security.sanitization import has_disallowed_characters
from qozon_langchain.security.secrets import check_secrets


def check_output(answer: str, *, policy: PrivacyPolicy) -> GateResult:
    """Validate the full text, block secrets, handle PII, and check display policy.

    Only an allow result may be released. No model calls or logs occur. No output
    length ceiling is invented; the separate generation/token policy is still TBD.
    This does not verify truth, citations, arbitrary harmful content, or images.
    """
    try:
        text = QuestionResponse(answer=answer).answer
        if has_disallowed_characters(text):
            return GateResult("block", "invalid_answer", "A checked answer could not be provided. Please try again.")
        secrets = check_secrets(text)
        if secrets.decision == "block":
            return GateResult("block", "output_contains_secrets", "The answer was withheld because it appeared to contain credentials.", rule_ids=secrets.rule_ids)
        # Check the original display shape before PII replacement can conceal a URI.
        if not permits_answer_display(text):
            return GateResult("block", "unsafe_answer_display", "A checked answer could not be provided. Please try again.")
        checked = check_pii(text, policy=policy, direction="output")
        if checked.decision == "block" or checked.text is None:
            code = "output_pii_blocked" if checked.reason == "pii_blocked" else "output_check_unavailable"
            return GateResult("block", code, "The answer could not pass the required privacy checks and was withheld.", pii_types=checked.pii_types)
        approved = QuestionResponse(answer=checked.text).answer
        if has_disallowed_characters(approved) or not permits_answer_display(approved) or check_secrets(approved).decision == "block":
            return GateResult("block", "output_check_unavailable", "A checked answer could not be provided. Please try again.")
        return GateResult("allow", "output_approved", "Answer passed local checks.", approved, pii_types=checked.pii_types)
    except ValidationError:
        return GateResult("block", "invalid_answer", "A checked answer could not be provided. Please try again.")
    except Exception:
        return GateResult("block", "output_check_unavailable", "The required answer checks could not be completed. The answer was withheld.")
