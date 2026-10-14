import pytest
import asyncio

from qozon_langchain.knowledge_base.pdf.retrieval import Evidence
from qozon_langchain.security.policies import training_policy
from qozon_langchain.services.question_service import QuestionServiceError, answer_question


class FakeRetriever:
    def __init__(self, evidence=None):
        self.questions = []
        self.evidence = evidence if evidence is not None else [
            Evidence("chunk", "book", "synthetic.pdf", (7,), "text", "", "An answer supported by the book.")]

    async def retrieve(self, question):
        self.questions.append(question)
        return self.evidence


class FakeGroundedModel:
    def __init__(self, answer="An answer supported by the book. [S1]"):
        self.calls = []
        self.answer = answer

    async def generate_grounded_answer(self, question, evidence):
        self.calls.append((question, evidence))
        return self.answer


def run(question, model, retriever):
    import asyncio
    return asyncio.run(answer_question(question, model=model, retriever=retriever, policy=training_policy()))


def test_blocked_input_never_queries_index_or_model():
    model, retriever = FakeGroundedModel(), FakeRetriever()
    with pytest.raises(QuestionServiceError):
        run("password=synthetic-secret-value", model, retriever)
    assert model.calls == retriever.questions == []


def test_redacted_question_reaches_retrieval_and_citations_are_application_resolved():
    model, retriever = FakeGroundedModel(), FakeRetriever()
    result = run("SSN 567-55-4545. What does the book say?", model, retriever)
    assert "567-55-4545" not in retriever.questions[0]
    assert result.sources[0].physical_pages == [7] and result.sources[0].chunk_id == "chunk"
    assert result.sources[0].factually_verified is False


def test_empty_retrieval_returns_insufficient_evidence_without_generation():
    model, retriever = FakeGroundedModel(), FakeRetriever([])
    result = run("Some question", model, retriever)
    assert "sufficient evidence" in result.answer and result.sources == [] and model.calls == []


@pytest.mark.parametrize("answer", ["An uncited answer", "Wrong reference [S2]", "Wrong reference [S0]"])
def test_missing_or_fabricated_citations_are_withheld(answer):
    with pytest.raises(QuestionServiceError, match="source references"):
        run("Some question", FakeGroundedModel(answer), FakeRetriever())


def test_secret_in_grounded_answer_is_withheld():
    with pytest.raises(QuestionServiceError) as caught:
        run("Some question", FakeGroundedModel("password=synthetic-secret-value [S1]"), FakeRetriever())
    assert caught.value.stage == "output"


def test_retrieval_failure_has_fixed_safe_error_and_no_generation():
    class BrokenRetriever:
        async def retrieve(self, question):
            raise RuntimeError("private-document-content")
    model = FakeGroundedModel()
    with pytest.raises(QuestionServiceError) as caught:
        run("Some question", model, BrokenRetriever())
    assert caught.value.code == "retrieval_unavailable" and "private" not in str(caught.value)
    assert model.calls == []


def test_conflict_replacement_cannot_bypass_output_privacy_checks():
    evidence = [
        Evidence("one", "book", "fixture.txt", (11,), "text", "", "password=synthetic-source-secret The jar contains four stones."),
        Evidence("two", "book", "fixture.txt", (12,), "text", "", "The jar contains six stones."),
    ]
    with pytest.raises(QuestionServiceError) as caught:
        run("What is the count?", FakeGroundedModel("The sources conflict [S1] [S2]. I cannot determine the count."), FakeRetriever(evidence))
    assert caught.value.code == "output_contains_secrets"
    assert "synthetic-source-secret" not in str(caught.value)


def test_evidence_checker_failure_withholds_with_fixed_error(monkeypatch):
    from qozon_langchain.services import question_service
    def broken(*args):
        raise RuntimeError("private-fixture-details")
    monkeypatch.setattr(question_service, "verify_evidence", broken)
    with pytest.raises(QuestionServiceError) as caught:
        run("What does the source say?", FakeGroundedModel(), FakeRetriever())
    assert caught.value.stage == "output" and caught.value.code == "evidence_check_unavailable"
    assert "private-fixture" not in str(caught.value)


@pytest.mark.parametrize("slow_stage", ["retrieval", "model"])
def test_workflow_deadline_cancels_waiting_stage_without_followup_calls(slow_stage):
    cancelled = []
    class SlowRetriever(FakeRetriever):
        async def retrieve(self, question):
            if slow_stage == "retrieval":
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append("retrieval")
            return await super().retrieve(question)
    class SlowModel(FakeGroundedModel):
        async def generate_grounded_answer(self, question, evidence):
            self.calls.append((question, evidence))
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append("model")
    model = SlowModel()
    async def check():
        with pytest.raises(QuestionServiceError) as caught:
            await asyncio.wait_for(answer_question("What does the source say?", model=model,
                retriever=SlowRetriever(), policy=training_policy(), timeout_seconds=0.01), timeout=1)
        assert caught.value.code == "question_timeout"
    asyncio.run(check())
    assert cancelled == [slow_stage]
    assert len(model.calls) == (0 if slow_stage == "retrieval" else 1)


def test_caller_cancellation_propagates_instead_of_returning_or_retrying():
    class CancelledModel(FakeGroundedModel):
        async def generate_grounded_answer(self, *args):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        run("What does the source say?", CancelledModel(), FakeRetriever())
