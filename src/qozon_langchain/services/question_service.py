"""One buffered question workflow with an explicitly supplied model and policy.

No HTTP handling, credential loading, logging, streaming, or model construction
occurs here. The API and live model adapter are wired separately.
"""

import asyncio
from typing import TYPE_CHECKING, Literal, Protocol

from qozon_langchain.api.schemas import QuestionResponse, SourceCitation
from qozon_langchain.core.observability import evidence_payload, trace_span
from qozon_langchain.security.evidence_verification import POLICY_VERSION, EvidenceVerificationError, verify_evidence
from qozon_langchain.security.input_gate import check_input
from qozon_langchain.security.output_gate import check_output
from qozon_langchain.security.policies import PrivacyPolicy

if TYPE_CHECKING:
    from qozon_langchain.knowledge_base.pdf.retrieval import EvidenceRetriever


class AnswerModel(Protocol):
    """Small interface implemented by a fake or a future LangChain adapter."""

    async def generate_answer(self, question: str) -> str:
        """Return a complete answer for already approved question text."""
        ...


class QuestionServiceError(Exception):
    """Safe public error attributes with no submitted text or provider error details."""

    def __init__(self, *, stage: Literal["input", "model", "output"], code: str, message: str) -> None:
        self.stage = stage
        self.code = code
        self.message = message
        super().__init__(message)


class ModelInvocationError(Exception):
    """Fixed model failure categories; provider adapters must discard raw details."""

    def __init__(self, code: str) -> None:
        allowed = {
            "model_authentication_failed", "model_rate_limited", "model_connection_failed",
            "model_timeout", "model_not_available", "model_not_configured", "model_incomplete", "invalid_model_answer",
        }
        self.code = code if code in allowed else "model_unavailable"
        super().__init__(self.code)


async def answer_question(
    question: str, *, model: AnswerModel, policy: PrivacyPolicy,
    retriever: "EvidenceRetriever | None" = None,
    timeout_seconds: float = 45.0,
) -> QuestionResponse:
    """Observed entry point shared by the API and LangSmith evaluation target."""
    with trace_span("question_workflow", metadata={"rag_enabled": retriever is not None}) as span:
        try:
            async with asyncio.timeout(timeout_seconds):
                response = await _answer_question(question, model=model, policy=policy, retriever=retriever)
        except TimeoutError:
            span.finish(status="withheld", stage="model", code="question_timeout")
            raise QuestionServiceError(stage="model", code="question_timeout",
                                       message="Question answering timed out. Please try again.") from None
        except QuestionServiceError as error:
            span.finish(status="withheld", stage=error.stage, code=error.code)
            raise
        span.finish(status="success", **response.model_dump())
        return response


async def _answer_question(
    question: str, *, model: AnswerModel, policy: PrivacyPolicy,
    retriever: "EvidenceRetriever | None" = None,
) -> QuestionResponse:
    """Input gate → one model call → output gate → approved response.

    Review and block results stop before generation. Only checked input is sent
    to the supplied model, and only checked output becomes a response. Model and
    unexpected checker failures become fixed safe errors, never raw exceptions.
    Callers must not trace/log locals or exception context: those can hold raw
    text despite safe error messages. The provider adapter owns request limits.
    """
    try:
        with trace_span("input_gate") as span:
            approved_input = check_input(question, policy=policy)
            span.finish(decision=approved_input.decision, code=approved_input.code,
                        pii_types=list(approved_input.pii_types))
    except Exception:
        raise QuestionServiceError(
            stage="input", code="input_check_unavailable",
            message="The required input checks could not be completed. Your question was not sent to the AI model.",
        ) from None
    if approved_input.decision != "allow" or approved_input.text is None:
        raise QuestionServiceError(
            stage="input", code=approved_input.code, message=approved_input.message,
        )

    evidence = None
    if retriever is not None:
        try:
            with trace_span("retrieve_evidence", run_type="retriever",
                            inputs={"question": approved_input.text}) as span:
                evidence = await retriever.retrieve(approved_input.text)
                span.finish(evidence=evidence_payload(evidence), retrieved_count=len(evidence))
        except Exception:
            raise QuestionServiceError(stage="model", code="retrieval_unavailable",
                                       message="The required source retrieval could not be completed.") from None
    try:
        if evidence == []:
            answer = "I could not find sufficient evidence in the indexed book to answer this question."
        else:
            with trace_span("generate_answer", run_type="llm",
                            inputs={"question": approved_input.text},
                            metadata={"grounded": evidence is not None}) as span:
                if evidence is not None:
                    answer = await model.generate_grounded_answer(approved_input.text, evidence)
                else:
                    answer = await model.generate_answer(approved_input.text)
                # The raw reply is withheld from traces until the output gate passes.
                span.finish(status="buffered")
    except ModelInvocationError as error:
        raise QuestionServiceError(
            stage="model", code=error.code,
            message="An answer could not be generated. Please try again.",
        ) from None
    except Exception:
        raise QuestionServiceError(
            stage="model", code="model_unavailable",
            message="An answer could not be generated. Please try again.",
        ) from None

    try:
        with trace_span("output_gate") as span:
            approved_output = check_output(answer, policy=policy)
            span.finish(decision=approved_output.decision, code=approved_output.code,
                        pii_types=list(approved_output.pii_types))
    except Exception:
        raise QuestionServiceError(
            stage="output", code="output_check_unavailable",
            message="The required answer checks could not be completed. The answer was withheld.",
        ) from None
    if approved_output.decision != "allow" or approved_output.text is None:
        raise QuestionServiceError(
            stage="output", code=approved_output.code, message=approved_output.message,
        )
    sources = []
    if evidence:
        try:
            with trace_span("verify_answer_evidence", metadata={"policy": POLICY_VERSION}) as span:
                verified = verify_evidence(approved_output.text, evidence)
                span.finish(status="supported", mode=verified.mode, cited_count=len(verified.cited))
        except EvidenceVerificationError as error:
            message = ("The answer's source references could not be verified."
                       if error.code == "invalid_source_citation" else
                       "The answer could not be supported by its cited passages and was withheld.")
            raise QuestionServiceError(stage="output", code=error.code, message=message) from None
        except Exception:
            raise QuestionServiceError(stage="output", code="evidence_check_unavailable",
                                       message="The required evidence checks could not be completed. The answer was withheld.") from None
        # A canonical conflict disclosure includes source quotations. Check the
        # rewritten text too; it must not bypass the privacy/display gate.
        if verified.text != approved_output.text:
            try:
                approved_output = check_output(verified.text, policy=policy)
            except Exception:
                raise QuestionServiceError(stage="output", code="output_check_unavailable",
                                           message="The required answer checks could not be completed. The answer was withheld.") from None
            if approved_output.decision != "allow" or approved_output.text is None:
                raise QuestionServiceError(stage="output", code=approved_output.code, message=approved_output.message)
        cited = verified.cited
        for n in cited:
            item = evidence[n - 1]
            sources.append(SourceCitation(
                citation_id=f"S{n}", chunk_id=item.chunk_id, document_id=item.document_id, source=item.source,
                physical_pages=list(item.page_numbers), content_type=item.content_type,
                asset_id=item.parent_asset_id or None, factually_verified=item.factually_verified,
                url=item.url, image_url=item.image_url, structured_url=item.structured_url,
            ))
    if evidence:
        validate = getattr(retriever, "validate_evidence", None)
        if validate is not None:
            try:
                await validate(evidence)
            except Exception:
                raise QuestionServiceError(stage="output", code="source_access_changed",
                    message="The sources changed or became unavailable. The answer was withheld. Please try again.") from None
    return QuestionResponse(answer=approved_output.text, sources=sources)
