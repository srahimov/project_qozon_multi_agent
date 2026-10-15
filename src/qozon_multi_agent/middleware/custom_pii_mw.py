"""Custom PII detection and node-style middleware in one module.

Categories checked by this module, with their regex matching rules:
* ssn: nine digits, either contiguous or in a three-two-four hyphenated form.
* address: selected numbered English/U.S. street addresses, optionally with a unit.
* medical_card: an ID containing a digit after an explicit "medical card" label.
* date_of_birth: a labeled birth date in month/day/year format; separators must agree.
* age: a one-to-three-digit age followed by "years old" or a hyphenated equivalent.

Two kinds of rules work together:
* _PATTERNS defines what text counts as a match for each custom category.
* DEFAULT_RULES selects allow, block or redact for each category.
The default configuration redacts all five categories. A blocking match stops the
invocation; an allow rule preserves that category. Mask and hash are unsupported
by this custom middleware. Names are deliberately excluded.

These are bounded pattern detectors, not identity or calendar validation. For
example, SSN-shaped text is not checked against an issuer, birth dates require
labels, and the date regex does not validate month-specific day counts.
LangChain's built-in middleware handles email, payment cards, IP/MAC addresses
and URLs separately. Credentials retain their separate guard.

Register CustomPIIMiddleware on the supervisor, not the PDF subagent. Its
before_model and after_model node-style hooks check input, returned tool text
and answer text; async equivalents support agent.ainvoke(). These checks do not
inspect image pixels, tool-call arguments or streamed token deltas. The supervisor
delegation wrapper supplies the already checked visitor question. Detection makes no external model call.
Never log or upload raw matched values.
"""

# re provides compiled regular expressions for the matching rules below.
import re
# Any describes content blocks; Literal lists the supported category/action names.
from typing import Any, Literal

# AgentMiddleware is the base class; AgentState holds the agent's messages.
from langchain.agents.middleware import AgentMiddleware, AgentState
# PIIMatch describes the exact type, value and character offsets of a match.
from langchain.agents.middleware.pii import PIIMatch
# These classes identify model answers, visitor input and tool results.
# BaseMessage is their shared type, used in the _updates() annotation.
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
# LangChain supplies this execution context when it calls a registered hook.
# Importing Runtime does not mean we build a custom LangGraph graph.
from langgraph.runtime import Runtime

# Keep this module standalone: it imports no Qozon policy or detector modules.
PIIType = Literal["ssn", "address", "medical_card", "date_of_birth", "age"]
PIIAction = Literal["allow", "block", "redact"]
# These are handling rules, distinct from the regex matching rules below.
DEFAULT_RULES: dict[PIIType, PIIAction] = {
    "ssn": "redact",
    "address": "redact",
    "medical_card": "redact",
    "date_of_birth": "redact",
    "age": "redact",
}
# The dictionary keys define exactly which custom categories we support.
CUSTOM_PII_TYPES = tuple(DEFAULT_RULES)


# The leading underscore marks an internal helper; capitals mark a constant.
# A street-name word starts with a letter and permits selected punctuation.
_STREET_WORD = r"[A-Za-z][A-Za-z'’-]{0,39}"
# This internal fragment matches explicit street suffixes and abbreviations.
_STREET_SUFFIX = (
    r"(?:boulevard|street|avenue|circle|drive|place|lane|line|road|court|way|"
    r"blvd|st|ave|cir|dr|pl|ln|rd|ct)"
)
# Each named "value" group identifies exactly what will be redacted.
_PATTERNS: dict[PIIType, re.Pattern[str]] = {
    # Reject matches embedded in a longer word, number or hyphenated token.
    "ssn": re.compile(
        r"(?<![\w-])(?P<value>(?:[0-9]{3}-[0-9]{2}-[0-9]{4}|[0-9]{9}))(?![\w-])"
    ),
    # Number + street-name words + suffix; optionally include an apartment/unit.
    "address": re.compile(
        rf"(?<![\w-])(?P<value>[0-9]{{1,6}}[A-Za-z]?\s+"
        rf"(?:{_STREET_WORD}\s+){{1,6}}{_STREET_SUFFIX}\b\.?"
        r"(?:[ ,]+(?:apt\.?|apartment|suite|unit|#)\s*#?\s*[A-Za-z0-9-]{1,12}\b)?)(?!\w)",
        re.IGNORECASE,
    ),
    # Require a medical-card label and a bounded ID containing at least one digit.
    "medical_card": re.compile(
        r"\bmedical\s+card(?:\s+(?:number|no\.?|id))?\s*[:#=]?\s*#?\s*"
        r"(?P<value>(?=[A-Za-z0-9-]{0,39}[0-9])[A-Za-z0-9][A-Za-z0-9-]{3,39})(?![\w-])",
        re.IGNORECASE,
    ),
    # Require a birth-date label; capture month/day/year with the same separator.
    "date_of_birth": re.compile(
        r"\b(?:date\s+of\s+birth|birth\s*date|dob)\s*[:#=]?\s*"
        r"(?P<value>(?:0[1-9]|1[0-2])(?P<separator>[/.-])(?:0[1-9]|[12][0-9]|3[01])"
        r"(?P=separator)(?:[0-9]{4}|[0-9]{2}))(?![\w/-]|\.[0-9])",
        re.IGNORECASE,
    ),
    # Redact the age value, preserving the descriptive "years old" wording.
    "age": re.compile(
        r"(?<![\w.-])(?P<value>[0-9]{1,3})(?:\s+years?\s+old|[- ]years?[- ]old)\b",
        re.IGNORECASE,
    ),
}


# Shared detector: the custom middleware and existing gates use the same rules.
def custom_pii(text: str, *, pii_type: PIIType) -> list[PIIMatch]:
    """Return exact value spans for one custom type; middleware handles policy.

    Regex matching is deliberately conservative about context for dates and
    medical-card IDs. No model calls, logging, or external verification occur.
    Invalid requests raise fixed errors that the PII checker handles safely.
    """
    # Accept only text; fixed errors never repeat the supplied value.
    if not isinstance(text, str):
        raise ValueError("invalid_custom_pii_text")
    # Built-in categories belong to LangChain's separate detector implementation.
    if pii_type not in CUSTOM_PII_TYPES:
        raise ValueError("unsupported_custom_pii_type")
    # Return every match with offsets into the original text.
    return [
        PIIMatch(
            type=pii_type,
            value=match.group("value"),  # Sensitive value: use only for transformation.
            start=match.start("value"),  # First character included in the match.
            end=match.end("value"),      # First character after the match.
        )
        for match in _PATTERNS[pii_type].finditer(text)
    ]


# A separate error type lets callers recognize privacy failures safely.
class CustomPIIError(ValueError):
    """Fixed failure codes only; never include a matched value."""


# Inheriting AgentMiddleware makes these methods registerable LangChain hooks.
class CustomPIIMiddleware(AgentMiddleware):
    """Apply custom allow/block/redact rules through registered agent hooks.

    The default configuration redacts all five custom types. A block rule stops the
    invocation before any partial transformation is returned. Unsupported
    mask/hash configurations are rejected rather than silently changed.
    """

    # Called when the middleware object is created; this makes no model request.
    # Optional overrides are simple mappings, e.g. {"age": "allow"}.
    def __init__(self, rules: dict[PIIType, PIIAction] | None = None) -> None:
        # Copy defaults so one middleware instance cannot modify another's rules.
        self.rules = DEFAULT_RULES.copy()
        # Only inspect overrides when the caller supplies them.
        if rules is not None:
            # Reject malformed configuration instead of silently bypassing checks.
            if not isinstance(rules, dict) or any(kind not in CUSTOM_PII_TYPES for kind in rules):
                raise ValueError("invalid_custom_pii_rules")
            # Only allow, block and redact are supported, not mask or hash.
            if any(action not in {"allow", "block", "redact"} for action in rules.values()):
                raise ValueError("unsupported_custom_pii_action")
            # Override selected categories; unspecified categories still redact.
            self.rules.update(rules)
        # Validate the final configuration too, including the module defaults.
        if any(action not in {"allow", "block", "redact"} for action in self.rules.values()):
            raise ValueError("unsupported_custom_pii_action")

    # Helper: check one text string and return its checked version.
    def _check_text(self, text: str) -> str:
        # Detector failures must stop processing rather than release unchecked text.
        try:
            # Collect all matches in the original text before replacing anything.
            matches = [
                # Store the category and handling action beside each detected span.
                (pii_type, action, match)
                # Allow rules preserve that category, so skip detection for them.
                for pii_type, action in self.rules.items() if action != "allow"
                # The detector returns each match's type, value, start and end.
                for match in custom_pii(text, pii_type=pii_type)
            ]
        # Catch detector failures; their original messages might contain private text.
        except Exception:
            # Suppress the original exception chain and expose only a fixed code.
            raise CustomPIIError("custom_pii_check_unavailable") from None
        # A single blocking match stops everything before any edited text returns.
        if any(action == "block" for _, action, _ in matches):
            # The agent invocation fails; it does not continue with the matched text.
            raise CustomPIIError("custom_pii_blocked")

        # Merge overlapping spans before replacement so one detector cannot
        # expose the unmatched remainder of another detector's sensitive value.
        # Each span will contain a start offset, end offset and redaction label.
        spans = []
        # Sort left to right; at the same start, put the longest match first.
        for pii_type, _, match in sorted(matches, key=lambda item: (item[2]["start"], -item[2]["end"])):
            # Offsets refer to character positions in the original text.
            start, end = match["start"], match["end"]
            # If this span starts before the last span ends, they overlap.
            if spans and start < spans[-1][1]:
                # Read the previous span; its earlier label is intentionally ignored.
                previous_start, previous_end, _ = spans[-1]
                # Cover the entire overlap and use a general PII label.
                spans[-1] = (previous_start, max(previous_end, end), "PII")
            else:
                # Otherwise add a separate span labeled with its custom PII category.
                spans.append((start, end, pii_type.upper()))
        # Replace right to left so replacements do not shift unprocessed offsets.
        for start, end, label in reversed(spans):
            # Keep text outside the match and insert a redaction placeholder.
            text = text[:start] + f"[REDACTED_{label}]" + text[end:]
        # Return the checked text; a no-match input returns unchanged.
        return text

    # Helper: handle plain text and LangChain's list-of-blocks message format.
    def _check_content(self, content: Any) -> Any:
        # A plain string can go straight to the text checker.
        if isinstance(content, str):
            return self._check_text(content)
        # Other supported content must be a list of strings or dictionaries.
        if not isinstance(content, list):
            # Unsupported content is withheld instead of being treated as safe.
            raise CustomPIIError("unsupported_message_content")
        # Build a new list so the original message content is not edited in place.
        checked = []
        # Check each content block independently.
        for block in content:
            # Some block lists contain plain strings.
            if isinstance(block, str):
                # Append the string after custom PII handling.
                checked.append(self._check_text(block))
            # Other blocks are structured dictionaries, such as text or images.
            elif isinstance(block, dict):
                # Only text blocks are within this middleware's detection scope.
                if block.get("type") == "text":
                    # A text block must actually contain a string.
                    if not isinstance(block.get("text"), str):
                        raise CustomPIIError("unsupported_message_content")
                    # Copy the block, replace its text and preserve its other fields.
                    block = {**block, "text": self._check_text(block["text"])}
                # Non-text blocks pass through unchanged; image pixels are not checked.
                checked.append(block)
            else:
                # Reject invalid list entries rather than silently skip them.
                raise CustomPIIError("unsupported_message_content")
        # Return the newly assembled content list.
        return checked

    # Helper: turn checked content into the state updates LangChain expects.
    def _updates(self, messages: list[BaseMessage]) -> dict[str, Any] | None:
        # Collect only messages whose content changes.
        updates = []
        # Process the messages selected by the calling hook.
        for message in messages:
            # Check text while keeping the message's surrounding metadata separate.
            content = self._check_content(message.content)
            # Avoid unnecessary state updates when nothing was detected.
            if content != message.content:
                # Copy the message and preserve its ID, role and tool-call identity.
                # LangChain's message reducer replaces messages with matching IDs.
                updates.append(message.model_copy(update={"content": content}))
        # A dictionary updates agent state; None means no change is needed.
        return {"messages": updates} if updates else None

    # Node-style hook: LangChain calls this before a model request.
    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Check human input and returned tool text before model execution."""
        # The hook receives runtime context, but this check needs only the messages.
        return self._updates([
            # Read messages already stored in the agent's state.
            message for message in state["messages"]
            # Check visitor text and tool results, leaving other roles to their hooks.
            if isinstance(message, (HumanMessage, ToolMessage))
        ])

    # Node-style hook: LangChain calls this after the model produces a response.
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Check the newest model answer before the agent can release it."""
        # Search newest to oldest for an AI message; None is the no-answer fallback.
        latest = next((message for message in reversed(state["messages"])
                       # Ignore human and tool messages while locating the answer.
                       if isinstance(message, AIMessage)), None)
        # Check that answer if it exists, otherwise leave the state unchanged.
        return self._updates([latest]) if latest is not None else None

    # Async node-style hook used during agent.ainvoke().
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        # Reuse the synchronous detector logic; it performs no network I/O.
        return self.before_model(state, runtime)

    # Async counterpart of the output hook.
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        # Keep synchronous and asynchronous privacy behavior identical.
        return self.after_model(state, runtime)
