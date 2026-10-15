"""Download an existing private Supabase PDF into a local ingestion directory.

This downloads a file; it does not upload, extract text, embed, or call an LLM.
Run only from trusted backend ingestion code, never with a user-supplied URL.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import tempfile
from urllib.parse import quote, urlsplit

import httpx

from qozon_multi_agent.core.config import Settings


class PDFDownloadError(Exception):
    """Fixed error code without credentials, response bodies, or document text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DownloadedPDF:
    """Local file plus a content hash for later ingestion version tracking."""

    path: Path
    sha256: str
    size_bytes: int


def download_pdf(
    object_path: str,
    *,
    settings: Settings,
    destination_dir: Path,
    max_bytes: int = 128 * 1024 * 1024,
    transport: httpx.BaseTransport | None = None,
) -> DownloadedPDF:
    """Stream a private PDF to disk and release it only after basic validation.

    The object path is relative to the configured bucket. Files are created
    with private permissions. Failed downloads are removed. Redirects are
    disabled so the backend key stays with the configured Supabase origin.
    The header check identifies PDFs; Docling must still validate their content.
    """
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise PDFDownloadError("storage_not_configured")
    bucket = settings.supabase_storage_bucket
    if not bucket:
        raise PDFDownloadError("storage_not_configured")
    base_url = settings.supabase_url.rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not re.fullmatch(r"[a-z0-9]+\.supabase\.co", parsed.netloc)
        or parsed.path or parsed.query or parsed.fragment
    ):
        raise PDFDownloadError("invalid_storage_url")
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]+", bucket)
        or not isinstance(object_path, str)
        or not object_path.lower().endswith(".pdf")
        or any(part in {"", ".", ".."} for part in object_path.split("/"))
        or "\\" in object_path
        or any(ord(char) < 32 for char in object_path)
    ):
        raise PDFDownloadError("invalid_object_path")
    if type(max_bytes) is not int or max_bytes <= 0:
        raise PDFDownloadError("invalid_size_limit")

    url = f"{base_url}/storage/v1/object/authenticated/{bucket}/{quote(object_path, safe='/')}"
    local_path: Path | None = None
    completed = False
    try:
        destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with httpx.Client(
            timeout=httpx.Timeout(60.0, connect=15.0),
            follow_redirects=False,
            transport=transport,
        ) as client:
            with client.stream(
                "GET", url,
                headers={"apikey": settings.supabase_secret_key.get_secret_value()},
            ) as response:
                if response.status_code != 200:
                    raise PDFDownloadError("storage_download_failed")
                length = response.headers.get("content-length")
                if length is not None and int(length) > max_bytes:
                    raise PDFDownloadError("pdf_too_large")
                digest = sha256()
                total = 0
                header = b""
                with tempfile.NamedTemporaryFile(
                    dir=destination_dir, prefix="source-", suffix=".pdf", delete=False
                ) as local:
                    local_path = Path(local.name)
                    for chunk in response.iter_bytes(chunk_size=64 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise PDFDownloadError("pdf_too_large")
                        header = (header + chunk)[:5]
                        local.write(chunk)
                        digest.update(chunk)
                if header != b"%PDF-":
                    raise PDFDownloadError("invalid_pdf_header")
        completed = True
        return DownloadedPDF(path=local_path, sha256=digest.hexdigest(), size_bytes=total)
    except PDFDownloadError:
        raise
    except (httpx.HTTPError, OSError, ValueError):
        raise PDFDownloadError("storage_download_failed") from None
    finally:
        if local_path is not None and not completed:
            local_path.unlink(missing_ok=True)
