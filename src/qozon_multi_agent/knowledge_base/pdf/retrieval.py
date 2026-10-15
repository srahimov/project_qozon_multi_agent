"""Retrieve Chroma text with canonical local source resolution and no HTTP paths.

Published assets gain verified public URLs from the local publication registry.
Unpublished sources retain IDs and pages without invented URLs or local paths.
"""

from dataclasses import dataclass, field
import hashlib
import json
import re
from pathlib import Path
from typing import Protocol
from langsmith import tracing_context
from langchain_core.documents import Document

from qozon_multi_agent.core.config import Settings
from qozon_multi_agent.knowledge_base.pdf.chunking import checked_document_text, local_file
from qozon_multi_agent.knowledge_base.pdf.indexing import build_embeddings, index_read_lock, load_corpus, open_store
from qozon_multi_agent.knowledge_base.pdf.processing import processing_fingerprint
from qozon_multi_agent.knowledge_base.pdf.publication import published_links


class RetrievalError(Exception):
    pass


@dataclass(frozen=True)
class Evidence:
    chunk_id: str
    document_id: str
    source: str
    page_numbers: tuple[int, ...]
    content_type: str
    parent_asset_id: str
    text: str = field(repr=False)
    factually_verified: bool = False
    image: bytes | None = field(default=None, repr=False)
    url: str | None = None
    image_url: str | None = None
    structured_url: str | None = None
    cloud_document_id: str | None = None
    revision: str | None = None
    source_sha256: str = ""
    retrieval_lanes: tuple[str, ...] = ()


class EvidenceRetriever(Protocol):
    async def retrieve(self, question: str) -> list[Evidence]: ...


def lexical_tokens(text):
    stop = {"a", "an", "the", "what", "is", "are", "does", "do", "in", "of", "to", "and", "or", "with", "how", "this", "that", "it"}
    aliases = {"aim": "purpose", "aims": "purpose", "purposes": "purpose"}
    return [aliases.get(word, word) for word in re.findall(r"[\w]+", text.casefold()) if word not in stop]


def resolve_record(settings, record, source_hashes, *, budget, image_selected=True):
    """Resolve the same reviewed parent context for local reads and cloud import."""
    meta = record["metadata"]
    parent = meta["parent_asset_id"]
    text, image = record["page_content"], None
    if parent:
        mp = Path(meta["manifest"])
        if processing_fingerprint(mp, meta["element_refs"][0]) != meta["source_sha256"]:
            raise RetrievalError("retrieval_source_changed")
        summary_bytes = Path(meta["summary_file"]).read_bytes()
        expected_hash = source_hashes.get(meta["summary_file"])
        if expected_hash and hashlib.sha256(summary_bytes).hexdigest() != expected_hash:
            raise RetrievalError("retrieval_summary_changed")
        saved = json.loads(summary_bytes)
        if saved["processing_identity"]["source_sha256"] != meta["source_sha256"]:
            raise RetrievalError("retrieval_summary_changed")
        # Resolve the full checked summary even if retrieval matched a split piece.
        text = saved["description"]
        manifest = json.loads(mp.read_text())
        asset = next(a for a in manifest["assets"] if a["element_ref"] == meta["element_refs"][0])
        if meta["content_type"] == "table_summary":
            full = local_file(mp.parent, asset["markdown"]).read_text()
            # Remove padding, retaining every row, column separator and cell value.
            full = re.sub(r"-{3,}", "---", re.sub(r"[ \t]+", " ", full))
            checked, _, _ = checked_document_text(full)
            # Include complete tables only when they fit; never cut a table silently.
            if checked is not None and len(text) + len(checked) + 30 <= budget:
                text += "\n\nComplete source table:\n" + checked
        else:
            if asset.get("caption"):
                text += "\n\nPrinted source caption:\n" + asset["caption"]
            if not image_selected:
                path = local_file(mp.parent, asset["images"][0]["image"])
                if not 0 < path.stat().st_size <= 10 * 1024 * 1024:
                    raise RetrievalError("retrieval_image_invalid")
                image = path.read_bytes()
                if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise RetrievalError("retrieval_image_invalid")
    return text, image


def fuse_hits(question, results, lexical_hits, *, max_distance):
    # Weighted reciprocal-rank fusion combines library rankings by stable ID.
    # Keep only lexical hits that actually share a non-stopword query term.
    ranks, hits = {}, {}
    for rank, (hit, distance) in enumerate(results, 1):
        if not 0 <= distance <= max_distance:
            continue
        key = hit.metadata.get("chunk_id")
        ranks[key] = ranks.get(key, 0) + 0.3 / (60 + rank)
        hits[key] = hit
    query_words = set(lexical_tokens(question))
    for rank, hit in enumerate(lexical_hits, 1):
        if not query_words.intersection(lexical_tokens(hit.page_content)):
            continue
        key = hit.metadata["chunk_id"]
        ranks[key] = ranks.get(key, 0) + 0.7 / (60 + rank)
        hits.setdefault(key, hit)
    # Explicit three-word source phrases (e.g. "table of contents")
    # should outrank generic topic overlap. Ignore mostly stopword phrases.
    words = re.findall(r"[\w]+", question.casefold())
    phrases = {" ".join(words[i:i + 3]) for i in range(len(words) - 2)
               if len(lexical_tokens(" ".join(words[i:i + 3]))) >= 2}
    for key, hit in hits.items():
        normalized = " ".join(re.findall(r"[\w]+", hit.page_content.casefold()))
        if any(phrase in normalized for phrase in phrases):
            ranks[key] += 0.05
    return [hits[key] for key in sorted(ranks, key=ranks.get, reverse=True)]


def build_retriever(settings):
    if settings.rag_backend == "supabase":
        from qozon_multi_agent.knowledge_base.cloud import CloudPDFRetriever
        return CloudPDFRetriever(settings=settings, embeddings=build_embeddings(settings))
    return LocalPDFRetriever(settings)


class LocalPDFRetriever:
    def __init__(self, settings: Settings, *, store=None):
        self.settings = settings
        with index_read_lock(settings.rag_vector_directory):
            self._load(store=store)

    def _load(self, *, store=None):
        from langchain_community.retrievers import BM25Retriever

        settings = self.settings
        manifest = json.loads((settings.rag_vector_directory / "index-manifest.json").read_text())
        corpus, records = load_corpus(settings.rag_chunks_directory)
        if (manifest["status"] != "complete" or manifest["corpus_sha256"] != corpus["corpus_sha256"]
                or manifest["model"] != settings.embedding_model_name
                or manifest["dimensions"] != settings.embedding_dimensions):
            raise RetrievalError("retrieval_index_mismatch")
        self.records = {r["id"]: r for r in records}
        self.lexical = BM25Retriever.from_documents(
            [Document(page_content=r["page_content"], metadata={"chunk_id": r["id"]}) for r in records],
            preprocess_func=lexical_tokens, k=max(12, settings.rag_top_k * 3),
        )
        self.store = store or open_store(settings.rag_vector_directory, manifest["collection"],
                                         build_embeddings(settings), create=False)
        self.corpus_sha256 = corpus["corpus_sha256"]
        self.collection = manifest["collection"]
        self.revision = manifest.get("revision", 0)
        self.source_hashes = {item["path"]: item["sha256"] for item in corpus.get("input_files", [])}

    async def retrieve(self, question: str) -> list[Evidence]:
        try:
            with index_read_lock(self.settings.rag_vector_directory):
                index = json.loads((self.settings.rag_vector_directory / "index-manifest.json").read_text())
                if index["status"] != "complete":
                    raise RetrievalError("retrieval_update_pending")
                if (index["corpus_sha256"] != self.corpus_sha256 or index["collection"] != self.collection
                        or index.get("revision", 0) != self.revision):
                    self._load(store=self.store if index["collection"] == self.collection else None)
                return await self._retrieve(question)
        except RetrievalError:
            raise
        except Exception:
            raise RetrievalError("retrieval_unavailable") from None

    async def _retrieve(self, question: str) -> list[Evidence]:
        try:
            with tracing_context(enabled=False):
                results = await self.store.asimilarity_search_with_score(question, k=max(12, self.settings.rag_top_k * 3))
                lexical_hits = await self.lexical.ainvoke(question, config={"callbacks": []})
            results = [(hit, 0) for hit in fuse_hits(
                question, results, lexical_hits, max_distance=self.settings.rag_max_distance)]
            evidence, parents, remaining = [], set(), self.settings.rag_context_characters
            image_selected = False
            for hit, distance in results:
                if len(evidence) >= self.settings.rag_top_k:
                    break
                if not 0 <= distance <= self.settings.rag_max_distance:
                    continue
                record = self.records.get(hit.metadata.get("chunk_id"))
                if record is None or record["page_content"] != hit.page_content:
                    raise RetrievalError("retrieval_record_changed")
                meta = record["metadata"]
                parent = meta["parent_asset_id"]
                if parent and parent in parents:
                    continue
                text, image = resolve_record(
                    self.settings, record, self.source_hashes,
                    budget=min(remaining, self.settings.rag_context_characters // self.settings.rag_top_k),
                    image_selected=image_selected,
                )
                checked, _, _ = checked_document_text(text)
                if checked is None or len(checked) > remaining:
                    continue
                links = published_links(self.settings, meta["document_id"], parent, meta.get("source_sha256", ""))
                evidence.append(Evidence(record["id"], meta["document_id"], meta["source"],
                                         tuple(meta["page_numbers"]), meta["content_type"], parent,
                                         checked, meta["factually_verified"], image, **links,
                                         source_sha256=meta.get("source_sha256", "")))
                remaining -= len(checked)
                if parent:
                    parents.add(parent)
                image_selected = image_selected or image is not None
            return evidence
        except RetrievalError:
            raise
        except Exception:
            raise RetrievalError("retrieval_unavailable") from None
