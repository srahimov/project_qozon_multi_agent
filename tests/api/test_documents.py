"""Public reader boundary tests; original PDFs and unapproved assets stay unavailable."""

import json
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from qozon_langchain.api import dependencies
from qozon_langchain.api.app import create_app
from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.documents import DocumentReader

DOC = 'd5000000-0000-0000-0000-000000000001'
CHUNK = 'a' * 64
ORIGINAL, ASSET, FINGERPRINT = 'b' * 64, 'c' * 64, 'd' * 64
DOCUMENT = {'id': DOC, 'title': 'Fictional reviewed guide', 'active_revision': '1' * 64}
METADATA = {'document_id': ORIGINAL, 'parent_asset_id': ASSET, 'source_sha256': FINGERPRINT,
            'url': 'https://untrusted.example/original.pdf',
            'private_sources': {'image': {'bucket': 'pdf_rag', 'object': 'original.pdf'}}}


@pytest.fixture
def make_client(monkeypatch, tmp_path):
    def build(handler=None, registry_change=None, **overrides):
        kwargs = dict(_env_file=None, supabase_url="https://synthetic.supabase.co",
            supabase_publishable_key="sb_publishable_synthetic", supabase_secret_key="synthetic_privileged_key",
            supabase_assets_bucket="approved-assets", rag_publication_manifest=tmp_path / "published.json")
        settings = Settings(**{**kwargs, **overrides})
        files=[{"role":role,"key":f"{ORIGINAL}/{ASSET}/{'e'*64}.{extension}","verified_public":True}
               for role,extension in [("image_url","png"),("url","md"),("structured_url","json")]]
        registry={"project_url":"https://synthetic.supabase.co","bucket":"approved-assets",
            "assets":{ASSET:{"document_id":ORIGINAL,"source_sha256":FINGERPRINT,"files":files}}}
        if registry_change:
            registry_change(registry)
        settings.rag_publication_manifest.write_text(json.dumps(registry))
        requests, readers = [], []
        monkeypatch.setattr(dependencies,"get_settings",lambda:settings)
        def respond(request):
            requests.append(request)
            if handler:
                result=handler(request)
                if result is not None:return result
            if request.url.path=="/rest/v1/qozon_documents":
                return httpx.Response(200,json=[DOCUMENT])
            if request.url.path=="/rest/v1/qozon_chunks":
                return httpx.Response(200,json=[{"revision":"1"*64,"metadata":METADATA}])
            pytest.fail("No Auth, Storage, original-PDF or untrusted-origin request is permitted")
        def reader(settings):
            result=DocumentReader(settings,transport=httpx.MockTransport(respond))
            readers.append(result)
            return result
        monkeypatch.setattr(dependencies,"DocumentReader",reader)
        return TestClient(create_app()), requests, readers, settings
    return build


@pytest.mark.parametrize("headers", [{}, {"Authorization":"Bearer invalid.visitor.token"}, {"Cookie":"token=untrusted"}])
def test_public_reads_need_no_account_and_never_forward_visitor_credentials(make_client,headers):
    client,requests,readers,_=make_client()
    with client:
        result=client.get("/documents?limit=5&offset=2",headers=headers)
    assert result.status_code==200 and result.json()==[DOCUMENT]
    assert result.headers["cache-control"]=="private, no-store"
    assert all(r.headers["apikey"]=="sb_publishable_synthetic" for r in requests)
    assert all("authorization" not in r.headers and "cookie" not in r.headers for r in requests)
    assert requests[0].url.params["public_read"]=="eq.true"
    assert requests[0].url.params["active_revision"]=="not.is.null"
    assert requests[0].url.params["limit"]=="5" and requests[0].url.params["offset"]=="2"
    assert all(r.client.is_closed for r in readers)


def test_public_metadata_projects_only_summary_fields(make_client):
    def handler(request):
        if request.url.path=="/rest/v1/qozon_documents":
            return httpx.Response(200,json=[{**DOCUMENT,"owner_id":"private","storage_object":"original.pdf"}])
    client,requests,_,_=make_client(handler)
    with client:
        result=client.get(f"/documents/{DOC}")
    assert result.status_code==200 and result.json()==DOCUMENT
    assert requests[0].url.params["select"]=="id,title,active_revision"
    assert "storage_object" not in result.text and "owner_id" not in result.text


@pytest.mark.parametrize("kind,suffix",[("image","png"),("structured","json"),("text","md")])
def test_citations_redirect_only_to_canonical_approved_public_asset(make_client,kind,suffix):
    client,requests,readers,_=make_client()
    with client:
        result=client.get(f"/documents/{DOC}/citations/{CHUNK}/{kind}?url=https://untrusted.example/private.pdf",follow_redirects=False)
    expected=f"https://synthetic.supabase.co/storage/v1/object/public/approved-assets/{ORIGINAL}/{ASSET}/{'e'*64}.{suffix}"
    assert result.status_code==307 and result.headers["location"]==expected
    assert "token" not in result.headers["location"] and "private.pdf" not in result.headers["location"]
    assert all(r.headers["apikey"]=="sb_publishable_synthetic" and "authorization" not in r.headers for r in requests)
    assert all(r.url.path.startswith("/rest/") for r in requests)
    assert all(r.client.is_closed for r in readers)


def test_reviewed_picture_with_only_primary_url_role_is_supported(make_client):
    def change(registry):
        record=registry["assets"][ASSET]
        record["files"]=[{"role":"url","key":f"{ORIGINAL}/{ASSET}/{'e'*64}.png","verified_public":True}]
    client,_,_,_=make_client(registry_change=change)
    with client:
        result=client.get(f"/documents/{DOC}/citations/{CHUNK}/image",follow_redirects=False)
    assert result.status_code==307 and result.headers["location"].endswith(".png")


@pytest.mark.parametrize("headers",[{}, {"Authorization":"Bearer synthetic.admin.signature"}])
def test_original_pdf_route_is_absent_even_when_a_token_is_supplied(make_client,headers):
    client,requests,_,_=make_client()
    with client:
        result=client.get(f"/documents/{DOC}/source",headers=headers)
    assert result.status_code==404 and not requests


@pytest.mark.parametrize("path",[f"/documents/{DOC}", f"/documents/{DOC}/citations/{CHUNK}/image"])
def test_private_deleted_unpublished_or_absent_document_is_not_exposed(make_client,path):
    def handler(request):
        if request.url.path=="/rest/v1/qozon_documents":return httpx.Response(200,json=[])
    client,requests,_,_=make_client(handler)
    with client:result=client.get(path,follow_redirects=False)
    assert result.status_code==404 and len(requests)==1 and "location" not in result.headers


@pytest.mark.parametrize("failure",["missing_chunk","staged_chunk","missing_metadata","changed_fingerprint","different_pdf","different_asset"])
def test_unapproved_or_changed_citation_never_redirects(make_client,failure):
    def handler(request):
        if request.url.path=="/rest/v1/qozon_chunks":
            meta=dict(METADATA);revision="1"*64
            if failure=="missing_chunk":return httpx.Response(200,json=[])
            if failure=="staged_chunk":revision="2"*64
            if failure=="missing_metadata":meta={"url":"https://untrusted.example/private.pdf"}
            if failure=="changed_fingerprint":meta["source_sha256"]="f"*64
            if failure=="different_pdf":meta["document_id"]="f"*64
            if failure=="different_asset":meta["parent_asset_id"]="f"*64
            return httpx.Response(200,json=[{"revision":revision,"metadata":meta}])
    client,_,_,_=make_client(handler)
    with client:result=client.get(f"/documents/{DOC}/citations/{CHUNK}/image",follow_redirects=False)
    assert result.status_code==404 and "location" not in result.headers


@pytest.mark.parametrize("change",["unverified","different_bucket","different_project","original_pdf_key","foreign_prefix"])
def test_public_registry_approval_and_destination_checks_still_apply(make_client,change):
    def edit(registry):
        if change=="unverified":registry["assets"][ASSET]["files"][0]["verified_public"]=False
        if change=="different_bucket":registry["bucket"]="private-assets"
        if change=="different_project":registry["project_url"]="https://foreign.supabase.co"
        if change=="original_pdf_key":registry["assets"][ASSET]["files"][0]["key"]=f"{ORIGINAL}/{ASSET}/{'e'*64}.pdf"
        if change=="foreign_prefix":registry["assets"][ASSET]["files"][0]["key"]=f"{'f'*64}/{ASSET}/{'e'*64}.png"
    client,_,_,_=make_client(registry_change=edit)
    with client:result=client.get(f"/documents/{DOC}/citations/{CHUNK}/image",follow_redirects=False)
    assert result.status_code==404 and "location" not in result.headers


@pytest.mark.parametrize("status",[302,401,403,500])
def test_upstream_errors_do_not_redirect_or_echo_provider_details(make_client,status):
    client,requests,readers,_=make_client(lambda r:httpx.Response(status,headers={"location":"https://untrusted.example"},json={"private":"synthetic-private-upstream"}))
    with client:result=client.get("/documents",follow_redirects=False)
    assert result.status_code==503 and "synthetic-private-upstream" not in result.text
    assert len(requests)==1 and all(r.client.is_closed for r in readers)


@pytest.mark.parametrize("configuration",[{"supabase_publishable_key":None},{"supabase_publishable_key":"sb_secret_rejected"},{"supabase_url":"https://foreign.example"}])
def test_reader_has_no_privileged_key_fallback(make_client,configuration):
    client,requests,_,_=make_client(**configuration)
    with client:result=client.get("/documents")
    assert result.status_code==503 and not requests


def test_metadata_reads_and_citations_work_without_storage_secret(make_client):
    client,requests,_,_=make_client(supabase_secret_key=None,supabase_storage_bucket=None)
    with client:
        assert client.get("/documents").status_code==200
        assert client.get(f"/documents/{DOC}/citations/{CHUNK}/image",follow_redirects=False).status_code==307
    assert all("authorization" not in r.headers for r in requests)


def test_upstream_timeout_has_safe_error_and_closes_client(make_client):
    def handler(request):raise httpx.ReadTimeout("synthetic-private-upstream")
    client,_,readers,_=make_client(handler)
    with client:result=client.get("/documents")
    assert result.status_code==504 and "synthetic-private-upstream" not in result.text
    assert all(r.client.is_closed for r in readers)


def test_invalid_upstream_summary_never_echoes_response_validation_input(make_client):
    client,_,_,_=make_client(lambda r:httpx.Response(200,json=[{**DOCUMENT,"title":{"secret":"synthetic-private-upstream"}}]))
    with client:result=client.get("/documents")
    assert result.status_code==502 and "synthetic-private-upstream" not in result.text


@pytest.mark.parametrize("path",["/documents?limit=101",f"/documents/{DOC}/citations/{CHUNK}/pdf",f"/documents/{DOC}/citations/invalid/image"])
def test_public_request_shape_is_bounded(make_client,path):
    client,requests,_,_=make_client()
    with client:result=client.get(path,follow_redirects=False)
    assert result.status_code==422 and not requests


def test_public_question_endpoint_remains_available_without_user_auth(monkeypatch):
    class FakeModel:
        async def generate_answer(self,question):return "A fictional answer."
    app=create_app()
    app.dependency_overrides[dependencies.get_answer_model]=lambda:FakeModel()
    app.dependency_overrides[dependencies.get_evidence_retriever]=lambda:None
    with TestClient(app) as client:result=client.post("/questions",json={"question":"What is an orchid?"})
    assert result.status_code==200 and result.json()["answer"]=="A fictional answer."
