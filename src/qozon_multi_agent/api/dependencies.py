"""Lazy API model configuration; no key loading or provider calls on import."""

from functools import lru_cache
import asyncio
import json

from qozon_multi_agent.core.config import get_settings
from qozon_multi_agent.agents.supervisor import build_configured_supervisor
from qozon_multi_agent.knowledge_base.documents import DocumentAccessError, DocumentReader


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
def _configured_supervisor():
    """Reuse a stateless agent/client graph; each invocation has its own messages."""
    return build_configured_supervisor()


def get_supervisor_factory():
    """Return construction capability; the service calls it only after input approval."""
    return _configured_supervisor


def model_configuration_ready() -> bool:
    """Check key/budget presence only; this makes no request to OpenAI."""
    try:
        settings = get_settings()
        return bool(settings.openai_api_key is not None and settings.output_max_tokens is not None
                    and settings.rag_enabled and settings.rag_backend == "supabase"
                    and settings.supabase_url and settings.supabase_publishable_key)
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
