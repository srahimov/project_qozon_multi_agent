"""Credential/display enforcement on buffered text; runtime PII is on the supervisor."""

from pydantic import ValidationError

from qozon_multi_agent.api.schemas import QuestionResponse
from qozon_multi_agent.security.policies import GateResult, permits_answer_display
from qozon_multi_agent.security.sanitization import has_disallowed_characters
from qozon_multi_agent.security.secrets import check_secrets


def check_output(answer: str) -> GateResult:
    """Check response shape, credentials and display safety, without PII or grading."""
    try:
        text = QuestionResponse(answer=answer).answer
        if has_disallowed_characters(text) or not permits_answer_display(text):
            return GateResult("block", "unsafe_answer_display", "A checked answer could not be provided.")
        if check_secrets(text).decision == "block":
            return GateResult("block", "output_contains_secrets",
                              "The answer was withheld because it appeared to contain credentials.")
        return GateResult("allow", "output_approved", "Answer passed output checks.", text)
    except ValidationError:
        return GateResult("block", "invalid_answer", "A checked answer could not be provided.")
    except Exception:
        return GateResult("block", "output_check_unavailable", "The required answer checks could not be completed.")
