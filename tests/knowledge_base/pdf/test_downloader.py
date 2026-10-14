"""Exercise downloads without contacting Supabase or reading local keys."""

from hashlib import sha256

import httpx
import pytest

from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.pdf.downloader import PDFDownloadError, download_pdf


def storage_settings(**overrides):
    values = dict(
        SUPABASE_URL="https://exampleproject.supabase.co",
        SUPABASE_SECRET_KEY="synthetic-test-key",
        SUPABASE_STORAGE_BUCKET="pdf_rag",
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_download_returns_private_file_and_content_hash(tmp_path):
    content = b"%PDF-1.7\nsynthetic test document"

    def handler(request):
        assert request.headers["apikey"] == "synthetic-test-key"
        assert request.url.path.endswith("/pdf_rag/folder/Book.pdf")
        return httpx.Response(200, content=content)

    result = download_pdf(
        "folder/Book.pdf", settings=storage_settings(), destination_dir=tmp_path,
        transport=httpx.MockTransport(handler),
    )
    assert result.path.read_bytes() == content
    assert result.size_bytes == len(content)
    assert result.sha256 == sha256(content).hexdigest()
    assert result.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("status", [302, 401, 403, 404, 500])
def test_http_failure_never_returns_response_body_or_follows_redirect(tmp_path, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://other.example"},
                              text="sensitive upstream details")

    with pytest.raises(PDFDownloadError) as error:
        download_pdf("Book.pdf", settings=storage_settings(), destination_dir=tmp_path,
                 transport=httpx.MockTransport(handler))
    assert str(error.value) == "storage_download_failed"
    assert len(calls) == 1
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("content,limit,code", [
    (b"not a PDF", 100, "invalid_pdf_header"),
    (b"%PDF-too large", 6, "pdf_too_large"),
    (b"", 100, "invalid_pdf_header"),
])
def test_invalid_download_is_removed(tmp_path, content, limit, code):
    # No length header: exercise the streaming size bound too.
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=httpx.ByteStream(content))
    )
    with pytest.raises(PDFDownloadError) as error:
        download_pdf("Book.pdf", settings=storage_settings(), destination_dir=tmp_path,
                 max_bytes=limit, transport=transport)
    assert error.value.code == code
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("url", ["http://exampleproject.supabase.co", "https://other.example",
                                  "https://exampleproject.supabase.co/extra"])
def test_untrusted_origins_are_rejected_before_network(tmp_path, url):
    with pytest.raises(PDFDownloadError, match="invalid_storage_url"):
        download_pdf("Book.pdf", settings=storage_settings(SUPABASE_URL=url),
                 destination_dir=tmp_path)


@pytest.mark.parametrize("path", ["../Book.pdf", "/Book.pdf", "folder//Book.pdf", "Book.txt"])
def test_invalid_paths_are_rejected_before_network(tmp_path, path):
    with pytest.raises(PDFDownloadError, match="invalid_object_path"):
        download_pdf(path, settings=storage_settings(), destination_dir=tmp_path)


def test_secret_is_hidden_and_missing_config_does_not_contact_storage(tmp_path):
    settings = storage_settings()
    assert "synthetic-test-key" not in repr(settings)
    assert settings.supabase_secret_key.get_secret_value() == "synthetic-test-key"
    with pytest.raises(PDFDownloadError, match="storage_not_configured"):
        download_pdf("Book.pdf", settings=storage_settings(SUPABASE_SECRET_KEY=""),
                 destination_dir=tmp_path)
