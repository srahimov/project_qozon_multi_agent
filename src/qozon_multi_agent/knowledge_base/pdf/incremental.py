"""Update changed source units in the existing Chroma collection.

Preview is local only. --initialize adopts an existing unchanged corpus without
splitting. --apply embeds only cache misses and mutates only added/deleted IDs.
A private journal freezes the target corpus; --resume completes an interrupted
commit without splitting or re-embedding already cached successful calls.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

from langchain_core.documents import Document

from qozon_multi_agent.core.config import Settings
from qozon_multi_agent.knowledge_base.pdf.chunking import (
    VERSION, CorpusError, atomic_write, checked_document_text, collect_source_units,
    corpus_payload, digest, save_json, split_source_unit, unit_snapshot,
)
from qozon_multi_agent.knowledge_base.pdf.indexing import (
    CachedEmbeddings, IndexError, build_embeddings, index_lock, load_corpus,
    open_store, scalar_metadata,
)

DEFAULT_PROGRESS = Path("data/pdf-assets/full-book/progress.json")
DEFAULT_SUMMARIES = Path("data/pdf-summaries/summary-index.json")


def _index(settings, corpus):
    index = json.loads((settings.rag_vector_directory / "index-manifest.json").read_text())
    if (index["corpus_sha256"] != corpus["corpus_sha256"]
            or index["model"] != settings.embedding_model_name
            or index["dimensions"] != settings.embedding_dimensions
            or index["status"] != "complete"):
        raise IndexError("incremental_index_mismatch")
    return index


def _snapshot(settings, corpus, records):
    path = settings.rag_chunks_directory / "source-units.json"
    if not path.exists():
        raise CorpusError("incremental_baseline_required")
    saved = json.loads(path.read_text())
    if (saved["version"] != "source-units-v1" or saved["corpus_sha256"] != corpus["corpus_sha256"]
            or saved["document_id"] != corpus["document_id"]
            or saved["chunk_size"] != corpus["chunk_size"]
            or saved["chunk_overlap"] != corpus["chunk_overlap"]
            or saved["chunking_version"] != VERSION):
        raise CorpusError("source_unit_snapshot_mismatch")
    ids = [c for unit in saved["units"] for c in unit["chunk_ids"]]
    if (len(ids) != len(set(ids)) or set(ids) != {r["id"] for r in records}
            or len(saved["units"]) != len({u["id"] for u in saved["units"]})):
        raise CorpusError("source_unit_membership_invalid")
    return saved


def _collect(corpus, progress, summaries):
    units, report = collect_source_units(progress, summaries, size=corpus["chunk_size"],
                                         overlap=corpus["chunk_overlap"])
    if report["document_id"] != corpus["document_id"] or corpus["chunking_version"] != VERSION:
        raise CorpusError("document_or_splitter_version_changed")
    return units, report


def initialize_sources(settings, *, progress=DEFAULT_PROGRESS, summaries=DEFAULT_SUMMARIES):
    """Map saved chunks back to unchanged groups by their element refs and offsets."""
    with index_lock(settings.rag_vector_directory):
        corpus, records = load_corpus(settings.rag_chunks_directory)
        index = _index(settings, corpus)
        if (settings.rag_vector_directory / "incremental-journal.json").exists():
            raise IndexError("incremental_resume_required")
        if (settings.rag_chunks_directory / "source-units.json").exists():
            saved = _snapshot(settings, corpus, records)
            return {"status": "already_initialized", "source_units": len(saved["units"]),
                    "split_units": 0, "new_embeddings": 0}
        _validate_store(open_store(settings.rag_vector_directory, index["collection"], None, create=False), records)
        units, report = _collect(corpus, progress, summaries)
        if corpus["input_files"] != report["input_files"]:
            raise CorpusError("baseline_sources_changed")
        if any("chunk_id" in hold for hold in corpus["holds"]):
            raise CorpusError("baseline_chunk_holds_need_review")
        memberships = {u["id"]: [] for u in units}
        lookup, by_id = {}, {u["id"]: u for u in units}
        for unit in units:
            for span in unit["spans"]:
                key = (unit["metadata"]["manifest"], unit["metadata"]["content_type"], span["ref"])
                if key in lookup:
                    raise CorpusError("ambiguous_source_unit")
                lookup[key] = unit["id"]
        for record in records:
            meta = record["metadata"]
            owners = {lookup.get((meta["manifest"], meta["content_type"], ref)) for ref in meta["element_refs"]}
            if len(owners) != 1 or None in owners:
                raise CorpusError("source_unit_mapping_failed")
            unit = by_id[owners.pop()]
            if any(meta.get(k) != v for k, v in unit["metadata"].items()):
                raise CorpusError("baseline_metadata_changed")
            text = unit["text"]
            if meta.get("offset_scope") == "redacted_parent_chunk":
                text, _, _ = checked_document_text(text[meta["source_start_index"]:meta["source_end_index"]])
                if text is None:
                    raise CorpusError("baseline_text_changed")
            start = meta["start_index"]
            if text[start:start + len(record["page_content"])] != record["page_content"]:
                raise CorpusError("baseline_text_changed")
            if record["id"] != digest({"content": record["page_content"], "metadata": meta}):
                raise CorpusError("baseline_chunk_identity_invalid")
            memberships[unit["id"]].append(record["id"])
        by_chunk = {r["id"]: r for r in records}
        details = {}
        for unit in units:
            redactions = len({by_chunk[key]["metadata"]["parent_chunk_id"] for key in memberships[unit["id"]]
                              if "parent_chunk_id" in by_chunk[key]["metadata"]})
            details[unit["id"]] = dict(holds=[], extra_counts={"post_split_redactions": redactions} if redactions else {})
        save_json(settings.rag_chunks_directory / "source-units.json", unit_snapshot(units, memberships, corpus, details))
        return {"status": "initialized", "source_units": len(units), "chunks": len(records),
                "split_units": 0, "new_embeddings": 0}


def _embedding_misses(settings, records):
    keys = {digest([settings.embedding_model_name, settings.embedding_dimensions, r["page_content"]])
            for r in records}
    path = settings.rag_vector_directory / "embedding-cache.sqlite3"
    if not path.exists():
        return len(keys)
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as db:
        cached = {row[0] for row in db.execute("SELECT identity FROM vectors")}
    return len(keys - cached)


def plan_update(settings, *, progress=DEFAULT_PROGRESS, summaries=DEFAULT_SUMMARIES):
    """Scan fingerprints; call the splitter only for changed/new source units."""
    corpus, old = load_corpus(settings.rag_chunks_directory)
    index = _index(settings, corpus)
    saved = _snapshot(settings, corpus, old)
    units, report = _collect(corpus, progress, summaries)
    previous = {u["id"]: u for u in saved["units"]}
    old_records = {r["id"]: r for r in old}
    records, memberships, changed, details = [], {}, [], {}
    counts = Counter(report["input_counts"])
    for unit in units:
        before = previous.get(unit["id"])
        if before and before["fingerprint"] == unit["fingerprint"]:
            batch = [old_records[c] for c in before["chunk_ids"]]
            holds, extra = before.get("holds", []), before.get("extra_counts", {})
        else:
            batch, holds, extra = split_source_unit(unit, size=corpus["chunk_size"], overlap=corpus["chunk_overlap"])
            changed.append(unit["id"])
        report["holds"].extend(holds)
        counts.update(extra)
        details[unit["id"]] = dict(holds=holds, extra_counts=extra)
        records.extend(batch)
        memberships[unit["id"]] = [r["id"] for r in batch]
    # Preserve the original order on a no-op, including bootstrap ordering.
    removed = set(previous) - set(memberships)
    if not changed and not removed:
        records = old
    report["input_counts"] = dict(counts)
    raw, report = corpus_payload(records, report)
    target = unit_snapshot(units, memberships, report, details)
    current_ids, target_ids = set(old_records), {r["id"] for r in records}
    added = [r for r in records if r["id"] not in current_ids]
    stats = {"status": "preview", "collection": index["collection"], "changed_source_units": len(changed),
             "removed_source_units": len(removed), "split_units": len(changed),
             "added_chunks": len(added), "deleted_chunks": len(current_ids - target_ids),
             "unchanged_chunks": len(current_ids & target_ids), "total_chunks": len(records),
             "new_embedding_texts": _embedding_misses(settings, added)}
    return dict(corpus=corpus, index=index, snapshot=target, report=report, records=records,
                raw=raw, added=added, deleted=sorted(current_ids - target_ids), stats=stats)


def _validate_store(store, records):
    stored = store.get(include=["documents", "metadatas"])
    expected = {r["id"]: r for r in records}
    if set(stored["ids"]) != set(expected):
        raise IndexError("incremental_collection_ids_mismatch")
    for key, text, metadata in zip(stored["ids"], stored["documents"], stored["metadatas"]):
        if text != expected[key]["page_content"] or metadata != scalar_metadata(expected[key]):
            raise IndexError("incremental_collection_record_mismatch")


def _commit(settings, journal, *, embeddings=None, batch_size=32):
    root = settings.rag_vector_directory
    stage = root / "incremental-stage"
    manifest, records = load_corpus(stage)
    snapshot = json.loads((stage / "source-units.json").read_text())
    if (manifest["corpus_sha256"] != journal["target_sha256"]
            or snapshot["corpus_sha256"] != journal["target_sha256"]
            or journal["model"] != settings.embedding_model_name
            or journal["dimensions"] != settings.embedding_dimensions
            or journal["chunks_directory"] != str(settings.rag_chunks_directory.resolve())):
        raise IndexError("incremental_journal_mismatch")
    # Sources may have been edited again after an interruption/provider call.
    units, _ = _collect(manifest, Path(journal["progress"]), Path(journal["summaries"]))
    if [(u["id"], u["fingerprint"]) for u in units] != [(u["id"], u["fingerprint"]) for u in snapshot["units"]]:
        raise CorpusError("incremental_target_sources_changed")
    active = json.loads((root / "index-manifest.json").read_text())
    if (active["collection"] != journal["collection"]
            or active["corpus_sha256"] not in {journal["base_sha256"], journal["target_sha256"]}
            or active["model"] != journal["model"] or active["dimensions"] != journal["dimensions"]):
        raise IndexError("incremental_journal_mismatch")
    added = [r for r in records if r["id"] in set(journal["added_ids"])]
    cached = None
    if added:
        cached = CachedEmbeddings(embeddings or build_embeddings(settings), root / "embedding-cache.sqlite3",
                                  model=settings.embedding_model_name, dimensions=settings.embedding_dimensions)
        # Save all successful new vectors BEFORE any Chroma mutation.
        for start in range(0, len(added), batch_size):
            cached.embed_documents([r["page_content"] for r in added[start:start + batch_size]])
    # A source edit during embedding must not commit an already obsolete target.
    latest, _ = _collect(manifest, Path(journal["progress"]), Path(journal["summaries"]))
    if [(u["id"], u["fingerprint"]) for u in latest] != [(u["id"], u["fingerprint"]) for u in snapshot["units"]]:
        raise CorpusError("incremental_target_sources_changed")
    store = open_store(root, journal["collection"], cached, create=False)
    ids = set(store.get(include=[])["ids"])
    allowed = {r["id"] for r in records} | set(journal["deleted_ids"])
    if ids - allowed:
        raise IndexError("unexpected_collection_records")
    try:
        save_json(root / "index-manifest.json", dict(active, status="updating"))
        for start in range(0, len(added), batch_size):
            batch = added[start:start + batch_size]
            store.add_documents([Document(page_content=r["page_content"], metadata=scalar_metadata(r)) for r in batch],
                                ids=[r["id"] for r in batch])
        for start in range(0, len(journal["deleted_ids"]), batch_size):
            store.delete(ids=journal["deleted_ids"][start:start + batch_size])
        _validate_store(store, records)
        output = settings.rag_chunks_directory
        atomic_write(output / "chunks.jsonl", (stage / "chunks.jsonl").read_text())
        save_json(output / "manifest.json", manifest)
        save_json(output / "source-units.json", snapshot)
        save_json(output / "verification.json", {k: v for k, v in manifest.items() if k != "input_files"})
        updated = dict(active, status="complete", corpus_sha256=manifest["corpus_sha256"],
                       expected_chunks=len(records), completed_chunks=len(records),
                       api_batches_this_run=cached.api_batches if cached else 0,
                       update_method="incremental", revision=active.get("revision", 0) + 1)
        # Reopen persisted Chroma and confirm all target records before releasing readers.
        _validate_store(open_store(root, journal["collection"], cached, create=False), records)
        save_json(root / "index-progress.json", updated)
        save_json(root / "index-manifest.json", updated)
        result = dict(journal["stats"], status="complete", corpus_sha256=manifest["corpus_sha256"],
                      api_batches_this_run=updated["api_batches_this_run"])
        save_json(root / "incremental-last-update.json", result)
        (root / "incremental-journal.json").unlink()
        return result
    except Exception:
        save_json(root / "index-manifest.json", dict(active, status="update_pending"))
        raise IndexError("incremental_resume_required") from None


def update_sources(settings, *, progress=DEFAULT_PROGRESS, summaries=DEFAULT_SUMMARIES,
                   apply=False, resume=False, embeddings=None, batch_size=32):
    if not 1 <= batch_size <= 128:
        raise IndexError("invalid_batch_size")
    with index_lock(settings.rag_vector_directory):
        journal_path = settings.rag_vector_directory / "incremental-journal.json"
        if resume:
            if not journal_path.exists():
                raise IndexError("incremental_journal_missing")
            return _commit(settings, json.loads(journal_path.read_text()), embeddings=embeddings, batch_size=batch_size)
        if journal_path.exists():
            raise IndexError("incremental_resume_required")
        plan = plan_update(settings, progress=progress, summaries=summaries)
        if not apply:
            return plan["stats"]
        store = open_store(settings.rag_vector_directory, plan["index"]["collection"], None, create=False)
        _, before = load_corpus(settings.rag_chunks_directory)
        _validate_store(store, before)
        if not plan["added"] and not plan["deleted"] and plan["report"] == plan["corpus"]:
            # No Chroma mutation or embedding client construction on a no-op.
            save_json(settings.rag_chunks_directory / "source-units.json", plan["snapshot"])
            result = dict(plan["stats"], status="unchanged", api_batches_this_run=0)
            save_json(settings.rag_vector_directory / "incremental-last-update.json", result)
            return result
        stage = settings.rag_vector_directory / "incremental-stage"
        atomic_write(stage / "chunks-before.jsonl", (settings.rag_chunks_directory / "chunks.jsonl").read_text())
        save_json(stage / "manifest-before.json", plan["corpus"])
        save_json(stage / "index-before.json", plan["index"])
        atomic_write(stage / "chunks.jsonl", plan["raw"])
        save_json(stage / "manifest.json", plan["report"])
        save_json(stage / "source-units.json", plan["snapshot"])
        journal = dict(base_sha256=plan["corpus"]["corpus_sha256"], target_sha256=plan["report"]["corpus_sha256"],
                       collection=plan["index"]["collection"], model=settings.embedding_model_name,
                       dimensions=settings.embedding_dimensions, added_ids=[r["id"] for r in plan["added"]],
                       deleted_ids=plan["deleted"], stats=plan["stats"],
                       chunks_directory=str(settings.rag_chunks_directory.resolve()),
                       progress=str(Path(progress).resolve()), summaries=str(Path(summaries).resolve()))
        save_json(journal_path, journal)
        return _commit(settings, journal, embeddings=embeddings, batch_size=batch_size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--initialize", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--resume", action="store_true")
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--summaries", type=Path, default=DEFAULT_SUMMARIES)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    try:
        settings = Settings()
        if args.initialize:
            result = initialize_sources(settings, progress=args.progress, summaries=args.summaries)
        else:
            result = update_sources(settings, progress=args.progress, summaries=args.summaries,
                                    apply=args.apply, resume=args.resume, batch_size=args.batch_size)
        print(json.dumps(result))
    except Exception as error:
        print(json.dumps({"status": "failed", "code": str(error) if isinstance(error, (CorpusError, IndexError))
                          else "incremental_update_failed"}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
