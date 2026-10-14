"""Checkpointed local Chroma indexing with LangChain/OpenAI embeddings.

Only explicitly running this command makes embedding API calls. A SQLite vector
cache saves successful embeddings before Chroma writes, preventing repeated paid
requests after a local insertion failure. No source text is stored in that cache.
"""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from langsmith import tracing_context
from openai import AuthenticationError, RateLimitError, APIConnectionError, APITimeoutError, BadRequestError

from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.pdf.chunking import (
    ChunkRecord, CorpusError, checked_document_text, digest, save_json,
)


class IndexError(Exception):
    """Fixed index errors without documents, keys or raw provider messages."""


def build_embeddings(settings: Settings) -> OpenAIEmbeddings:
    if settings.openai_api_key is None:
        raise IndexError("embedding_key_not_configured")
    return OpenAIEmbeddings(
        model=settings.embedding_model_name, dimensions=settings.embedding_dimensions,
        api_key=settings.openai_api_key, max_retries=0, request_timeout=60,
        chunk_size=32, check_embedding_ctx_length=False,
    )


class CachedEmbeddings(Embeddings):
    """A narrow LangChain Embeddings adapter; cache only corpus vectors, not queries."""

    def __init__(self, underlying: Embeddings, path: Path, *, model: str, dimensions: int):
        self.underlying = underlying
        self.path = path
        self.model = model
        self.dimensions = dimensions
        self.api_batches = 0
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS vectors (identity TEXT PRIMARY KEY, vector TEXT NOT NULL)")
        path.chmod(0o600)

    def _valid(self, vector):
        if len(vector) != self.dimensions or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector):
            raise IndexError("invalid_embedding_vector")
        return vector

    def embed_documents(self, texts):
        keys = [digest([self.model, self.dimensions, text]) for text in texts]
        with sqlite3.connect(self.path) as db:
            found = {k: self._valid(json.loads(row[0])) for k in set(keys)
                     if (row := db.execute("SELECT vector FROM vectors WHERE identity=?", (k,)).fetchone())}
            pending = dict((k, text) for k, text in zip(keys, texts) if k not in found)
            if pending:
                self.api_batches += 1
                try:
                    with tracing_context(enabled=False):
                        vectors = self.underlying.embed_documents(list(pending.values()))
                except AuthenticationError:
                    raise IndexError("embedding_authentication_failed") from None
                except RateLimitError as error:
                    code = "embedding_quota_exhausted" if error.code == "insufficient_quota" else "embedding_rate_limited"
                    raise IndexError(code) from None
                except APITimeoutError:
                    raise IndexError("embedding_timeout") from None
                except APIConnectionError:
                    raise IndexError("embedding_connection_failed") from None
                except BadRequestError:
                    raise IndexError("embedding_request_rejected") from None
                if len(vectors) != len(pending):
                    raise IndexError("embedding_count_mismatch")
                for key, vector in zip(pending, vectors):
                    found[key] = self._valid(vector)
                    db.execute("INSERT OR REPLACE INTO vectors VALUES (?,?)", (key, json.dumps(vector)))
                db.commit()
            return [found[key] for key in keys]

    def embed_query(self, text):
        with tracing_context(enabled=False):
            return self._valid(self.underlying.embed_query(text))


def open_store(directory: Path, collection: str, embeddings: Embeddings, *, create=True):
    # Local indexing packages are excluded from the public cloud serving image.
    from chromadb.config import Settings as ChromaSettings
    from langchain_chroma import Chroma

    return Chroma(
        collection_name=collection, embedding_function=embeddings,
        persist_directory=str(directory.resolve()),
        client_settings=ChromaSettings(anonymized_telemetry=False),
        collection_configuration={"hnsw": {"space": "cosine"}},
        create_collection_if_not_exists=create,
    )


def scalar_metadata(record: dict) -> dict:
    metadata = record["metadata"]
    return {"chunk_id": record["id"], "document_id": metadata["document_id"],
            "content_type": metadata["content_type"], "source": metadata["source"],
            "page_numbers_json": json.dumps(metadata["page_numbers"]),
            "physical_page": metadata["page_numbers"][0],
            "parent_asset_id": metadata["parent_asset_id"],
            "factually_verified": metadata["factually_verified"]}


def load_corpus(directory: Path):
    raw = (directory / "chunks.jsonl").read_bytes()
    manifest = json.loads((directory / "manifest.json").read_text())
    if hashlib.sha256(raw).hexdigest() != manifest["corpus_sha256"]:
        raise IndexError("corpus_changed")
    records = [ChunkRecord.model_validate_json(line).model_dump() for line in raw.splitlines() if line.strip()]
    if len(records) != manifest["chunk_count"] or len({r["id"] for r in records}) != len(records):
        raise IndexError("corpus_count_invalid")
    for record in records:
        if not record["metadata"]["page_numbers"]:
            raise IndexError("chunk_provenance_missing")
        checked, _, _ = checked_document_text(record["page_content"])
        if checked != record["page_content"]:
            raise IndexError("chunk_privacy_review_required")
    return manifest, records


@contextmanager
def index_read_lock(directory):
    """Hold a shared lock through retrieval; never serve a partially updated index."""
    with (directory / ".index.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise IndexError("index_update_in_progress") from None
        yield


@contextmanager
def index_lock(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / ".index.lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise IndexError("index_already_running") from None
        yield


def index_corpus(settings: Settings, *, embeddings: Embeddings | None = None, batch_size=32):
    if not 1 <= batch_size <= 128:
        raise IndexError("invalid_batch_size")
    corpus, records = load_corpus(settings.rag_chunks_directory)
    directory = settings.rag_vector_directory.resolve()
    identity = {"corpus_sha256": corpus["corpus_sha256"], "model": settings.embedding_model_name,
                "dimensions": settings.embedding_dimensions}
    collection = "qozon_pdf_" + digest(identity)[:24]
    with index_lock(directory):
        if (directory / "incremental-journal.json").exists():
            raise IndexError("incremental_resume_required")
        cached = CachedEmbeddings(embeddings or build_embeddings(settings), directory / "embedding-cache.sqlite3",
                                  model=settings.embedding_model_name, dimensions=settings.embedding_dimensions)
        store = open_store(directory, collection, cached)
        existing = store.get(include=[])["ids"]
        if set(existing) - {r["id"] for r in records}:
            raise IndexError("unexpected_collection_records")
        pending = [r for r in records if r["id"] not in set(existing)]
        progress = dict(identity, status="running", collection=collection, expected_chunks=len(records),
                        completed_chunks=len(existing), api_batches_this_run=0)
        save_json(directory / "index-progress.json", progress)
        try:
            for start in range(0, len(pending), batch_size):
                batch = pending[start:start + batch_size]
                store.add_documents([Document(page_content=r["page_content"], metadata=scalar_metadata(r)) for r in batch],
                                    ids=[r["id"] for r in batch])
                progress.update(completed_chunks=progress["completed_chunks"] + len(batch),
                                api_batches_this_run=cached.api_batches)
                save_json(directory / "index-progress.json", progress)
                print(json.dumps({"indexed_chunks": progress["completed_chunks"], "total_chunks": len(records)}), flush=True)
            saved = store.get(include=[])["ids"]
            if set(saved) != {r["id"] for r in records}:
                raise IndexError("stored_chunk_verification_failed")
            # Reopen the persisted collection and validate IDs across instances.
            reopened = open_store(directory, collection, cached, create=False)
            if set(reopened.get(include=[])["ids"]) != set(saved):
                raise IndexError("index_persistence_failed")
            progress.update(status="complete", completed_chunks=len(saved), api_batches_this_run=cached.api_batches)
            save_json(directory / "index-progress.json", progress)
            save_json(directory / "index-manifest.json", progress)
            return progress
        except Exception as error:
            code = str(error) if isinstance(error, IndexError) else "embedding_or_storage_failed"
            progress.update(status="failed", code=code, api_batches_this_run=cached.api_batches)
            save_json(directory / "index-progress.json", progress)
            raise IndexError(code) from None


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    try:
        print(json.dumps(index_corpus(Settings(), batch_size=args.batch_size)))
    except Exception as error:
        print(json.dumps({"status": "failed", "code": str(error) if isinstance(error, IndexError) else "index_unavailable"}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
