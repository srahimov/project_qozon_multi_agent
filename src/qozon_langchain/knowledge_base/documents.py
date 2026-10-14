"""Public document summaries and citation links from the approved asset registry.

The publishable key uses the anonymous database role. No user token or privileged
Storage credential is used; original PDF downloads have no API route.
"""

import re
from uuid import UUID

import httpx

from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.pdf.publication import published_links


class DocumentAccessError(Exception):
    """Fixed errors without upstream response bodies or credentials."""

    def __init__(self, code: str):
        self.code = code
        self.status, self.message = {
            "document_access_not_configured": (503, "Document access is not configured."),
            "source_not_found": (404, "The requested document or source is not available."),
            "source_unavailable": (503, "The source service is unavailable. Please try again."),
            "document_access_timeout": (504, "Document access timed out. Please try again."),
        }[code]
        super().__init__(self.message)


def public_configuration(settings):
    url = settings.supabase_url or ""
    key = settings.supabase_publishable_key
    if (not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co/?", url)
            or key is None or not re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", key.get_secret_value())):
        raise DocumentAccessError("document_access_not_configured")
    return url.rstrip("/"), key.get_secret_value()


class DocumentReader:
    def __init__(self, settings: Settings, *, transport=None):
        url, key = public_configuration(settings)
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=url.rstrip("/"), timeout=httpx.Timeout(10, connect=5),
            headers={"apikey": key},
            follow_redirects=False, trust_env=False, transport=transport,
        )

    async def _rows(self, table: str, params: dict):
        return await self.rows("GET", "/rest/v1/" + table, params=params)

    async def rows(self, method: str, path: str, **kwargs):
        """Bound the body while streaming; discard upstream error details."""
        try:
            async with self.client.stream(method, path, **kwargs) as response:
                if response.status_code != 200:
                    raise DocumentAccessError("source_unavailable")
                body = bytearray()
                async for piece in response.aiter_bytes():
                    body.extend(piece)
                    if len(body) > 1024 * 1024:
                        raise DocumentAccessError("source_unavailable")
            import json
            rows = json.loads(body)
            if not isinstance(rows, list):
                raise DocumentAccessError("source_unavailable")
            return rows
        except httpx.TimeoutException:
            raise DocumentAccessError("document_access_timeout") from None
        except (httpx.HTTPError, ValueError):
            raise DocumentAccessError("source_unavailable") from None

    async def list_documents(self, limit: int, offset: int):
        return await self._rows("qozon_documents", {
            "select": "id,title,active_revision", "public_read": "eq.true",
            "active_revision": "not.is.null", "order": "id.asc", "limit": limit, "offset": offset,
        })

    async def document(self, document_id: UUID):
        rows = await self._rows("qozon_documents", {
            "select": "id,title,active_revision", "id": f"eq.{document_id}",
            "public_read": "eq.true", "active_revision": "not.is.null", "limit": 1,
        })
        if not rows:
            raise DocumentAccessError("source_not_found")
        if not isinstance(rows[0], dict) or rows[0].get("id") != str(document_id):
            raise DocumentAccessError("source_unavailable")
        return rows[0]

    async def citation_url(self, document_id: UUID, chunk_id: str, kind: str):
        document = await self.document(document_id)
        rows = await self._rows("qozon_chunks", {
            "select": "revision,metadata", "document_id": f"eq.{document_id}",
            "chunk_id": f"eq.{chunk_id}", "limit": 1,
        })
        try:
            row = rows[0]
            if row["revision"] != document["active_revision"]:
                raise ValueError()
            meta = row["metadata"]
            links = published_links(self.settings, meta["document_id"],
                                    meta["parent_asset_id"], meta["source_sha256"])
            url = links.get({"image": "image_url", "structured": "structured_url", "text": "url"}[kind])
            if kind == "image" and url is None:
                url = links.get("url")  # Reviewed pictures may use the primary URL role.
            suffix = {"image": ".png", "structured": ".json", "text": ".md"}[kind]
            if not isinstance(url, str) or not url.endswith(suffix):
                raise ValueError()
        except (IndexError, KeyError, TypeError, ValueError):
            raise DocumentAccessError("source_not_found") from None
        # Registry URLs are canonical public PNG/MD/JSON assets, never original PDFs.
        return url
