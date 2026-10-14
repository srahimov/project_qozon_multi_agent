"""Local input enforcement before a model; API/service wiring remains separate."""

from qozon_langchain.security.pii import check_pii
from qozon_langchain.security.policies import GateResult, PrivacyPolicy
from qozon_langchain.security.sanitization import SanitizationError, sanitize_question
from qozon_langchain.security.screening import screen_question
from qozon_langchain.security.secrets import check_secrets


def check_input(question: str, *, policy: PrivacyPolicy) -> GateResult:
    """Normalize, screen, block secrets, apply PII policy, and release checked text.

    No model calls or logging. Review holds locally; errors withhold text. The
    caller must pass only an allow result's text to the model, never the original.
    This does not enforce English language, factual scope, or tool permissions.
    """
    try:
        text = sanitize_question(question)
        screening = screen_question(question)
        secrets = check_secrets(text)
        if secrets.decision == "block":
            return GateResult(
                "block", "input_contains_secrets",
                "Your question appears to contain credentials. It was not sent to the AI model. Remove credentials and try again.",
                rule_ids=secrets.rule_ids,
            )
        if screening.decision == "reject":
            return GateResult("block", "invalid_question", "Your question could not be accepted.", rule_ids=screening.rule_ids)
        if screening.decision == "review":
            return GateResult(
                "review", "input_needs_review",
                "Your question needs review and was not sent to the AI model. Rephrase it as a question about the service.",
                rule_ids=screening.rule_ids,
            )

        checked = check_pii(text, policy=policy, direction="input")
        if checked.decision == "block" or checked.text is None:
            code = "input_pii_blocked" if checked.reason == "pii_blocked" else "input_check_unavailable"
            return GateResult("block", code, "Your question could not pass the required privacy checks. It was not sent to the AI model.", pii_types=checked.pii_types)
        if not checked.text.strip() or check_secrets(checked.text).decision == "block":
            return GateResult("block", "input_check_unavailable", "Your question could not pass the required checks.")
        return GateResult("allow", "input_approved", "Question passed local checks.", checked.text, screening.rule_ids, checked.pii_types)
    except SanitizationError:
        return GateResult("block", "invalid_question", "Enter a nonblank question of at most 200 characters without unsupported characters.")
    except Exception:
        return GateResult("block", "input_check_unavailable", "The required input checks could not be completed. Your question was not sent to the AI model.")
