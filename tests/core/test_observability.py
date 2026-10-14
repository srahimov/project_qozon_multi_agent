"""Capture actual SDK span serialization without a LangSmith network connection."""

import asyncio
import json

from langsmith import Client
import pytest

from qozon_langchain.core import observability
from qozon_langchain.security.policies import training_policy
from qozon_langchain.services.question_service import QuestionServiceError, answer_question


@pytest.fixture
def recorded_spans(monkeypatch):
    operations = []
    monkeypatch.setattr(Client, "create_run", lambda self, **kw: operations.append(kw))
    monkeypatch.setattr(Client, "update_run", lambda self, run_id, **kw: operations.append(dict(kw, id=run_id)))
    client = Client(api_key="synthetic-langsmith-key", auto_batch_tracing=False)
    monkeypatch.setattr(observability, "langsmith_client", lambda: client)
    return operations


class FakeModel:
    async def generate_answer(self, question):
        return "Checked synthetic answer."


def test_successful_trace_has_gate_model_and_checked_output(recorded_spans):
    response = asyncio.run(answer_question("Contact person@example.com", model=FakeModel(), policy=training_policy()))
    raw = json.dumps(recorded_spans, default=str)
    names = [r.get("name") for r in recorded_spans]
    assert {"question_workflow", "input_gate", "generate_answer", "output_gate"}.issubset(names)
    assert "person@example.com" not in raw
    assert "[REDACTED_EMAIL]" in raw and response.answer in raw
    roots = [r for r in recorded_spans if r.get("name") == "question_workflow"]
    children = [r for r in recorded_spans if r.get("parent_run_id")]
    assert len({str(r["id"]) for r in roots}) == 1
    assert all(str(c["parent_run_id"]) == str(roots[0]["id"]) for c in children)


def test_blocked_input_never_appears_in_trace_or_calls_model(recorded_spans):
    class NeverModel:
        async def generate_answer(self, question):
            pytest.fail("Blocked question reached the model")
    with pytest.raises(QuestionServiceError):
        asyncio.run(answer_question("password=synthetic-private-value", model=NeverModel(), policy=training_policy()))
    raw = json.dumps(recorded_spans, default=str)
    assert "synthetic-private-value" not in raw and "input_contains_secrets" in raw
    assert not any(r.get("name") == "generate_answer" for r in recorded_spans)


@pytest.mark.parametrize("kind", ["output", "exception"])
def test_unsafe_reply_and_exception_context_are_not_traced(recorded_spans, kind):
    class BrokenModel:
        async def generate_answer(self, question):
            if kind == "exception":
                raise RuntimeError("provider-body: synthetic-private-value")
            return "password=synthetic-private-value"
    with pytest.raises(QuestionServiceError):
        asyncio.run(answer_question("Ordinary question?", model=BrokenModel(), policy=training_policy()))
    assert "synthetic-private-value" not in json.dumps(recorded_spans, default=str)
    assert "Traceback" not in json.dumps(recorded_spans, default=str)


def test_telemetry_failure_does_not_change_answer(monkeypatch):
    def broken():
        raise RuntimeError("telemetry-unavailable")
    monkeypatch.setattr(observability, "langsmith_client", broken)
    response = asyncio.run(answer_question("Ordinary question?", model=FakeModel(), policy=training_policy()))
    assert response.answer == "Checked synthetic answer."


def test_evidence_trace_excludes_image_bytes_and_paths():
    from qozon_langchain.knowledge_base.pdf.retrieval import Evidence
    item = Evidence("chunk", "book", "book.pdf", (2,), "image_description", "picture",
                    "Checked image description", image=b"private-image-data")
    payload = observability.evidence_payload([item])
    assert payload[0]["image_attached"] is True
    assert "private-image-data" not in json.dumps(payload)


def test_metadata_mode_removes_nested_content_but_keeps_source_references():
    payload = dict(question="private question", answer="private answer", status="success",
                   evidence=[dict(text="private passage", physical_pages=[5], chunk_id="chunk")],
                   usage_metadata=dict(input_tokens=12, output_tokens=4))
    filtered = observability.metadata_only(payload)
    assert "private" not in json.dumps(filtered)
    assert filtered["evidence"][0]["physical_pages"] == [5]
    assert filtered["usage_metadata"]["input_tokens"] == 12
