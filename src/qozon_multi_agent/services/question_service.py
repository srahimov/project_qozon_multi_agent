"""Buffered API execution: one input boundary, supervisor, then response checks."""

import asyncio
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from qozon_multi_agent.agents.pdf_subagent import PDFWorkflowError
from qozon_multi_agent.api.schemas import QuestionResponse
from qozon_multi_agent.security.input_gate import check_input
from qozon_multi_agent.security.output_gate import check_output


class QuestionServiceError(Exception):
    """Safe public errors, without user text or provider details."""

    def __init__(self, *, stage: Literal["input", "model", "output"], code: str, message: str):
        self.stage, self.code, self.message = stage, code, message
        super().__init__(message)


class ModelInvocationError(Exception):
    """Fixed provider failure codes used by the offline ingestion adapters."""

    def __init__(self, code: str):
        allowed = {
            "model_authentication_failed", "model_rate_limited", "model_connection_failed",
            "model_timeout", "model_not_available", "model_not_configured", "model_incomplete", "invalid_model_answer",
        }
        self.code = code if code in allowed else "model_unavailable"
        super().__init__(self.code)


async def answer_question(question: str, *, supervisor_factory, timeout_seconds: float = 45.0) -> QuestionResponse:
    """No provider client is constructed until the single input gate allows it.

    PII is handled only by registered supervisor middleware. The PDF tool owns
    retrieval and final source-access checks. No local quality judge or telemetry.
    """
    approved_input = check_input(question)
    if approved_input.decision != "allow":
        raise QuestionServiceError(stage="input", code=approved_input.code, message=approved_input.message)

    try:
        async with asyncio.timeout(timeout_seconds):
            try:
                supervisor = supervisor_factory()
            except Exception:
                raise QuestionServiceError(stage="model", code="model_not_configured",
                                           message="Question answering needs provider and cloud retrieval configuration.") from None
            state = await supervisor.ainvoke({"messages": [HumanMessage(content=approved_input.text)]})
    except QuestionServiceError:
        raise
    except TimeoutError:
        raise QuestionServiceError(stage="model", code="question_timeout",
                                   message="Question answering timed out. Please try again.") from None
    except PDFWorkflowError as error:
        code = "question_timeout" if str(error) == "pdf_deadline_exceeded" else "pdf_unavailable"
        raise QuestionServiceError(stage="model", code=code,
                                   message="The PDF workflow could not complete. Please try again.") from None
    except Exception:
        raise QuestionServiceError(stage="model", code="agent_unavailable",
                                   message="Question answering could not complete. Please try again.") from None

    try:
        messages = state["messages"]
        final = messages[-1]
        specialist = next(message for message in reversed(messages)
                          if isinstance(message, ToolMessage))
        response = QuestionResponse.model_validate(specialist.artifact)
        if not isinstance(final, AIMessage) or final.tool_calls:
            raise ValueError("incomplete_agent_response")
        # Use the final supervisor message, which has passed its output PII hooks;
        # the artifact supplies citation metadata, never unredacted answer text.
        approved_output = check_output(final.text)
    except Exception:
        raise QuestionServiceError(stage="output", code="invalid_agent_response",
                                   message="A complete answer with checked citations could not be returned.") from None
    if approved_output.decision != "allow":
        raise QuestionServiceError(stage="output", code=approved_output.code, message=approved_output.message)
    return QuestionResponse(answer=approved_output.text, sources=response.sources)
