import json

import httpx
import pytest

from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.pdf.chunking import digest
from qozon_langchain.knowledge_base.pdf.processing import processing_fingerprint
from qozon_langchain.knowledge_base.pdf.publication import PublicationError, publish_assets, published_links


def source(tmp_path):
    crop = tmp_path / "picture.png"
    crop.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic-test-pixels")
    manifest = tmp_path / "manifest.json"
    document_id = "a" * 64
    manifest.write_text(json.dumps({"document_sha256": document_id, "assets": [
        {"kind": "picture", "element_ref": "#/pictures/0", "page_numbers": [2],
         "caption": "Synthetic reviewed caption.", "images": [{"image": crop.name}]}]}))
    selection = {"manifest": str(manifest), "element_ref": "#/pictures/0",
                 "source_sha256": processing_fingerprint(manifest, "#/pictures/0")}
    settings = Settings(_env_file=None, supabase_url="https://synthetic.supabase.co",
                        supabase_secret_key="synthetic-local-key", supabase_assets_bucket="public-assets",
                        rag_publication_manifest=tmp_path / "published.json")
    return settings, selection, document_id


def test_publication_verifies_anonymous_bytes_and_is_repeatable(tmp_path):
    settings, selection, document_id = source(tmp_path)
    objects, uploads = {}, []
    def auth(request):
        assert request.headers["apikey"] == "synthetic-local-key"
        if request.method == "GET":
            return httpx.Response(200, json={"public": True})
        uploads.append(request.url.path)
        objects[request.url.path.replace("/object/", "/object/public/", 1)] = request.content
        return httpx.Response(200)
    def anonymous(request):
        assert "apikey" not in request.headers and "authorization" not in request.headers
        return httpx.Response(200, content=objects[request.url.path]) if request.url.path in objects else httpx.Response(404)
    with httpx.Client(transport=httpx.MockTransport(auth)) as a, httpx.Client(transport=httpx.MockTransport(anonymous)) as b:
        publish_assets(settings, [selection], authenticated=a, anonymous=b)
        publish_assets(settings, [selection], authenticated=a, anonymous=b)
    assert len(uploads) == 1
    asset_id = digest([document_id, str(tmp_path / "manifest.json"), selection["element_ref"]])
    links = published_links(settings, document_id, asset_id, selection["source_sha256"])
    assert links["url"].startswith("https://synthetic.supabase.co/storage/v1/object/public/public-assets/")
    assert published_links(settings, document_id, asset_id, "changed-source") == {}
    registry = json.loads(settings.rag_publication_manifest.read_text())
    registry["assets"][asset_id]["files"][0]["key"] = "../another-file.png"
    settings.rag_publication_manifest.write_text(json.dumps(registry))
    assert published_links(settings, document_id, asset_id, selection["source_sha256"]) == {}


def test_private_bucket_or_changed_source_cannot_publish(tmp_path):
    settings, selection, _ = source(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"public": False}))) as client:
        with pytest.raises(PublicationError, match="public_bucket_not_verified"):
            publish_assets(settings, [selection], authenticated=client)
    selection["source_sha256"] = "unapproved"
    with pytest.raises(PublicationError, match="publication_source_review_required"):
        publish_assets(settings, [selection])


def test_public_download_must_match_uploaded_bytes(tmp_path):
    settings, selection, _ = source(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"public": True}))) as a:
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"wrong bytes"))) as b:
            with pytest.raises(PublicationError, match="public_asset_verification_failed"):
                publish_assets(settings, [selection], authenticated=a, anonymous=b)
    assert not settings.rag_publication_manifest.exists()


def test_timeout_is_bounded_and_reports_safe_code(tmp_path, monkeypatch):
    import qozon_langchain.knowledge_base.pdf.publication as module
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    settings, selection, _ = source(tmp_path)
    events = []
    def timeout(request):
        raise httpx.ReadTimeout("synthetic-private-response-detail", request=request)
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(PublicationError, match="storage_timeout") as error:
            publish_assets(settings, [selection], authenticated=client, progress=events.append)
    assert "synthetic-private-response-detail" not in str(error.value)
    assert len(events) == 2 and all(e["status"] == "request_retry" for e in events)


def test_lost_upload_response_retries_same_key_without_overwriting(tmp_path, monkeypatch):
    import qozon_langchain.knowledge_base.pdf.publication as module
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    settings, selection, _ = source(tmp_path)
    objects, uploads, events = {}, [], []
    def auth(request):
        if request.method == "GET": return httpx.Response(200, json={"public": True})
        assert request.headers["x-upsert"] == "false"
        uploads.append(request.url.path)
        path = request.url.path.replace("/object/", "/object/public/", 1)
        if path in objects: return httpx.Response(409)
        objects[path] = request.content
        raise httpx.RemoteProtocolError("synthetic-lost-response", request=request)
    def public(request):
        assert "apikey" not in request.headers
        return httpx.Response(200, content=objects[request.url.path]) if request.url.path in objects else httpx.Response(404)
    with httpx.Client(transport=httpx.MockTransport(auth)) as a, httpx.Client(transport=httpx.MockTransport(public)) as b:
        publish_assets(settings, [selection], authenticated=a, anonymous=b, progress=events.append)
    assert len(uploads) == 2 and len(set(uploads)) == 1 and len(objects) == 1
    assert events[-1]["status"] == "asset_verified"
