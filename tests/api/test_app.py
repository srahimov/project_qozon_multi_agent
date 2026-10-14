"""Application health and registration checks without model calls."""

from fastapi.testclient import TestClient

from qozon_langchain.api.app import create_app


def test_health_reports_wired_service_without_provider_verification() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "stage": "foundation",
            "question_api": "wired",
            "model_calls_enabled": False,
            "provider_connection": "not_checked",
        }
        assert client.post("/questions", json={"question": "Hello"}).status_code == 503


def test_health_checks_rag_index_headers_without_provider_calls(tmp_path, monkeypatch):
    import json
    import qozon_langchain.api.dependencies as dependencies
    from qozon_langchain.core.config import Settings
    chunks, vectors = tmp_path / "chunks", tmp_path / "vectors"
    chunks.mkdir(); vectors.mkdir()
    (chunks / "manifest.json").write_text(json.dumps({"corpus_sha256": "corpus"}))
    index = {"status": "complete", "corpus_sha256": "corpus", "model": "text-embedding-3-small",
             "dimensions": 1536, "completed_chunks": 12}
    (vectors / "index-manifest.json").write_text(json.dumps(index))
    settings = Settings(_env_file=None, openai_api_key=None, rag_enabled=True,
                        rag_chunks_directory=chunks, rag_vector_directory=vectors)
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        health = client.get("/health").json()
    assert health["rag_index"] == "ready" and health["indexed_chunks"] == 12
    assert health["model_calls_enabled"] is False
    index["dimensions"] = 7
    (vectors / "index-manifest.json").write_text(json.dumps(index))
    with TestClient(create_app()) as client:
        assert client.get("/health").json()["rag_index"] == "unavailable"
