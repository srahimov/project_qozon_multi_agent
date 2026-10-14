"""Lazy API model configuration; no key loading or provider calls on import."""

from functools import lru_cache
import asyncio
import json

from qozon_langchain.core.config import get_settings
from qozon_langchain.llm.model import OpenAIAnswerModel, build_openai_model
from qozon_langchain.services.question_service import AnswerModel, ModelInvocationError
from qozon_langchain.knowledge_base.documents import DocumentAccessError, DocumentReader


async def get_document_reader():
    """One anonymous read-only client per request; no visitor login required."""
    try:
        async with asyncio.timeout(45):
            try:
                reader = DocumentReader(get_settings())
            except DocumentAccessError:
                raise
            except Exception:
                raise DocumentAccessError("document_access_not_configured") from None
            async with reader.client:
                yield reader
    except TimeoutError:
        raise DocumentAccessError("document_access_timeout") from None


@lru_cache
def _configured_model() -> OpenAIAnswerModel:
    """Reuse a client after successful construction; restart after config changes."""
    return build_openai_model(get_settings())


class ConfiguredAnswerModel:
    """Construct the provider only when the service approves model input."""

    async def generate_answer(self, question: str) -> str:
        try:
            client = _configured_model()
        except Exception:
            raise ModelInvocationError("model_not_configured") from None
        return await client.generate_answer(question)

    async def generate_grounded_answer(self, question: str, evidence: list) -> str:
        try:
            client = _configured_model()
        except Exception:
            raise ModelInvocationError("model_not_configured") from None
        return await client.generate_grounded_answer(question, evidence)


@lru_cache
def _configured_retriever():
    from qozon_langchain.knowledge_base.pdf.retrieval import build_retriever
    return build_retriever(get_settings())


class ConfiguredRetriever:
    async def retrieve(self, question):
        return await _configured_retriever().retrieve(question)

    async def validate_evidence(self, evidence):
        validate = getattr(_configured_retriever(), "validate_evidence", None)
        if validate is not None:
            await validate(evidence)


def get_evidence_retriever():
    """Open the index and embedding client only after input approval."""
    return ConfiguredRetriever() if get_settings().rag_enabled else None


def get_answer_model() -> AnswerModel:
    """FastAPI dependency; tests replace this with a fake model."""
    return ConfiguredAnswerModel()


def model_configuration_ready() -> bool:
    """Check key/budget presence only; this makes no request to OpenAI."""
    try:
        settings = get_settings()
        return settings.openai_api_key is not None and settings.output_max_tokens is not None
    except Exception:
        return False


def rag_index_status() -> dict:
    """Inspect local configuration/index headers, without provider calls."""
    result = {}
    try:
        settings = get_settings()
        if not settings.rag_enabled:
            return result
        result.update(stage="pdf_rag", rag_enabled=True, rag_index="unavailable", rag_backend=settings.rag_backend)
        if settings.rag_backend == "supabase":
            # Health is configuration-only; readiness requires real public reads.
            result["rag_index"] = "configured" if settings.supabase_url and settings.supabase_publishable_key else "unavailable"
            return result
        index = json.loads((settings.rag_vector_directory / "index-manifest.json").read_text())
        corpus = json.loads((settings.rag_chunks_directory / "manifest.json").read_text())
        if (index["status"] == "complete" and index["corpus_sha256"] == corpus["corpus_sha256"]
                and index["model"] == settings.embedding_model_name
                and index["dimensions"] == settings.embedding_dimensions):
            result.update(rag_index="ready", indexed_chunks=index["completed_chunks"])
    except Exception:
        pass
    return result
