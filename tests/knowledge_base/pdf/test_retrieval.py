import hashlib
import json

from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document
import pytest

from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.pdf.chunking import digest
from qozon_langchain.knowledge_base.pdf.indexing import index_corpus, open_store
from qozon_langchain.knowledge_base.pdf.retrieval import LocalPDFRetriever, RetrievalError


class FakeEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[1.0, 0.0, 0.0] if "alpha" in text else [0.0, 1.0, 0.0] for text in texts]

    def embed_query(self, text):
        return [1.0, 0.0, 0.0]


def fixture(tmp_path):
    directory = tmp_path / "chunks"
    directory.mkdir()
    records = [{"id": digest(text), "page_content": text,
                "metadata": {"document_id": "book", "source": "synthetic.pdf", "page_numbers": [12 + n],
                             "content_type": "text", "parent_asset_id": "", "factually_verified": False}}
               for n, text in enumerate(["alpha book evidence", "beta book evidence"])]
    raw = "".join(json.dumps(r) + "\n" for r in records)
    (directory / "chunks.jsonl").write_text(raw)
    (directory / "manifest.json").write_text(json.dumps({"corpus_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                                                        "chunk_count": len(records)}))
    settings = Settings(_env_file=None, openai_api_key=None, embedding_dimensions=3,
                        rag_chunks_directory=directory, rag_vector_directory=tmp_path / "chroma")
    embedding = FakeEmbeddings()
    report = index_corpus(settings, embeddings=embedding)
    store = open_store(settings.rag_vector_directory, report["collection"], embedding, create=False)
    return settings, store


def test_query_returns_only_in_distance_evidence_with_canonical_pages(tmp_path):
    import asyncio
    settings, store = fixture(tmp_path)
    retriever = LocalPDFRetriever(settings, store=store)
    evidence = asyncio.run(retriever.retrieve("alpha question"))
    assert len(evidence) == 1 and evidence[0].page_numbers == (12,)
    assert evidence[0].text == "alpha book evidence"


def test_embedding_configuration_change_rejects_index(tmp_path):
    settings, store = fixture(tmp_path)
    settings.embedding_dimensions = 4
    with pytest.raises(RetrievalError, match="retrieval_index_mismatch"):
        LocalPDFRetriever(settings, store=store)


def test_changed_store_text_is_withheld_instead_of_used_as_evidence(tmp_path):
    import asyncio
    settings, store = fixture(tmp_path)
    retriever = LocalPDFRetriever(settings, store=store)
    class ChangedStore:
        async def asimilarity_search_with_score(self, question, **kwargs):
            return [(Document(page_content="altered text", metadata={"chunk_id": next(iter(retriever.records))}), 0.0)]
    retriever.store = ChangedStore()
    with pytest.raises(RetrievalError, match="retrieval_record_changed"):
        asyncio.run(retriever.retrieve("question"))


def test_explicit_source_phrase_can_recover_a_missed_semantic_result(tmp_path):
    import asyncio
    settings, _ = fixture(tmp_path)
    path = settings.rag_chunks_directory / "chunks.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records.append({"id": digest("contents"), "page_content": "Table of contents: anatomy and diagnosis.",
                    "metadata": dict(records[0]["metadata"], page_numbers=[30])})
    raw = "".join(json.dumps(r) + "\n" for r in records)
    path.write_text(raw)
    (settings.rag_chunks_directory / "manifest.json").write_text(json.dumps({
        "corpus_sha256": hashlib.sha256(raw.encode()).hexdigest(), "chunk_count": len(records)}))
    report = index_corpus(settings, embeddings=FakeEmbeddings())
    store = open_store(settings.rag_vector_directory, report["collection"], FakeEmbeddings(), create=False)
    retriever = LocalPDFRetriever(settings, store=store)
    evidence = asyncio.run(retriever.retrieve("What is in the table of contents?"))
    assert evidence[0].page_numbers == (30,)


def test_aims_query_recovers_purpose_sentence_without_a_semantic_match(tmp_path):
    import asyncio
    settings, _ = fixture(tmp_path)
    path = settings.rag_chunks_directory / "chunks.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records.append({"id": digest("purpose"), "page_content": "The purpose is to translate the book and study its philosophy.",
                    "metadata": dict(records[0]["metadata"], page_numbers=[31])})
    raw = "".join(json.dumps(r) + "\n" for r in records)
    path.write_text(raw)
    (settings.rag_chunks_directory / "manifest.json").write_text(json.dumps({
        "corpus_sha256": hashlib.sha256(raw.encode()).hexdigest(), "chunk_count": len(records)}))
    report = index_corpus(settings, embeddings=FakeEmbeddings())
    store = open_store(settings.rag_vector_directory, report["collection"], FakeEmbeddings(), create=False)
    retriever = LocalPDFRetriever(settings, store=store)
    evidence = asyncio.run(retriever.retrieve("What are its two aims?"))
    assert evidence[0].page_numbers == (31,)
