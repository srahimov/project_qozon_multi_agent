"""The container accepts questions only after the private edge admission boundary."""

import pytest
from fastapi.testclient import TestClient

from qozon_langchain.api.limits import configured_limits
from tests.api.test_limits import KEY, Model, application, configure


@pytest.mark.parametrize("headers", [
    {}, {"X-Qozon-Admission": "visitor-forged"},
    {"CF-Connecting-IP": "192.0.2.1", "X-Forwarded-For": "192.0.2.2"},
])
def test_cloudflare_questions_require_internal_admission(monkeypatch, tmp_path, headers):
    configure(monkeypatch, tmp_path)
    monkeypatch.setenv("QOZON_QUESTION_LIMITS_BACKEND", "cloudflare")
    model = Model()
    with TestClient(application(model)) as client:
        response = client.post("/questions", json={"question": "Find repair services?"}, headers=headers)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "question_limits_unavailable"
    assert model.calls == 0
    assert not (tmp_path / "limits.sqlite3").exists()


def test_edge_admission_has_no_ephemeral_duplicate_counter(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, daily=1)
    monkeypatch.setenv("QOZON_QUESTION_LIMITS_BACKEND", "cloudflare")
    model = Model()
    with TestClient(application(model)) as client:
        for _ in range(2):
            assert client.post("/questions", json={"question": "Find repair services?"},
                               headers={"X-Qozon-Admission": KEY}).status_code == 200
        assert client.get("/health").status_code == 200
    assert model.calls == 2
    assert configured_limits() is None
    assert not (tmp_path / "limits.sqlite3").exists()


@pytest.mark.parametrize("enabled,key", [("false", KEY), ("true", "")])
def test_cloudflare_configuration_fails_closed_at_startup(monkeypatch, tmp_path, enabled, key):
    configure(monkeypatch, tmp_path)
    monkeypatch.setenv("QOZON_QUESTION_LIMITS_BACKEND", "cloudflare")
    monkeypatch.setenv("QOZON_QUESTION_LIMITS_ENABLED", enabled)
    monkeypatch.setenv("QOZON_QUESTION_LIMIT_KEY", key)
    with pytest.raises(RuntimeError, match="question_limits_unavailable"):
        with TestClient(application(Model())):
            pass
