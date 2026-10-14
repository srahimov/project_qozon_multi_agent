import asyncio
from types import SimpleNamespace
import uuid

from langsmith.utils import LangSmithNotFoundError
import pytest

from qozon_langchain.evaluation.langsmith_rag import (
    AnswerJudge, EvaluationTarget, JudgeResult, accepts_scores, deterministic_scores, load_cases, sync_dataset,
)
from qozon_langchain.knowledge_base.pdf.retrieval import Evidence


class DatasetClient:
    def __init__(self):
        self.dataset = None
        self.examples = []

    def read_dataset(self, **kw):
        if self.dataset is None:
            raise LangSmithNotFoundError("not_found")
        return self.dataset

    def create_dataset(self, dataset_name, **kw):
        self.dataset = SimpleNamespace(id=uuid.uuid4(), name=dataset_name)
        return self.dataset

    def list_examples(self, **kw):
        return self.examples

    def create_examples(self, examples, **kw):
        self.examples.extend(SimpleNamespace(**row) for row in examples)


def test_dataset_repeated_sync_is_idempotent_and_changed_gold_is_rejected():
    client, cases = DatasetClient(), load_cases()
    sync_dataset(client, cases)
    sync_dataset(client, cases)
    assert len(client.examples) == 6
    cases[0].reference.answer = "Changed reference."
    with pytest.raises(ValueError, match="dataset_changed"):
        sync_dataset(client, cases)


def test_dataset_server_split_metadata_does_not_change_reviewed_case():
    client, cases = DatasetClient(), load_cases()
    sync_dataset(client, cases)
    for example in client.examples:
        example.metadata["dataset_split"] = ["base"]
    sync_dataset(client, cases)
    assert len(client.examples) == 6
    client.examples[0].metadata["reference_status"] = "changed_review_status"
    with pytest.raises(ValueError, match="dataset_changed"):
        sync_dataset(client, cases)


def test_acceptance_fails_missing_judgments_or_failed_scores():
    reference = load_cases()[1].reference
    keys = ["workflow_outcome", "privacy_boundary", "retrieval_page_hit", "citation_integrity",
            "cited_reference_page", "answer_correctness", "answer_groundedness",
            "source_url_integrity", "public_source_access"]
    scores = [{"key": key, "score": 1} for key in keys]
    assert accepts_scores(scores, reference)
    assert not accepts_scores([s for s in scores if s["key"] != "answer_correctness"], reference)
    assert not accepts_scores(scores + [{"key": "judge_available", "score": 0}], reference)
    assert not accepts_scores(scores + [scores[0]], reference)
    scores[-1]["score"] = 0
    assert not accepts_scores(scores, reference)


class Retriever:
    def __init__(self):
        self.queries = []

    async def retrieve(self, question):
        self.queries.append(question)
        return [Evidence("chunk", "book", "book.pdf", (4,), "text", "", "The book states its purpose.")]


class Model:
    async def generate_grounded_answer(self, question, evidence):
        return "The book states its purpose. [S1]"


def test_evaluation_runs_same_gated_service_and_exposes_only_checked_evidence():
    retriever = Retriever()
    target = EvaluationTarget(Model(), retriever)
    result = asyncio.run(target({"question": "My SSN is 000-12-3456. What is the purpose?"}))
    assert "000-12-3456" not in str(result)
    assert "[REDACTED_SSN]" in retriever.queries[0]
    assert result["model_calls"] == 1 and result["sources"][0]["physical_pages"] == [4]
    example = SimpleNamespace(outputs=dict(expected_pages=[4], expected_content_type="text",
                                           forbidden_text=["000-12-3456"]))
    scores = deterministic_scores(SimpleNamespace(outputs=result), example)["results"]
    assert all(score["score"] == 1 for score in scores)


def test_blocked_case_makes_no_retrieval_or_model_call():
    retriever = Retriever()
    target = EvaluationTarget(Model(), retriever)
    result = asyncio.run(target({"question": "password=synthetic-evaluation-secret"}))
    assert result["code"] == "input_contains_secrets" and result["model_calls"] == 0
    assert not retriever.queries and not result["evidence"]


def test_fabricated_citations_and_wrong_reference_pages_score_zero():
    run = SimpleNamespace(outputs=dict(status="success", code=None, model_calls=1,
        answer="Claim. [S2]", checked_question="Question?",
        evidence=[dict(citation_id="S1", chunk_id="a", document_id="b", physical_pages=[4], content_type="text")],
        sources=[dict(citation_id="S2", chunk_id="wrong", document_id="b", physical_pages=[99], content_type="text")]))
    example = SimpleNamespace(outputs=dict(expected_pages=[5], expected_content_type="text"))
    scores = {s["key"]: s["score"] for s in deterministic_scores(run, example)["results"]}
    assert scores["citation_integrity"] == 0
    assert scores["retrieval_page_hit"] == 0 and scores["cited_reference_page"] == 0


def test_installed_sdk_accepts_async_target_and_multi_score_evaluator_offline(monkeypatch):
    from datetime import datetime, timezone
    from langsmith import Client
    from langsmith.schemas import Example
    # The SDK's beta upload_results=False still explicitly enables target tracing.
    # Stub run writes as well; this test must never attempt a real network call.
    monkeypatch.setattr(Client, "create_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(Client, "update_run", lambda *args, **kwargs: None)
    target = EvaluationTarget(Model(), Retriever())
    example = Example(id=uuid.uuid4(), dataset_id=uuid.uuid4(), created_at=datetime.now(timezone.utc),
                      inputs={"question": "What is the purpose?"},
                      outputs=dict(expected_pages=[4], expected_content_type="text"))
    async def execute():
        client = Client(api_key="synthetic-key", auto_batch_tracing=False)
        results = await client.aevaluate(target.__call__, data=[example], evaluators=[deterministic_scores],
                                         upload_results=False, disable_evaluator_tracing=True, max_concurrency=1)
        return [row async for row in results]
    rows = asyncio.run(execute())
    assert len(rows) == 1
    scores = {s.key: s.score for s in rows[0]["evaluation_results"]["results"]}
    assert all(score == 1 for score in scores.values()), (scores, rows[0]["run"].outputs)


def test_vision_judge_receives_local_pixels_but_feedback_does_not_include_them():
    from langchain_core.messages import AIMessage
    from qozon_langchain.core.config import Settings
    target = EvaluationTarget(Model(), Retriever())
    target.local_evidence["Describe the picture."] = [Evidence(
        "chunk", "book", "book.pdf", (2,), "image_description", "picture", "Checked description",
        image=b"synthetic-pixel-data")]
    judge = AnswerJudge(Settings(_env_file=None, openai_api_key="synthetic-key"), target)
    sent = []
    class FakeJudge:
        async def ainvoke(self, messages, **kw):
            sent.extend(messages)
            return dict(parsed=JudgeResult(answer_correct=True, grounded=True,
                                           explanation="Contact person@example.com for review."),
                        raw=AIMessage(content="synthetic"), parsing_error=None)
    judge.structured = FakeJudge()
    run = SimpleNamespace(outputs=dict(status="success", checked_question="Describe the picture.",
                                       answer="Picture answer.", evidence=[]))
    example = SimpleNamespace(inputs={"question": "Describe the picture."}, outputs={"answer": "Reference."})
    scores = asyncio.run(judge(run, example))
    assert sent[-1].content[1]["type"] == "image_url"
    assert "person@example.com" not in str(scores)
    assert "synthetic-pixel-data" not in str(scores)


def test_judge_failure_is_reported_as_unavailable_not_success():
    from qozon_langchain.core.config import Settings
    target = EvaluationTarget(Model(), Retriever())
    judge = AnswerJudge(Settings(_env_file=None, openai_api_key="synthetic-key"), target)
    class BrokenJudge:
        async def ainvoke(self, *args, **kw):
            raise RuntimeError("private-provider-body")
    judge.structured = BrokenJudge()
    run = SimpleNamespace(outputs=dict(status="success", checked_question="Question?", answer="Answer.", evidence=[]))
    example = SimpleNamespace(inputs={"question": "Question?"}, outputs={"answer": "Reference."})
    scores = asyncio.run(judge(run, example))
    assert scores["results"][0]["key"] == "judge_available"
    assert scores["results"][0]["score"] == 0 and "private-provider-body" not in str(scores)
