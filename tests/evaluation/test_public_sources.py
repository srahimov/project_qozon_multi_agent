import asyncio
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from qozon_langchain.core.config import Settings
from qozon_langchain.evaluation.langsmith_rag import PublicSourceEvaluator
from qozon_langchain.knowledge_base.pdf.publication import public_url
from qozon_langchain.knowledge_base.pdf.retrieval import Evidence


def fixture(tmp_path):
    payload = b"synthetic-public-source-image"
    sha = hashlib.sha256(payload).hexdigest()
    doc_id, asset_id, source_hash = "a" * 64, "b" * 64, "c" * 64
    key = f"{doc_id}/{asset_id}/{sha}.png"
    settings = Settings(_env_file=None, supabase_url="https://synthetic.supabase.co",
                        supabase_assets_bucket="public-assets", rag_publication_manifest=tmp_path / "published.json")
    settings.rag_publication_manifest.write_text(json.dumps({
        "bucket": settings.supabase_assets_bucket, "project_url": settings.supabase_url,
        "assets": {asset_id: {"document_id": doc_id, "source_sha256": source_hash,
            "files": [{"role": "url", "key": key, "sha256": sha, "size_bytes": len(payload), "verified_public": True}]}}}))
    target = SimpleNamespace(local_evidence={"Fictional question": [Evidence(
        "chunk", doc_id, "fictional.pdf", (2,), "image_description", asset_id,
        "Fictional source description.", source_sha256=source_hash)]})
    run = SimpleNamespace(outputs={"status": "success", "sources": [{"chunk_id": "chunk",
        "asset_id": asset_id, "url": public_url(settings, key), "image_url": None, "structured_url": None}]})
    example = SimpleNamespace(inputs={"question": "Fictional question"}, outputs={"expected_content_type": "image_description"})
    return settings, target, run, example, payload


def scores(evaluator, run, example):
    return {s["key"]: s["score"] for s in asyncio.run(evaluator(run, example))["results"]}


def test_public_source_evaluation_downloads_anonymously_and_checks_bytes(tmp_path):
    settings, target, run, example, payload = fixture(tmp_path)
    requests = []
    def reply(request):
        requests.append(request)
        assert "apikey" not in request.headers and "authorization" not in request.headers
        return httpx.Response(200, content=payload)
    result = scores(PublicSourceEvaluator(settings, target, transport=httpx.MockTransport(reply)), run, example)
    assert result == {"source_url_integrity": 1, "public_source_access": 1}
    assert len(requests) == 1


def test_invented_url_is_rejected_before_any_download(tmp_path):
    settings, target, run, example, _ = fixture(tmp_path)
    run.outputs["sources"][0]["url"] = "https://untrusted.example/source.png"
    transport = httpx.MockTransport(lambda request: pytest.fail("Never fetch a noncanonical URL"))
    assert scores(PublicSourceEvaluator(settings, target, transport=transport), run, example) == {
        "source_url_integrity": 0, "public_source_access": 0}


@pytest.mark.parametrize("response", [httpx.Response(404), httpx.Response(200, content=b"altered")])
def test_public_download_errors_do_not_look_like_success(tmp_path, response):
    settings, target, run, example, _ = fixture(tmp_path)
    evaluator = PublicSourceEvaluator(settings, target, transport=httpx.MockTransport(lambda request: response))
    assert scores(evaluator, run, example) == {"source_url_integrity": 1, "public_source_access": 0}


def test_plain_text_citation_has_no_public_asset_requirement(tmp_path):
    settings, target, run, _, _ = fixture(tmp_path)
    run.outputs["sources"] = [{"asset_id": None}]
    evaluator = PublicSourceEvaluator(settings, target)
    assert asyncio.run(evaluator(run, SimpleNamespace(outputs={"expected_content_type": "text"}))) == {"results": []}


def test_changed_recorded_fingerprint_is_rejected_without_a_local_record_map(tmp_path):
    from dataclasses import replace
    settings,target,run,example,_=fixture(tmp_path)
    evidence=target.local_evidence[example.inputs["question"]][0]
    target.local_evidence[example.inputs["question"]]=[replace(evidence,source_sha256="d"*64)]
    transport=httpx.MockTransport(lambda request: pytest.fail("Changed fingerprints must never fetch an asset"))
    assert scores(PublicSourceEvaluator(settings,target,transport=transport),run,example)=={
        "source_url_integrity":0,"public_source_access":0}
