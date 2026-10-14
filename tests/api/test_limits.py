"""Admission limits use temporary disks and scripted models, never paid calls."""

from concurrent.futures import ThreadPoolExecutor
import asyncio
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from qozon_langchain.api.app import create_app
from qozon_langchain.api.dependencies import get_answer_model, get_evidence_retriever
from qozon_langchain.api.limits import QuestionLimitReached, QuestionLimits, configured_limits
from qozon_langchain.core.config import get_settings

KEY = "synthetic-limit-key-at-least-32-characters"


def configure(monkeypatch, tmp_path, *, minute=5, daily=100):
    monkeypatch.setattr("qozon_langchain.api.limits.time", SimpleNamespace(time=lambda: 86400))
    monkeypatch.setenv("QOZON_QUESTION_LIMITS_ENABLED", "true")
    monkeypatch.setenv("QOZON_QUESTION_LIMITS_DATABASE", str(tmp_path / "limits.sqlite3"))
    monkeypatch.setenv("QOZON_QUESTION_LIMIT_KEY", KEY)
    monkeypatch.setenv("QOZON_QUESTIONS_PER_MINUTE", str(minute))
    monkeypatch.setenv("QOZON_QUESTIONS_PER_DAY", str(daily))
    get_settings.cache_clear()
    configured_limits.cache_clear()


class Model:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    async def generate_answer(self, question):
        self.calls += 1
        if self.fail:
            raise RuntimeError("synthetic-private-provider-error")
        return "A checked answer."


def application(model):
    app = create_app()
    app.dependency_overrides[get_answer_model] = lambda: model
    app.dependency_overrides[get_evidence_retriever] = lambda: None
    return app


def test_counters_persist_and_minute_and_utc_day_reset(tmp_path):
    path = tmp_path / "limits.sqlite3"
    QuestionLimits(path, KEY, 1, 2).admit("192.0.2.1", now=86400)
    restarted = QuestionLimits(path, KEY, 1, 2)
    with pytest.raises(QuestionLimitReached) as blocked:
        restarted.admit("192.0.2.1", now=86401)
    assert (blocked.value.code, blocked.value.retry_after) == ("question_rate_limited", 59)
    restarted.admit("192.0.2.1", now=86460)
    with pytest.raises(QuestionLimitReached) as blocked:
        restarted.admit("192.0.2.2", now=86500)
    assert blocked.value.code == "daily_question_limit_reached"
    restarted.admit("192.0.2.1", now=172800)
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT * FROM requests").fetchall()
    assert len(rows) == 2  # expired minute/day/client rows pruned
    assert "192.0.2.1" not in str(rows) and KEY not in str(rows)


@pytest.mark.parametrize("same_client,minute,daily,expected", [(False, 5, 7, 7), (True, 3, 100, 3)])
def test_atomic_admission_across_independent_instances(tmp_path, same_client, minute, daily, expected):
    limits = [QuestionLimits(tmp_path / "limits.sqlite3", KEY, minute, daily) for _ in range(2)]
    def attempt(i):
        try:
            limits[i % 2].admit("shared" if same_client else str(i), now=86400)
            return True
        except QuestionLimitReached:
            return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(attempt, range(32))) == expected


def test_http_limit_blocks_before_retrieval_and_generation_and_ignores_forged_forwarded_ip(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, minute=1)
    model = Model()
    class Retriever:
        calls = 0
        async def retrieve(self, question):
            self.calls += 1
            return []
    retriever = Retriever()
    app = application(model)
    app.dependency_overrides[get_evidence_retriever] = lambda: retriever
    with TestClient(app) as client:
        assert client.post("/questions", json={"question": "What is in the book?"}).status_code == 200
        response = client.post("/questions", json={"question": "What is in the book?"},
                               headers={"X-Forwarded-For": "192.0.2.99"})
        assert response.status_code == 429
        assert response.json()["detail"]["code"] == "question_rate_limited"
        assert int(response.headers["retry-after"]) in range(1, 61)
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/health").status_code == 200
        assert client.get("/documents/00000000-0000-0000-0000-000000000001/source").status_code == 404
    assert retriever.calls == 1 and model.calls == 0


def test_failure_is_not_refunded_or_retried(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, daily=1)
    model = Model(fail=True)
    with TestClient(application(model)) as client:
        assert client.post("/questions", json={"question": "Find repair services?"}).status_code == 503
        blocked = client.post("/questions", json={"question": "Find repair services?"})
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "daily_question_limit_reached"
    assert model.calls == 1 and "synthetic-private" not in blocked.text


def test_invalid_body_does_not_consume_allowance(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, daily=1)
    model = Model()
    with TestClient(application(model)) as client:
        assert client.post("/questions", json={"question": "a" * 201}).status_code == 422
        assert client.post("/questions", json={"question": "Find repair services?"}).status_code == 200
    assert model.calls == 1


def test_broken_counter_fails_closed_without_leaking_details(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    model = Model()
    with TestClient(application(model)) as client:
        def broken(client):
            raise sqlite3.OperationalError("synthetic-private-path")
        monkeypatch.setattr(configured_limits(), "admit", broken)
        response = client.post("/questions", json={"question": "Find repair services?"})
    assert response.status_code == 503 and model.calls == 0
    assert response.json()["detail"]["code"] == "question_limits_unavailable"
    assert "synthetic-private" not in response.text


def test_missing_key_stops_startup(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    monkeypatch.delenv("QOZON_QUESTION_LIMIT_KEY")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="^question_limits_unavailable$"):
        with TestClient(application(Model())):
            pass


def test_limit_also_applies_when_asgi_caller_skips_lifespan(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, daily=1)
    model = Model()
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(model)), base_url="http://test") as client:
            assert (await client.post("/questions", json={"question": "Find repair services?"})).status_code == 200
            assert (await client.post("/questions", json={"question": "Find repair services?"})).status_code == 429
    asyncio.run(check())
    assert model.calls == 1
