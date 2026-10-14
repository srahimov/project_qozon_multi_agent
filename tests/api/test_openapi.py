"""The exported client contract must describe the actual safe HTTP boundaries."""

from fastapi.testclient import TestClient

from qozon_langchain.api.app import create_app
from qozon_langchain.api.schemas import APIErrorResponse


def test_openapi_describes_safe_errors_and_retry_header():
    app = create_app()
    spec = app.openapi()
    responses = spec["paths"]["/questions"]["post"]["responses"]
    for status in (400, 409, 422, 429, 500, 502, 503, 504):
        assert responses[str(status)]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/APIErrorResponse"}
    assert "Retry-After" in responses["429"]["headers"]
    with TestClient(app) as client:
        response = client.post("/questions", json={"question": "a" * 201})
    assert response.status_code == 422
    assert APIErrorResponse.model_validate(response.json()).detail.code == "invalid_request"


def test_citation_contract_is_a_redirect_and_no_original_pdf_route_exists():
    spec = create_app().openapi()
    route = spec["paths"]["/documents/{document_id}/citations/{chunk_id}/{kind}"]["get"]
    assert "307" in route["responses"] and "200" not in route["responses"]
    assert "content" not in route["responses"]["307"]
    assert "Location" in route["responses"]["307"]["headers"]
    assert not any(path.endswith("/source") for path in spec["paths"])
