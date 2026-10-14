"""Explicit LangSmith spans. Raw gate inputs, provider errors and images stay local.

Keep automatic LangChain tracing disabled beneath these spans: an output gate
cannot remove sensitive content from a trace that was already uploaded.
Telemetry failures must not change the question service's result.
"""

from contextlib import contextmanager
from functools import lru_cache

from langsmith import Client, get_current_run_tree, trace, tracing_context

from qozon_langchain.core.config import get_settings


def metadata_only(payload):
    """Drop content at the SDK upload boundary while preserving useful references."""
    if isinstance(payload, dict):
        return {key: metadata_only(value) for key, value in payload.items()
                if key not in {"question", "checked_question", "answer", "text", "explanation", "reference"}}
    if isinstance(payload, (list, tuple)):
        return [metadata_only(value) for value in payload]
    return payload


@lru_cache
def langsmith_client() -> Client | None:
    settings = get_settings()
    if not settings.langsmith_tracing or settings.langsmith_api_key is None:
        return None
    return Client(
        api_url=settings.langsmith_endpoint,
        api_key=settings.langsmith_api_key.get_secret_value(),
        workspace_id=settings.langsmith_workspace_id,
        timeout_ms=5000,
        # Checked content uploads need separate approval; default to references
        # and metrics even when LANGSMITH_TRACING is enabled.
        hide_inputs=False if settings.langsmith_trace_content else metadata_only,
        hide_outputs=False if settings.langsmith_trace_content else metadata_only,
        omit_traced_runtime_info=True,
    )


class SafeSpan:
    """Only explicit, checked values reach the SDK; never serialize function locals."""

    def __init__(self, run=None):
        self.run = run
        self.outputs = {}

    def inputs(self, **values):
        if self.run is not None:
            try:
                self.run.add_inputs(values)
            except Exception:
                pass

    def finish(self, **values):
        self.outputs.update(values)


@contextmanager
def trace_span(name: str, *, run_type="chain", inputs=None, metadata=None):
    try:
        client = langsmith_client()
    except Exception:
        client = None
    if client is None:
        yield SafeSpan()
        return
    with tracing_context(enabled=True, client=client, project_name=get_settings().langsmith_project):
        manager = trace(name, run_type, inputs=inputs or {}, metadata=metadata or {}, client=client)
        try:
            run = manager.__enter__()
        except Exception:
            yield SafeSpan()
            return
        span = SafeSpan(run)
        failed = False
        try:
            yield span
        except BaseException:
            failed = True
            raise
        finally:
            try:
                run.end(outputs=span.outputs, error="step_failed" if failed else None)
                # Do not pass the exception: the SDK otherwise records its traceback.
                manager.__exit__(None, None, None)
            except Exception:
                pass


def evidence_payload(evidence) -> list[dict]:
    """Checked retrieval text and public references; no image bytes or local paths."""
    return [dict(citation_id=f"S{n}", chunk_id=item.chunk_id, document_id=item.document_id,
                 physical_pages=list(item.page_numbers), content_type=item.content_type,
                 asset_id=item.parent_asset_id or None, text=item.text,
                 image_attached=item.image is not None)
            for n, item in enumerate(evidence, 1)]


def record_model_usage(response, *, model_name: str):
    """Attach provider token counts to the explicit LLM span, without its raw reply."""
    try:
        run = get_current_run_tree()
        if run is None:
            return
        usage = response.usage_metadata or {}
        usage = {key: value for key, value in usage.items()
                 if key in {"input_tokens", "output_tokens", "total_tokens"} and type(value) is int}
        run.add_metadata({"ls_provider": "openai", "ls_model_name": model_name})
        run.add_outputs({"usage_metadata": usage})
    except Exception:
        pass


def flush_traces():
    """Flush only an existing tracing client; shutdown must not load new keys."""
    if not langsmith_client.cache_info().currsize:
        return
    try:
        client = langsmith_client()
        if client is not None:
            client.flush(timeout=5)
    except Exception:
        pass
