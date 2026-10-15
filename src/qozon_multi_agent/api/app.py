"""Phase 1 API with health and a gated question service."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio

from qozon_multi_agent.api.dependencies import model_configuration_ready, rag_index_status
from qozon_multi_agent.api.questions import router as questions_router
from qozon_multi_agent.api.limits import configured_limits
from qozon_multi_agent.api.documents import NO_CACHE_HEADERS, router as documents_router
from qozon_multi_agent.core.config import get_settings
from qozon_multi_agent.knowledge_base.documents import DocumentAccessError


class ConfiguredCORS(CORSMiddleware):
    """Read browser origins when ASGI builds the stack, keeping imports lazy."""

    def __init__(self, app):
        super().__init__(app, allow_origins=get_settings().cors_origins,
                         allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
                         allow_credentials=False, expose_headers=["Retry-After"])


@asynccontextmanager
async def lifespan(app):
    try:
        await asyncio.to_thread(configured_limits)
    except Exception:
        raise RuntimeError("question_limits_unavailable") from None
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        lifespan=lifespan,
        title="Qozon Multi Agent",
        version="0.1.0",
        description="Gated question API with configurable PDF retrieval and physical-page citations.",
    )
    app.add_middleware(ConfiguredCORS)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Structured validation errors can retain user input; return a fixed message.
        private = request.url.path.startswith("/documents")
        return JSONResponse(
            status_code=422,
            headers=NO_CACHE_HEADERS if private else None,
            content={"detail": {"code": "invalid_request", "message":
                     "Document request is invalid." if private else "Question request is invalid."}},
        )

    @app.exception_handler(DocumentAccessError)
    async def document_error(request: Request, exc: DocumentAccessError) -> JSONResponse:
        headers = {**NO_CACHE_HEADERS}
        return JSONResponse(status_code=exc.status, headers=headers,
                            content={"detail": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(ResponseValidationError)
    async def invalid_response(request: Request, exc: ResponseValidationError) -> JSONResponse:
        return JSONResponse(status_code=502, headers=NO_CACHE_HEADERS,
                            content={"detail": {"code": "invalid_response",
                                                "message": "A checked response could not be provided."}})

    app.include_router(questions_router)
    app.include_router(documents_router)

    @app.get("/health", tags=["foundation"])
    def health() -> dict[str, str | bool | int]:
        result = {
            "status": "ok",
            "stage": "foundation",
            "question_api": "wired",
            "model_calls_enabled": model_configuration_ready(),
            "provider_connection": "not_checked",
        }
        result.update(rag_index_status())
        return result

    return app


app = create_app()
