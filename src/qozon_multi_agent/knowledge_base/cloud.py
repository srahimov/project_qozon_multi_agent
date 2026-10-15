"""LangChain retriever over anonymous, RLS-filtered Supabase RPCs."""

import asyncio
import hashlib
import math
from typing import Annotated, Any, Literal
from uuid import UUID

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from langsmith import tracing_context
from pydantic import BaseModel, ConfigDict, Field

from qozon_multi_agent.core.config import Settings
from qozon_multi_agent.knowledge_base.documents import DocumentReader
from qozon_multi_agent.knowledge_base.pdf.chunking import checked_document_text
from qozon_multi_agent.knowledge_base.pdf.publication import published_links
from qozon_multi_agent.knowledge_base.pdf.retrieval import Evidence, RetrievalError, fuse_hits, lexical_tokens

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class PublicMetadata(BaseModel):
    """The entire public import contract; paths, locators and URLs are excluded."""
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    document_id: Hash
    source: Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[^/\\\x00-\x1f]+$")]
    page_numbers: Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=641)]
    content_type: Literal["text", "image_description", "table_summary"]
    parent_asset_id: Annotated[str, Field(pattern=r"^(?:[a-f0-9]{64})?$")]
    source_sha256: Annotated[str, Field(pattern=r"^(?:[a-f0-9]{64})?$")]
    factually_verified: bool
    evidence_sha256: Hash


def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def checked_hit(row):
    meta = dict(row["metadata"])
    cloud_id, revision, chunk_id = str(UUID(meta.pop("cloud_document_id"))), meta.pop("revision"), meta.pop("chunk_id")
    public = PublicMetadata.model_validate(meta)
    if not all(len(x) == 64 and all(c in "0123456789abcdef" for c in x) for x in (revision, chunk_id)):
        raise RetrievalError("retrieval_record_invalid")
    text = row["content"]
    if (not isinstance(text, str) or not 0 < len(text) <= 16000
            or text_hash(text) != public.evidence_sha256 or checked_document_text(text)[0] != text):
        raise RetrievalError("retrieval_record_changed")
    return Document(page_content=text, metadata=dict(public.model_dump(), cloud_document_id=cloud_id,
                                                     revision=revision, chunk_id=chunk_id))


def balanced_hits(query, vectors, keywords, *, max_distance, context_characters):
    """Select four per independent lane, then deduplicate within the context cap."""
    vector_lane = [hit for hit, distance in sorted(vectors, key=lambda item: item[1])
                   if 0 <= distance <= max_distance]
    words = set(lexical_tokens(query))
    keyword_lane = [hit for hit in keywords if words.intersection(lexical_tokens(hit.page_content))]
    lanes = {}
    for name, candidates in (("vector", vector_lane), ("keyword", keyword_lane)):
        unique = {}
        for hit in candidates:
            unique.setdefault(hit.metadata["chunk_id"], hit)
        lanes[name] = list(unique.values())[:4]
    provenance = {}
    for name, hits in lanes.items():
        for hit in hits:
            provenance.setdefault(hit.metadata["chunk_id"], []).append(name)
    selected, seen, remaining = [], set(), context_characters
    # Alternate lanes so one lane cannot consume the entire budget first.
    for index in range(4):
        for name in ("vector", "keyword"):
            if index >= len(lanes[name]):
                continue
            hit = lanes[name][index]
            key = hit.metadata["chunk_id"]
            if key in seen or len(hit.page_content) > remaining:
                continue
            seen.add(key)
            remaining -= len(hit.page_content)
            selected.append(hit.model_copy(update={"metadata": {
                **hit.metadata, "retrieval_lanes": tuple(provenance[key]),
            }}))
    return selected


class CloudPDFRetriever(BaseRetriever):
    settings: Settings = Field(exclude=True, repr=False)
    embeddings: Embeddings = Field(exclude=True, repr=False)
    transport: Any = Field(default=None, exclude=True, repr=False)
    balanced: bool = False

    def _get_relevant_documents(self, query, *, run_manager):
        return asyncio.run(self._aget_relevant_documents(query, run_manager=run_manager))

    async def _aget_relevant_documents(self, query, *, run_manager):
        try:
            reader = DocumentReader(self.settings, transport=self.transport)
            async with reader.client:
                with tracing_context(enabled=False):
                    vector = await self.embeddings.aembed_query(query)
                if (len(vector) != 1536 or self.settings.embedding_dimensions != 1536
                        or self.settings.embedding_model_name != "text-embedding-3-small"
                        or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector)
                        or not any(vector)):
                    raise RetrievalError("retrieval_vector_invalid")
                words = list(dict.fromkeys(lexical_tokens(query)))
                # Both lanes belong to this request; join cancellation before closing the client.
                async with asyncio.TaskGroup() as group:
                    vector_task = group.create_task(reader.rows("POST", "/rest/v1/rpc/qozon_match_chunks", json={
                        "query_embedding": vector, "match_count": 12, "filter": {}}),
                    )
                    keyword_task = group.create_task(reader.rows("POST", "/rest/v1/rpc/qozon_keyword_chunks", json={
                        "query_text": " or ".join(words), "match_count": 12, "filter": {}}),
                    )
                vector_rows, keyword_rows = vector_task.result(), keyword_task.result()
                if len(vector_rows) > 12 or len(keyword_rows) > 12:
                    raise RetrievalError("retrieval_result_limit")
                vectors = []
                for row in vector_rows:
                    score = row["similarity"]
                    if not isinstance(score, (int, float)) or not math.isfinite(score) or not -1 <= score <= 1.00001:
                        raise RetrievalError("retrieval_score_invalid")
                    vectors.append((checked_hit(row), max(0, 1 - score)))
                lexical = [checked_hit(row) for row in keyword_rows]
                # Separate calls can straddle activation. Never mix revisions or contents.
                identities, documents = {}, {}
                for hit in [x[0] for x in vectors] + lexical:
                    m = hit.metadata
                    key = m["chunk_id"]
                    if key in identities and identities[key] != hit:
                        raise RetrievalError("retrieval_record_changed")
                    identities[key] = hit
                    old = documents.setdefault(m["cloud_document_id"], m["revision"])
                    if old != m["revision"]:
                        raise RetrievalError("retrieval_revision_changed")
                if self.balanced:
                    return balanced_hits(query, vectors, lexical, max_distance=self.settings.rag_max_distance,
                                         context_characters=self.settings.rag_context_characters)
                hits = fuse_hits(query, vectors, lexical, max_distance=self.settings.rag_max_distance)
                selected, parents, remaining = [], set(), self.settings.rag_context_characters
                for hit in hits:
                    parent = hit.metadata["parent_asset_id"]
                    if parent and parent in parents or len(hit.page_content) > remaining:
                        continue
                    selected.append(hit)
                    remaining -= len(hit.page_content)
                    if parent:
                        parents.add(parent)
                    if len(selected) == self.settings.rag_top_k:
                        break
                return selected
        except RetrievalError:
            raise
        except Exception:
            raise RetrievalError("retrieval_unavailable") from None

    async def retrieve(self, question):
        try:
            with tracing_context(enabled=False):
                hits = await self.ainvoke(question, config={"callbacks": []})
            evidence, image_selected = [], False
            reader = DocumentReader(self.settings, transport=self.transport)
            async with reader.client:
                for hit in hits:
                    meta = hit.metadata
                    links = published_links(self.settings, meta["document_id"], meta["parent_asset_id"], meta["source_sha256"])
                    if meta["parent_asset_id"] and not links:
                        raise RetrievalError("retrieval_asset_not_approved")
                    image = None
                    if meta["content_type"] == "image_description" and not image_selected:
                        url = links.get("image_url") or links.get("url")
                        if not url or not url.endswith(".png"):
                            raise RetrievalError("retrieval_image_invalid")
                        async with reader.client.stream("GET", url) as response:
                            if response.status_code != 200:
                                raise RetrievalError("retrieval_image_unavailable")
                            body = bytearray()
                            async for piece in response.aiter_bytes():
                                body.extend(piece)
                                if len(body) > 10 * 1024 * 1024:
                                    raise RetrievalError("retrieval_image_invalid")
                        image = bytes(body)
                        if (not image.startswith(b"\x89PNG\r\n\x1a\n")
                                or hashlib.sha256(image).hexdigest() != url.rsplit('/', 1)[1][:-4]):
                            raise RetrievalError("retrieval_image_changed")
                        image_selected = True
                    evidence.append(Evidence(meta["chunk_id"], meta["document_id"], meta["source"],
                        tuple(meta["page_numbers"]), meta["content_type"], meta["parent_asset_id"],
                        hit.page_content, meta["factually_verified"], image, **links,
                        cloud_document_id=meta["cloud_document_id"], revision=meta["revision"],
                        source_sha256=meta["source_sha256"],
                        retrieval_lanes=tuple(meta.get("retrieval_lanes", ()))))
            await self.validate_evidence(evidence)
            return evidence
        except RetrievalError:
            raise
        except Exception:
            raise RetrievalError("retrieval_unavailable") from None

    async def retrieve_balanced(self, question):
        """Use four-per-lane retrieval without changing the existing API default."""
        return await self.model_copy(update={"balanced": True}).retrieve(question)

    async def validate_evidence(self, evidence):
        """Re-read anonymous rows before releasing a buffered answer."""
        if not evidence:
            return
        reader = DocumentReader(self.settings, transport=self.transport)
        async with reader.client:
            for doc_id in {x.cloud_document_id for x in evidence}:
                selected = [x for x in evidence if x.cloud_document_id == doc_id]
                doc = await reader.document(UUID(doc_id))
                rows = await reader._rows("qozon_chunks", {
                    "select": "chunk_id,revision,content,evidence_content,metadata",
                    "document_id": f"eq.{doc_id}", "revision": f"eq.{doc['active_revision']}",
                    "chunk_id": "in.(" + ",".join(x.chunk_id for x in selected) + ")", "limit": 12,
                })
                current = {r["chunk_id"]: r for r in rows}
                for item in selected:
                    row = current.get(item.chunk_id)
                    if (item.revision != doc["active_revision"] or row is None
                            or row["revision"] != item.revision
                            or (row["evidence_content"] or row["content"]) != item.text):
                        raise RetrievalError("retrieval_access_changed")
                    meta = PublicMetadata.model_validate(row["metadata"])
                    if (meta.document_id != item.document_id or meta.page_numbers != list(item.page_numbers)
                            or meta.source != item.source or meta.content_type != item.content_type
                            or meta.parent_asset_id != item.parent_asset_id or meta.factually_verified != item.factually_verified
                            or meta.source_sha256 != item.source_sha256
                            or meta.evidence_sha256 != text_hash(item.text)):
                        raise RetrievalError("retrieval_record_changed")
                    links = published_links(self.settings, meta.document_id, meta.parent_asset_id, meta.source_sha256)
                    if links != {k: v for k, v in {"url": item.url, "image_url": item.image_url,
                                                 "structured_url": item.structured_url}.items() if v is not None}:
                        raise RetrievalError("retrieval_asset_changed")
