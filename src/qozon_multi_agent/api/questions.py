"""HTTP question endpoint using the single input gate and lazy supervisor dependency."""

from fastapi import APIRouter, Depends, HTTPException, Request

from qozon_multi_agent.api.dependencies import get_supervisor_factory
from qozon_multi_agent.api.schemas import APIErrorResponse, QuestionRequest, QuestionResponse
from qozon_multi_agent.api.limits import admit_question
from qozon_multi_agent.services.question_service import QuestionServiceError, answer_question

router = APIRouter(tags=["questions"], responses={
    422: {"model": APIErrorResponse, "description": "Invalid question body; input is not echoed."},
    500: {"model": APIErrorResponse, "description": "A checked answer could not be provided."},
})


@router.post("/questions", response_model=QuestionResponse, response_model_exclude_defaults=True, responses={
    400: {"model": APIErrorResponse, "description": "Input blocked by required checks."},
    409: {"model": APIErrorResponse, "description": "Input held for review; no model call."},
    429: {"model": APIErrorResponse, "description": "Visitor or daily question allowance exhausted; no paid call.",
          "headers": {"Retry-After": {"description": "Seconds until the relevant allowance resets.",
                                      "schema": {"type": "integer", "minimum": 1}}}},
    502: {"model": APIErrorResponse, "description": "A checked answer could not be returned."},
    503: {"model": APIErrorResponse, "description": "Model configuration, provider, or required checks unavailable."},
    504: {"model": APIErrorResponse, "description": "Question workflow or model request timed out."},
})
async def ask_question(
    request: QuestionRequest, http_request: Request,
    supervisor_factory=Depends(get_supervisor_factory),
) -> QuestionResponse:
    """Return only gated answers, translating safe service errors into HTTP errors."""
    await admit_question(http_request)
    try:
        result = await answer_question(request.question, supervisor_factory=supervisor_factory)
        return result
    except QuestionServiceError as error:
        if error.code in {"model_timeout", "question_timeout"}:
            status = 504
        elif error.code in {"input_check_unavailable", "output_check_unavailable", "evidence_check_unavailable"}:
            status = 503
        elif error.stage == "input":
            status = 409 if error.code == "input_needs_review" else 400
        elif error.stage == "output" or error.code in {"model_incomplete", "invalid_model_answer"}:
            status = 502
        else:
            status = 503
        message = (
            "Question answering needs local model configuration before it can run."
            if error.code == "model_not_configured" else error.message
        )
        raise HTTPException(status_code=status, detail={"code": error.code, "message": message}) from None
    except Exception:
        raise HTTPException(
            status_code=500,
            detail={"code": "question_failed", "message": "A checked answer could not be provided. Please try again."},
        ) from None
