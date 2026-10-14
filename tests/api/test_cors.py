"""Browser integration for the confirmed Cloudflare React origin; no paid calls."""

import pytest
from fastapi.testclient import TestClient

from qozon_langchain.api.app import create_app
from qozon_langchain.api.dependencies import get_answer_model, get_evidence_retriever
from qozon_langchain.core.config import get_settings
from qozon_langchain.api.limits import configured_limits

ORIGIN = "https://srahimov.site"


@pytest.fixture
def browser_client(monkeypatch):
    monkeypatch.setenv("QOZON_CORS_ORIGINS", '["https://srahimov.site"]')
    get_settings.cache_clear()
    class Model:
        calls = 0
        async def generate_answer(self, question):
            self.calls += 1
            return "A checked answer."
    model = Model()
    app = create_app()
    app.dependency_overrides[get_answer_model] = lambda: model
    app.dependency_overrides[get_evidence_retriever] = lambda: None
    with TestClient(app) as client:
        yield client, model


def preflight(client, origin, method="POST", headers="content-type"):
    return client.options("/questions", headers={"Origin": origin,
        "Access-Control-Request-Method": method, "Access-Control-Request-Headers": headers})


def test_approved_json_preflight_does_not_generate_answer(browser_client):
    client, model = browser_client
    response = preflight(client, ORIGIN)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-credentials" not in response.headers
    assert model.calls == 0


@pytest.mark.parametrize("origin,method,headers", [
    ("https://unapproved.example", "POST", "content-type"),
    ("http://srahimov.site", "POST", "content-type"),
    ("https://www.srahimov.site", "POST", "content-type"),
    (ORIGIN, "DELETE", "content-type"),
    (ORIGIN, "POST", "authorization"),
])
def test_unapproved_preflight_does_not_generate_answer(browser_client, origin, method, headers):
    client, model = browser_client
    assert preflight(client, origin, method, headers).status_code == 400
    assert model.calls == 0


def test_approved_answer_and_safe_errors_are_browser_readable(browser_client):
    client, model = browser_client
    for body, expected in [({"question": "Find repair services?"}, 200), ({"question": "a"*201}, 422)]:
        response = client.post("/questions", json=body, headers={"Origin": ORIGIN})
        assert response.status_code == expected
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert "Retry-After" in response.headers["access-control-expose-headers"]
    assert model.calls == 1


def test_public_nonbrowser_api_and_private_original_boundary_remain(browser_client):
    client, model = browser_client
    response = client.post("/questions", json={"question": "Find repair services?"})
    assert response.status_code == 200 and "access-control-allow-origin" not in response.headers
    original = client.get("/documents/00000000-0000-0000-0000-000000000001/source", headers={"Origin": ORIGIN})
    assert original.status_code == 404 and original.headers["access-control-allow-origin"] == ORIGIN
    # CORS controls browser response access, not authentication or non-browser calls.
    response = client.get("/health", headers={"Origin": "https://unapproved.example"})
    assert response.status_code == 200 and "access-control-allow-origin" not in response.headers


def test_preflight_does_not_use_daily_slot_and_browser_can_read_retry_after(monkeypatch, tmp_path):
    monkeypatch.setenv("QOZON_CORS_ORIGINS", '["https://srahimov.site"]')
    monkeypatch.setenv("QOZON_QUESTION_LIMITS_ENABLED", "true")
    monkeypatch.setenv("QOZON_QUESTION_LIMITS_DATABASE", str(tmp_path / "limits.sqlite3"))
    monkeypatch.setenv("QOZON_QUESTION_LIMIT_KEY", "synthetic-limit-key-at-least-32-characters")
    monkeypatch.setenv("QOZON_QUESTIONS_PER_DAY", "1")
    get_settings.cache_clear()
    configured_limits.cache_clear()
    class Model:
        calls = 0
        async def generate_answer(self, question):
            self.calls += 1
            return "A checked answer."
    model = Model()
    app = create_app()
    app.dependency_overrides[get_answer_model] = lambda: model
    app.dependency_overrides[get_evidence_retriever] = lambda: None
    with TestClient(app) as client:
        assert preflight(client, ORIGIN).status_code == 200
        assert client.post("/questions", json={"question": "Find repair services?"}, headers={"Origin": ORIGIN}).status_code == 200
        response = client.post("/questions", json={"question": "Find repair services?"}, headers={"Origin": ORIGIN})
    assert response.status_code == 429 and model.calls == 1
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert int(response.headers["retry-after"]) > 0
    assert "Retry-After" in response.headers["access-control-expose-headers"]
