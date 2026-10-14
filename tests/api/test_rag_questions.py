from fastapi.testclient import TestClient

from qozon_langchain.api.app import create_app
from qozon_langchain.api.dependencies import get_answer_model, get_evidence_retriever
from qozon_langchain.knowledge_base.pdf.retrieval import Evidence


def test_http_rag_returns_resolved_sources_without_local_paths():
    class Retriever:
        async def retrieve(self, question):
            return [Evidence("chunk", "book", "synthetic.pdf", (12, 13), "table_summary", "asset", "The table contains this information.")]

    class Model:
        async def generate_grounded_answer(self, question, evidence):
            return "The table contains this information. [S1]"

    app = create_app()
    app.dependency_overrides[get_answer_model] = Model
    app.dependency_overrides[get_evidence_retriever] = Retriever
    with TestClient(app) as client:
        response = client.post("/questions", json={"question": "What does the table contain?"})
    assert response.status_code == 200
    source = response.json()["sources"][0]
    assert source["physical_pages"] == [12, 13] and source["asset_id"] == "asset"
    assert source["factually_verified"] is False
    assert "manifest" not in source and "/Users/" not in response.text


def test_rag_http_blocks_before_retrieval_and_missing_citations_return_safe_error():
    calls = []

    class Retriever:
        async def retrieve(self, question):
            calls.append(question)
            return [Evidence("chunk", "book", "synthetic.pdf", (12,), "text", "", "Evidence.")]

    class Model:
        async def generate_grounded_answer(self, question, evidence):
            return "Answer without a source citation."

    app = create_app()
    app.dependency_overrides[get_answer_model] = Model
    app.dependency_overrides[get_evidence_retriever] = Retriever
    with TestClient(app) as client:
        blocked = client.post("/questions", json={"question": "password=synthetic-secret-value"})
        assert blocked.status_code == 400 and calls == []
        disclosure = client.post("/questions", json={"question": "My password is example-password-123. What is in the book?"})
        assert disclosure.status_code == 400 and calls == []
        failed = client.post("/questions", json={"question": "What does the book say?"})
    assert failed.status_code == 502 and failed.json()["detail"]["code"] == "invalid_source_citation"


def test_rag_http_withholds_unsupported_claim_and_unavailable_verifier(monkeypatch):
    from qozon_langchain.services import question_service
    class Retriever:
        async def retrieve(self, question):
            return [Evidence("chunk", "book", "fixture.txt", (11,), "text", "", "The box is red.")]
    class Model:
        async def generate_grounded_answer(self, question, evidence):
            return "The box contains five stones. [S1]"
    app = create_app()
    app.dependency_overrides[get_answer_model] = Model
    app.dependency_overrides[get_evidence_retriever] = Retriever
    with TestClient(app) as client:
        failed = client.post("/questions", json={"question": "What is in the box?"})
        assert failed.status_code == 502 and failed.json()["detail"]["code"] == "unsupported_answer"
        assert "five stones" not in failed.text
        def broken(*args):
            raise RuntimeError("private-fixture-details")
        monkeypatch.setattr(question_service, "verify_evidence", broken)
        unavailable = client.post("/questions", json={"question": "What is in the box?"})
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["code"] == "evidence_check_unavailable"
        assert "private-fixture" not in unavailable.text
