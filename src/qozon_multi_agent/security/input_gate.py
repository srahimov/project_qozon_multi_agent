"""Single API input boundary, before the supervisor and its PII middleware."""

from qozon_multi_agent.security.policies import GateResult
from qozon_multi_agent.security.sanitization import SanitizationError, sanitize_question
from qozon_multi_agent.security.screening import screen_question
from qozon_multi_agent.security.secrets import check_secrets


def check_input(question: str) -> GateResult:
    """Sanitize once, screen and block credentials. PII belongs to the supervisor."""
    try:
        text = sanitize_question(question)
        if check_secrets(text).decision == "block":
            return GateResult("block", "input_contains_secrets",
                              "Your question appears to contain credentials. Remove them and try again.")
        screening = screen_question(text)
        if screening.decision == "reject":
            return GateResult("block", "invalid_question", "Your question could not be accepted.",
                              rule_ids=screening.rule_ids)
        if screening.decision == "review":
            return GateResult("review", "input_needs_review",
                              "Rephrase your request as a question about the indexed book.", rule_ids=screening.rule_ids)
        return GateResult("allow", "input_approved", "Question passed input checks.", text)
    except SanitizationError:
        return GateResult("block", "invalid_question",
                          "Enter a nonblank question of at most 200 characters without unsupported characters.")
    except Exception:
        return GateResult("block", "input_check_unavailable", "The required input checks could not be completed.")
