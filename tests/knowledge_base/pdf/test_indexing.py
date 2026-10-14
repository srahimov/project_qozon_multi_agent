import hashlib
import json

from langchain_core.embeddings import Embeddings
import pytest

from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.pdf.chunking import digest
from qozon_langchain.knowledge_base.pdf.indexing import CachedEmbeddings, IndexError, index_corpus, load_corpus


class FakeEmbeddings(Embeddings):
    def __init__(self):
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        return [[1.0, 0.0, 0.0] if "alpha" in text else [0.0, 1.0, 0.0] for text in texts]

    def embed_query(self, text):
        return [1.0, 0.0, 0.0]


def corpus_fixture(tmp_path):
    directory = tmp_path / "chunks"
    directory.mkdir()
    records = []
    for text in ["alpha book evidence", "beta book evidence"]:
        records.append({"id": digest(text), "page_content": text,
                        "metadata": {"document_id": "book", "source": "synthetic.pdf", "page_numbers": [1],
                                     "content_type": "text", "parent_asset_id": "", "factually_verified": False}})
    raw = "".join(json.dumps(r) + "\n" for r in records)
    (directory / "chunks.jsonl").write_text(raw)
    (directory / "manifest.json").write_text(json.dumps({"corpus_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                                                        "chunk_count": len(records)}))
    settings = Settings(_env_file=None, openai_api_key=None, embedding_dimensions=3,
                        rag_chunks_directory=directory, rag_vector_directory=tmp_path / "chroma")
    return settings, records


def test_embedding_cache_reuses_identical_text_and_survives_restart(tmp_path):
    model = FakeEmbeddings()
    cached = CachedEmbeddings(model, tmp_path / "cache.sqlite", model="fake", dimensions=3)
    vectors = cached.embed_documents(["alpha", "alpha", "beta"])
    assert len(model.calls) == 1 and len(model.calls[0]) == 2
    new_model = FakeEmbeddings()
    reopened = CachedEmbeddings(new_model, tmp_path / "cache.sqlite", model="fake", dimensions=3)
    assert reopened.embed_documents(["alpha", "alpha", "beta"]) == vectors
    assert new_model.calls == []


def test_dimension_change_never_reuses_incompatible_cache(tmp_path):
    model = FakeEmbeddings()
    cached = CachedEmbeddings(model, tmp_path / "cache.sqlite", model="fake", dimensions=3)
    cached.embed_documents(["alpha"])
    wrong = CachedEmbeddings(model, tmp_path / "cache.sqlite", model="fake", dimensions=4)
    with pytest.raises(IndexError, match="invalid_embedding_vector"):
        wrong.embed_documents(["alpha"])


def test_chroma_index_resumes_without_reembedding_and_reopens(tmp_path):
    settings, records = corpus_fixture(tmp_path)
    model = FakeEmbeddings()
    report = index_corpus(settings, embeddings=model, batch_size=1)
    assert report["status"] == "complete" and report["completed_chunks"] == 2
    assert len(model.calls) == 2
    second = FakeEmbeddings()
    repeated = index_corpus(settings, embeddings=second)
    assert repeated["api_batches_this_run"] == 0 and second.calls == []


def test_modified_corpus_stops_before_embedding(tmp_path):
    settings, _ = corpus_fixture(tmp_path)
    with (settings.rag_chunks_directory / "chunks.jsonl").open("a") as stream:
        stream.write(" ")
    model = FakeEmbeddings()
    with pytest.raises(IndexError, match="corpus_changed"):
        index_corpus(settings, embeddings=model)
    assert model.calls == []


def test_secret_in_corpus_cannot_reach_embedding_api(tmp_path):
    settings, records = corpus_fixture(tmp_path)
    records[0]["page_content"] = "password=synthetic-secret-value"
    raw = "".join(json.dumps(r) + "\n" for r in records)
    (settings.rag_chunks_directory / "chunks.jsonl").write_text(raw)
    (settings.rag_chunks_directory / "manifest.json").write_text(json.dumps({
        "corpus_sha256": hashlib.sha256(raw.encode()).hexdigest(), "chunk_count": 2}))
    with pytest.raises(IndexError, match="chunk_privacy_review_required"):
        load_corpus(settings.rag_chunks_directory)


def test_failed_local_insertion_reuses_successful_embeddings_on_resume(tmp_path, monkeypatch):
    import qozon_langchain.knowledge_base.pdf.indexing as module
    settings, _ = corpus_fixture(tmp_path)
    original_open = module.open_store
    model = FakeEmbeddings()

    def broken_open(directory, collection, embeddings, **kwargs):
        class BrokenStore:
            def get(self, **kwargs):
                return {"ids": []}

            def add_documents(self, documents, **kwargs):
                embeddings.embed_documents([d.page_content for d in documents])
                raise RuntimeError("synthetic-storage-failure")
        return BrokenStore()

    monkeypatch.setattr(module, "open_store", broken_open)
    with pytest.raises(IndexError):
        index_corpus(settings, embeddings=model)
    assert len(model.calls) == 1
    monkeypatch.setattr(module, "open_store", original_open)
    resumed_model = FakeEmbeddings()
    report = index_corpus(settings, embeddings=resumed_model)
    assert report["status"] == "complete" and resumed_model.calls == []
