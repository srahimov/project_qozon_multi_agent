"""Real local Chroma tests with synthetic sources and fake embeddings only."""

import asyncio
import json

from langchain_core.embeddings import Embeddings
import pytest

from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.pdf.chunking import CorpusError, prepare_corpus
from qozon_langchain.knowledge_base.pdf.incremental import initialize_sources, update_sources
from qozon_langchain.knowledge_base.pdf.indexing import IndexError, index_corpus, index_lock, load_corpus, open_store
from qozon_langchain.knowledge_base.pdf.processing import processing_fingerprint
from qozon_langchain.knowledge_base.pdf.retrieval import LocalPDFRetriever, RetrievalError


class FakeEmbeddings(Embeddings):
    def __init__(self):
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        return [[1.0, 0.0, 0.0] if "alpha" in text else [0.0, 1.0, 0.0] for text in texts]

    def embed_query(self, text):
        return [1.0, 0.0, 0.0]


def fixture(tmp_path, *, summary=False):
    root = tmp_path / "source"
    root.mkdir()
    (root / "page.png").write_bytes(b"synthetic-local-page")
    doc = {"body": {"children": [{"$ref": f"#/texts/{n}"} for n in range(2)]},
           "texts": [{"self_ref": f"#/texts/{n}", "label": "text", "text": word + " evidence. " * 35,
                      "prov": [{"page_no": n + 1}]} for n, word in enumerate(["alpha", "beta"])]}
    dp = root / "document.json"
    dp.write_text(json.dumps(doc))
    manifest = {"document_sha256": "a" * 64, "source": "synthetic.pdf", "document": "document.json",
                "pages": [{"page_no": n, "image": "page.png"} for n in [1, 2]], "assets": []}
    if summary:
        (root / "picture.png").write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
        manifest["assets"] = [{"kind": "picture", "element_ref": "#/pictures/0", "page_numbers": [1],
                               "caption": "Synthetic alpha picture.", "nearby_text": [],
                               "images": [{"image": "picture.png"}]}]
    mp = root / "manifest.json"
    mp.write_text(json.dumps(manifest))
    pp = tmp_path / "progress.json"
    pp.write_text(json.dumps({"status": "complete", "completed_pages": 2, "total_pages": 2,
                             "document_sha256": "a" * 64, "batches": [{"manifest": str(mp)}]}))
    sp = tmp_path / "summaries.json"
    entries = []
    if summary:
        fingerprint = processing_fingerprint(mp, "#/pictures/0")
        path = root / "summary.json"
        path.write_text(json.dumps({"description": "An alpha illustration of a blue square.", "kind": "picture_description",
            "model": "fake", "document_sha256": "a" * 64, "source": "synthetic.pdf", "page_numbers": [1],
            "source_approval": "explicit_source_fingerprint_approval", "processing_identity": {"source_sha256": fingerprint}}))
        entries = [{"manifest": str(mp), "element_ref": "#/pictures/0", "source_sha256": fingerprint,
                    "summary_file": str(path)}]
    sp.write_text(json.dumps({"entries": entries}))
    settings = Settings(_env_file=None, openai_api_key=None, embedding_dimensions=3,
                        rag_chunks_directory=tmp_path / "chunks", rag_vector_directory=tmp_path / "chroma")
    prepare_corpus(pp, sp, settings.rag_chunks_directory, size=100, overlap=15)
    index_corpus(settings, embeddings=FakeEmbeddings())
    return settings, pp, sp, dp


def change_text(path, text):
    doc = json.loads(path.read_text())
    doc["texts"][0]["text"] = text
    path.write_text(json.dumps(doc))


def update(settings, pp, sp, **kw):
    return update_sources(settings, progress=pp, summaries=sp, **kw)


def test_noop_and_legacy_initialization_never_split_or_embed(tmp_path, monkeypatch):
    import qozon_langchain.knowledge_base.pdf.incremental as module
    settings, pp, sp, _ = fixture(tmp_path)
    before = (settings.rag_chunks_directory / "chunks.jsonl").read_bytes()
    (settings.rag_chunks_directory / "source-units.json").unlink()
    def forbidden(*args, **kwargs):
        pytest.fail("Unchanged sources must not be split or embedded")
    monkeypatch.setattr(module, "split_source_unit", forbidden)
    monkeypatch.setattr(module, "build_embeddings", forbidden)
    report = initialize_sources(settings, progress=pp, summaries=sp)
    assert report["split_units"] == 0
    assert update(settings, pp, sp, apply=True)["status"] == "unchanged"
    assert update(settings, pp, sp, apply=True)["split_units"] == 0
    assert (settings.rag_chunks_directory / "chunks.jsonl").read_bytes() == before


def test_changed_group_only_updates_affected_ids_and_reloads_keyword_search(tmp_path, monkeypatch):
    import qozon_langchain.knowledge_base.pdf.incremental as module
    settings, pp, sp, dp = fixture(tmp_path)
    old_index = json.loads((settings.rag_vector_directory / "index-manifest.json").read_text())
    _, before = load_corpus(settings.rag_chunks_directory)
    preserved = {r["id"] for r in before if r["metadata"]["page_numbers"] == [2]}
    store = open_store(settings.rag_vector_directory, old_index["collection"], FakeEmbeddings(), create=False)
    vectors_before = store.get(ids=list(preserved), include=["embeddings"])
    retriever = LocalPDFRetriever(settings, store=store)
    calls, writes, deletes = [], [], []
    original_split, original_open = module.split_source_unit, module.open_store
    def split(unit, **kw):
        calls.append(unit)
        return original_split(unit, **kw)
    class RecordingStore:
        def __init__(self, wrapped): self.wrapped = wrapped
        def get(self, **kw): return self.wrapped.get(**kw)
        def add_documents(self, documents, *, ids):
            writes.extend(ids)
            return self.wrapped.add_documents(documents, ids=ids)
        def delete(self, *, ids):
            deletes.extend(ids)
            return self.wrapped.delete(ids=ids)
    monkeypatch.setattr(module, "split_source_unit", split)
    monkeypatch.setattr(module, "open_store", lambda *a, **k: RecordingStore(original_open(*a, **k)))
    change_text(dp, "alpha updated meteorite evidence. " * 20)
    fake = FakeEmbeddings()
    report = update(settings, pp, sp, apply=True, embeddings=fake)
    _, after = load_corpus(settings.rag_chunks_directory)
    assert report["split_units"] == len(calls) == 1
    assert calls[0]["spans"][0]["pages"] == [1]
    assert report["collection"] == old_index["collection"]
    assert preserved <= {r["id"] for r in after}
    assert not preserved.intersection(writes + deletes)
    assert set(writes) == {r["id"] for r in after} - {r["id"] for r in before}
    assert set(deletes) == {r["id"] for r in before} - {r["id"] for r in after}
    vectors_after = store.get(ids=list(preserved), include=["embeddings"])
    assert vectors_before["embeddings"].tolist() == vectors_after["embeddings"].tolist()
    assert all("beta" not in text for batch in fake.calls for text in batch)
    evidence = asyncio.run(retriever.retrieve("meteorite"))
    assert any("meteorite" in e.text for e in evidence)
    assert set(retriever.records) == {r["id"] for r in after}
    assert {d.metadata["chunk_id"] for d in retriever.lexical.docs} == set(retriever.records)


def test_preview_makes_no_chroma_changes_or_embedding_calls(tmp_path):
    settings, pp, sp, dp = fixture(tmp_path)
    before = (settings.rag_vector_directory / "index-manifest.json").read_bytes()
    change_text(dp, "alpha edited sentence.")
    fake = FakeEmbeddings()
    report = update(settings, pp, sp, embeddings=fake)
    assert report["status"] == "preview" and report["split_units"] == 1
    assert report["new_embedding_texts"] > 0 and not fake.calls
    assert (settings.rag_vector_directory / "index-manifest.json").read_bytes() == before
    assert not (settings.rag_vector_directory / "incremental-journal.json").exists()


def test_removed_or_secret_source_deletes_old_evidence_without_embedding(tmp_path):
    settings, pp, sp, dp = fixture(tmp_path)
    _, before = load_corpus(settings.rag_chunks_directory)
    deleted = {r["id"] for r in before if r["metadata"]["page_numbers"] == [1]}
    change_text(dp, "password=synthetic-secret-value")
    fake = FakeEmbeddings()
    report = update(settings, pp, sp, apply=True, embeddings=fake)
    _, after = load_corpus(settings.rag_chunks_directory)
    assert report["removed_source_units"] == 1 and report["split_units"] == 0
    assert report["deleted_chunks"] == len(deleted) and fake.calls == []
    assert not deleted.intersection(r["id"] for r in after)
    assert all("synthetic-secret-value" not in r["page_content"] for r in after)


@pytest.mark.parametrize("metadata_only", [False, True])
def test_summary_update_only_splits_that_summary_and_preserves_asset_refs(tmp_path, metadata_only):
    settings, pp, sp, _ = fixture(tmp_path, summary=True)
    entry = json.loads(sp.read_text())["entries"][0]
    path = settings.rag_chunks_directory
    _, before = load_corpus(path)
    ordinary = {r["id"] for r in before if r["metadata"]["content_type"] == "text"}
    summary = json.loads(open(entry["summary_file"]).read())
    if metadata_only:
        summary["factually_verified"] = True
    else:
        summary["description"] = "An alpha illustration showing a synthetic red triangle. " * 4
    with open(entry["summary_file"], "w") as file: json.dump(summary, file)
    fake = FakeEmbeddings()
    report = update(settings, pp, sp, apply=True, embeddings=fake)
    _, after = load_corpus(path)
    assert report["split_units"] == 1
    assert ordinary <= {r["id"] for r in after}
    assert bool(fake.calls) != metadata_only
    images = [r for r in after if r["metadata"]["content_type"] == "image_description"]
    assert all(r["metadata"]["source_sha256"] == entry["source_sha256"] for r in images)
    assert {r["metadata"]["parent_asset_id"] for r in images} == {
        r["metadata"]["parent_asset_id"] for r in before if r["metadata"]["content_type"] == "image_description"}


@pytest.mark.parametrize("failure_phase", ["add", "delete", "write"])
def test_interruption_resumes_without_splitting_or_reembedding(tmp_path, monkeypatch, failure_phase):
    import qozon_langchain.knowledge_base.pdf.incremental as module
    settings, pp, sp, dp = fixture(tmp_path)
    index = json.loads((settings.rag_vector_directory / "index-manifest.json").read_text())
    store = open_store(settings.rag_vector_directory, index["collection"], FakeEmbeddings(), create=False)
    retriever = LocalPDFRetriever(settings, store=store)
    change_text(dp, "alpha new resumed evidence. " * 20)
    original_open, original_write = module.open_store, module.atomic_write
    if failure_phase == "write":
        def write(path, text):
            original_write(path, text)
            if path == settings.rag_chunks_directory / "chunks.jsonl":
                raise RuntimeError("synthetic-interruption")
        monkeypatch.setattr(module, "atomic_write", write)
    else:
        class BrokenStore:
            def __init__(self, wrapped): self.wrapped = wrapped
            def get(self, **kw): return self.wrapped.get(**kw)
            def add_documents(self, documents, **kw):
                result = self.wrapped.add_documents(documents, **kw)
                if failure_phase == "add": raise RuntimeError("synthetic-interruption")
                return result
            def delete(self, **kw):
                self.wrapped.delete(**kw)
                raise RuntimeError("synthetic-interruption")
        monkeypatch.setattr(module, "open_store", lambda *a, **k: BrokenStore(original_open(*a, **k)))
    first = FakeEmbeddings()
    with pytest.raises(IndexError, match="incremental_resume_required"):
        update(settings, pp, sp, apply=True, embeddings=first)
    assert first.calls
    with pytest.raises(RetrievalError):
        asyncio.run(retriever.retrieve("resumed"))
    if failure_phase != "write":
        with pytest.raises(IndexError, match="incremental_resume_required"):
            index_corpus(settings, embeddings=FakeEmbeddings())
    monkeypatch.setattr(module, "open_store", original_open)
    monkeypatch.setattr(module, "atomic_write", original_write)
    monkeypatch.setattr(module, "split_source_unit", lambda *a, **k: pytest.fail("Resume must use staged chunks"))
    second = FakeEmbeddings()
    result = update(settings, pp, sp, resume=True, embeddings=second)
    assert result["status"] == "complete" and second.calls == []
    assert not (settings.rag_vector_directory / "incremental-journal.json").exists()
    assert any("resumed" in e.text for e in asyncio.run(retriever.retrieve("resumed")))


def test_changed_pdf_version_requires_new_extraction_baseline(tmp_path):
    settings, pp, sp, _ = fixture(tmp_path)
    progress = json.loads(pp.read_text())
    progress["document_sha256"] = "b" * 64
    pp.write_text(json.dumps(progress))
    fake = FakeEmbeddings()
    with pytest.raises(CorpusError):
        update(settings, pp, sp, apply=True, embeddings=fake)
    assert fake.calls == []


def test_retrieval_does_not_query_during_exclusive_update(tmp_path):
    settings, _, _, _ = fixture(tmp_path)
    index = json.loads((settings.rag_vector_directory / "index-manifest.json").read_text())
    store = open_store(settings.rag_vector_directory, index["collection"], FakeEmbeddings(), create=False)
    retriever = LocalPDFRetriever(settings, store=store)
    with index_lock(settings.rag_vector_directory):
        with pytest.raises(RetrievalError):
            asyncio.run(retriever.retrieve("alpha"))


def test_source_change_after_partial_commit_cannot_resume_stale_target(tmp_path, monkeypatch):
    import qozon_langchain.knowledge_base.pdf.incremental as module
    settings, pp, sp, dp = fixture(tmp_path)
    change_text(dp, "alpha first new version.")
    original_write = module.atomic_write
    def interrupted(path, text):
        if path == settings.rag_chunks_directory / "chunks.jsonl": raise RuntimeError("interrupted")
        original_write(path, text)
    monkeypatch.setattr(module, "atomic_write", interrupted)
    with pytest.raises(IndexError): update(settings, pp, sp, apply=True, embeddings=FakeEmbeddings())
    change_text(dp, "alpha second new version.")
    with pytest.raises(CorpusError, match="incremental_target_sources_changed"):
        update(settings, pp, sp, resume=True, embeddings=FakeEmbeddings())


def test_summary_file_change_is_withheld_until_fingerprint_revision_reload(tmp_path):
    settings, pp, sp, _ = fixture(tmp_path, summary=True)
    index = json.loads((settings.rag_vector_directory / "index-manifest.json").read_text())
    store = open_store(settings.rag_vector_directory, index["collection"], FakeEmbeddings(), create=False)
    retriever = LocalPDFRetriever(settings, store=store)
    entry = json.loads(sp.read_text())["entries"][0]
    with open(entry["summary_file"]) as file: record = json.load(file)
    record["local_review_note"] = "Reviewed synthetic source."
    with open(entry["summary_file"], "w") as file: json.dump(record, file)
    with pytest.raises(RetrievalError, match="retrieval_summary_changed"):
        asyncio.run(retriever.retrieve("blue square"))
    fake = FakeEmbeddings()
    report = update(settings, pp, sp, apply=True, embeddings=fake)
    assert report["added_chunks"] == report["deleted_chunks"] == report["split_units"] == 0
    assert not fake.calls
    assert any("blue square" in e.text for e in asyncio.run(retriever.retrieve("blue square")))


def test_stale_summary_source_approval_stops_before_embedding(tmp_path):
    settings, pp, sp, _ = fixture(tmp_path, summary=True)
    index = sp.read_text()
    entries = json.loads(index)
    entries["entries"][0]["source_sha256"] = "b" * 64
    sp.write_text(json.dumps(entries))
    fake = FakeEmbeddings()
    with pytest.raises(CorpusError, match="summary_source_changed"):
        update(settings, pp, sp, apply=True, embeddings=fake)
    assert not fake.calls
    assert not (settings.rag_vector_directory / "incremental-journal.json").exists()


def test_source_edit_during_embedding_cannot_mutate_chroma(tmp_path):
    settings, pp, sp, dp = fixture(tmp_path)
    old_index = (settings.rag_vector_directory / "index-manifest.json").read_bytes()
    change_text(dp, "alpha selected new version.")
    class EditingEmbeddings(FakeEmbeddings):
        def embed_documents(self, texts):
            result = super().embed_documents(texts)
            change_text(dp, "alpha another edit during embedding.")
            return result
    with pytest.raises(CorpusError, match="incremental_target_sources_changed"):
        update(settings, pp, sp, apply=True, embeddings=EditingEmbeddings())
    assert (settings.rag_vector_directory / "index-manifest.json").read_bytes() == old_index
