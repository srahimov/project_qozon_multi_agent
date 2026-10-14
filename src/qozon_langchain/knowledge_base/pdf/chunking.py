"""Local, reproducible PDF corpus preparation; never calls an embedding or LLM API.

Read rich Docling JSON rather than flattening tables/pictures into ordinary text.
Source integrity and heuristic privacy checks are not factual/OCR verification.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unicodedata

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, ConfigDict, Field

from qozon_langchain.knowledge_base.pdf.processing import processing_fingerprint
from qozon_langchain.security.pii import check_pii
from qozon_langchain.security.policies import training_policy
from qozon_langchain.security.sanitization import has_disallowed_characters
from qozon_langchain.security.screening import screen_document_text
from qozon_langchain.security.secrets import check_secrets

VERSION = "recursive-v1"
DEFAULT_DIRECTORY = Path("data/pdf-chunks")


class CorpusError(Exception):
    """Fixed local error codes without source text or credentials."""


class ChunkRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: str = Field(min_length=64, max_length=64)
    page_content: str = Field(min_length=1)
    metadata: dict


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".prepare-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def local_file(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()) or not path.is_file():
        raise CorpusError("source_file_missing_or_invalid")
    return path


def checked_document_text(text: str) -> tuple[str | None, str, list[str]]:
    """Keep paragraphs; use the document budget, not the question's 200 chars."""
    if not isinstance(text, str) or not text.strip() or len(text) > 100_000:
        return None, "invalid_document_text", []
    text = unicodedata.normalize("NFC", text)
    if has_disallowed_characters(text):
        return None, "disallowed_source_characters", []
    screening = screen_document_text(text)
    if screening.decision != "allow":
        return None, "source_needs_review", list(screening.rule_ids)
    if check_secrets(text).decision != "allow":
        return None, "source_contains_secrets", []
    pii = check_pii(text, policy=training_policy(), direction="input")
    if pii.text is None or pii.decision == "block":
        return None, "source_privacy_check_failed", []
    if check_secrets(pii.text).decision != "allow":
        return None, "source_contains_secrets", []
    return pii.text, "redacted" if pii.text != text else "allow", list(pii.pii_types)


def ordinary_items(document: dict):
    """Walk body reading order, excluding furniture and asset subtrees/captions."""
    seen = set()

    def resolve(ref: str):
        if ref == "#/body":
            return document["body"]
        parts = ref.removeprefix("#/").split("/")
        return document[parts[0]][int(parts[1])]

    def walk(ref: str):
        if ref in seen:
            return
        seen.add(ref)
        item = resolve(ref)
        if ref.startswith(("#/pictures/", "#/tables/")):
            return
        if ref.startswith("#/texts/"):
            if item.get("content_layer", "body") == "body" and item.get("label") not in {
                "caption", "page_header", "page_footer", "picture", "table",
            }:
                yield item
        for child in item.get("children", []):
            yield from walk(child["$ref"])

    yield from walk("#/body")


def make_chunks(text: str, spans: list[dict], metadata: dict, *, size=1000, overlap=150) -> list[dict]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size, chunk_overlap=overlap, length_function=len,
        add_start_index=True, strip_whitespace=False,
    )
    result = []
    for number, doc in enumerate(splitter.split_documents([Document(page_content=text)])):
        start = doc.metadata["start_index"]
        if start < 0 or text[start:start + len(doc.page_content)] != doc.page_content:
            raise CorpusError("chunk_offset_invalid")
        parents = [s for s in spans if s["start"] < start + len(doc.page_content) and s["end"] > start]
        if not parents or not doc.page_content.strip():
            continue
        meta = dict(metadata, chunk_number=number, start_index=start,
                    page_numbers=sorted({p for s in parents for p in s["pages"]}),
                    element_refs=list(dict.fromkeys(s["ref"] for s in parents)),
                    chunking_version=VERSION, chunk_size=size, chunk_overlap=overlap)
        identity = digest({"content": doc.page_content, "metadata": meta})
        record = ChunkRecord(id=identity, page_content=doc.page_content, metadata=meta).model_dump()
        result.append(record)
    # Require all nonwhitespace input characters to belong to at least one chunk.
    covered = bytearray(len(text))
    for c in result:
        start = c["metadata"]["start_index"]
        covered[start:start + len(c["page_content"])] = b"\1" * len(c["page_content"])
    if any(not covered[i] and not char.isspace() for i, char in enumerate(text)):
        raise CorpusError("chunk_coverage_gap")
    return result


def source_unit(text, spans, metadata, *, size, overlap):
    """Identify an existing reading-order group independently of its text version."""
    identity = digest([metadata["document_id"], metadata["manifest"],
                       metadata["content_type"], spans[0]["ref"]])
    fingerprint = digest({"text": text, "spans": spans, "metadata": metadata,
                          "size": size, "overlap": overlap, "version": VERSION,
                          "policy": repr(training_policy())})
    return dict(id=identity, fingerprint=fingerprint, text=text, spans=spans, metadata=metadata)


def collect_source_units(progress_path: Path, summary_index: Path, *, size=1000, overlap=150):
    """Validate and assemble source units without calling the recursive splitter."""
    if not 0 <= overlap < size:
        raise CorpusError("invalid_splitter_configuration")
    progress = json.loads(progress_path.read_text())
    if progress["status"] != "complete" or progress["completed_pages"] != progress["total_pages"]:
        raise CorpusError("extraction_incomplete")
    source_hash = progress["document_sha256"]
    units, holds, exclusions, assets = [], [], [], {}
    page_coverage, input_files = [], []
    counts = Counter()
    for batch in progress["batches"]:
        mp = Path(batch["manifest"]).resolve()
        manifest = json.loads(mp.read_text())
        root = mp.parent
        if manifest["document_sha256"] != source_hash:
            raise CorpusError("mixed_source_documents")
        dp = local_file(root, manifest["document"])
        input_files.append({"path": str(dp), "sha256": hashlib.sha256(dp.read_bytes()).hexdigest()})
        pages = [p["page_no"] for p in manifest["pages"]]
        page_coverage.extend(pages)
        for page in manifest["pages"]:
            local_file(root, page["image"])
        for asset in manifest["assets"]:
            for im in asset["images"]:
                local_file(root, im["image"])
            if asset["kind"] == "table":
                table = json.loads(local_file(root, asset["structured_table"]).read_text())
                local_file(root, asset["markdown"])
                if not any(c.get("text", "").strip() for c in table.get("data", {}).get("table_cells", [])):
                    exclusions.append({"code": "empty_structured_table_text", "pages": asset["page_numbers"],
                                       "manifest": str(mp), "element_ref": asset["element_ref"]})
            assets[(str(mp), asset["element_ref"])] = asset
        document = json.loads(dp.read_text())
        # Each group retains conservative page provenance and exact cleaned-text offsets.
        groups = []
        for item in ordinary_items(document):
            raw = item.get("text", "")
            if not raw.strip():
                continue
            counts["ordinary_source_items"] += 1
            ipages = sorted({p["page_no"] for p in item.get("prov", [])})
            if not ipages or any(p not in pages for p in ipages):
                raise CorpusError("text_page_provenance_missing")
            cleaned, decision, signals = checked_document_text(raw)
            if cleaned is None:
                holds.append({"code": decision, "signals": signals, "pages": ipages,
                              "manifest": str(mp), "element_ref": item["self_ref"]})
                continue
            if decision == "redacted":
                counts["redacted_source_items"] += 1
            if not groups or groups[-1]["pages"] != ipages or item.get("label") in {"section_header", "title"}:
                groups.append({"pages": ipages, "text": "", "spans": []})
            group = groups[-1]
            prefix = "\n\n" if group["text"] else ""
            start = len(group["text"]) + len(prefix)
            group["text"] += prefix + cleaned
            group["spans"].append({"start": start, "end": start + len(cleaned), "pages": ipages, "ref": item["self_ref"]})
        for group in groups:
            base = {"document_id": source_hash, "source": manifest["source"], "content_type": "text",
                    "manifest": str(mp), "original_document": str(dp), "factually_verified": False,
                    "privacy_policy": training_policy().name, "parent_asset_id": ""}
            units.append(source_unit(group["text"], group["spans"], base, size=size, overlap=overlap))
    if sorted(page_coverage) != list(range(1, progress["total_pages"] + 1)):
        raise CorpusError("physical_page_coverage_invalid")
    index = json.loads(summary_index.read_text())
    for entry in index["entries"]:
        path = Path(entry["summary_file"]).resolve()
        record = json.loads(path.read_text())
        mp = str(Path(entry["manifest"]).resolve())
        key = (mp, entry["element_ref"])
        if key not in assets or record["document_sha256"] != source_hash:
            raise CorpusError("summary_source_missing")
        if processing_fingerprint(Path(mp), entry["element_ref"]) != entry["source_sha256"]:
            raise CorpusError("summary_source_changed")
        if (record.get("source_approval") != "explicit_source_fingerprint_approval"
                or record["processing_identity"]["source_sha256"] != entry["source_sha256"]):
            raise CorpusError("summary_approval_mismatch")
        if record["page_numbers"] != assets[key]["page_numbers"]:
            raise CorpusError("summary_page_mismatch")
        text, decision, signals = checked_document_text(record["description"])
        if text is None:
            holds.append({"code": decision, "signals": signals, "pages": record["page_numbers"], "summary": str(path)})
            continue
        input_files.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        kind = "table_summary" if record["kind"] == "table_summary" else "image_description"
        base = {"document_id": source_hash, "source": record["source"], "content_type": kind,
                "manifest": mp, "summary_file": str(path), "source_sha256": entry["source_sha256"],
                "parent_asset_id": digest([source_hash, mp, entry["element_ref"]]),
                "factually_verified": bool(record.get("factually_verified", False)),
                "visual_privacy_verified": bool(record.get("visual_privacy_verified", False)),
                "summary_model": record["model"], "privacy_policy": training_policy().name}
        units.append(source_unit(text, [{"start": 0, "end": len(text), "pages": record["page_numbers"],
                                         "ref": entry["element_ref"]}], base, size=size, overlap=overlap))
        counts[kind + "_assets"] += 1
    report = {"status": "prepared_with_review_notes", "document_id": source_hash,
              "physical_pages_verified": progress["total_pages"],
              "input_counts": dict(counts), "chunk_size": size, "chunk_overlap": overlap,
              "chunking_version": VERSION, "input_files": input_files,
              "holds": holds, "excluded_assets": exclusions, "external_model_calls": 0,
              "factually_verified": False, "visual_privacy_verified": False,
              "quality_notes": ["OCR and factual review remain partial; no full-book accuracy claim.",
                                "Contents table on physical page 5 was reconstructed against the original; crop retained."
                                if any(a.get("repair", {}).get("method") == "visual_transcription"
                                       and a["page_numbers"] == [5] for a in assets.values()) else
                                "Contents table on physical page 5 has uneven column alignment; original crop retained."]}
    if len({u["id"] for u in units}) != len(units):
        raise CorpusError("duplicate_source_units")
    return units, report


def split_source_unit(unit, *, size=1000, overlap=150):
    """Split one unit and recheck the exact payloads before any embedding."""
    chunks = make_chunks(unit["text"], unit["spans"], unit["metadata"], size=size, overlap=overlap)
    holds, counts = [], Counter()
    # Combining paragraphs or splitting at a boundary can create a new match.
    # Recheck the exact payload that will be embedded, not only source items.
    final = []
    for chunk in chunks:
        cleaned, decision, signals = checked_document_text(chunk["page_content"])
        if cleaned is None:
            holds.append({"code": decision, "signals": signals, "chunk_id": chunk["id"],
                          "pages": chunk["metadata"]["page_numbers"]})
            continue
        if cleaned == chunk["page_content"]:
            final.append(chunk)
        else:
            counts["post_split_redactions"] += 1
            meta = dict(chunk["metadata"], parent_chunk_id=chunk["id"],
                        source_start_index=chunk["metadata"]["start_index"],
                        source_end_index=chunk["metadata"]["start_index"] + len(chunk["page_content"]),
                        offset_scope="redacted_parent_chunk")
            spans = [{"start": 0, "end": len(cleaned), "pages": meta["page_numbers"], "ref": ref}
                     for ref in meta["element_refs"]]
            final.extend(make_chunks(cleaned, spans, meta, size=size, overlap=overlap))
    return final, holds, dict(counts)


def corpus_payload(chunks, report):
    """Create a validated canonical corpus payload; this does no splitting."""
    ids = [c["id"] for c in chunks]
    if not chunks or len(ids) != len(set(ids)) or any(len(c["page_content"]) > report["chunk_size"] for c in chunks):
        raise CorpusError("invalid_chunk_records")
    serialized = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks)
    corpus_hash = hashlib.sha256(serialized.encode()).hexdigest()
    report = dict(report, chunk_count=len(chunks), corpus_sha256=corpus_hash,
                  chunk_types=dict(Counter(c["metadata"]["content_type"] for c in chunks)))
    return serialized, report


def unit_snapshot(units, memberships, report, details=None):
    details = details or {}
    return {"version": "source-units-v1", "document_id": report["document_id"],
            "corpus_sha256": report["corpus_sha256"], "chunk_size": report["chunk_size"],
            "chunk_overlap": report["chunk_overlap"], "chunking_version": report["chunking_version"],
            "units": [dict(id=u["id"], fingerprint=u["fingerprint"], chunk_ids=memberships[u["id"]],
                           **details.get(u["id"], {}))
                      for u in units]}


def prepare_corpus(progress_path: Path, summary_index: Path, destination=DEFAULT_DIRECTORY, *, size=1000, overlap=150):
    units, report = collect_source_units(progress_path, summary_index, size=size, overlap=overlap)
    chunks, memberships, details = [], {}, {}
    counts = Counter(report["input_counts"])
    for unit in units:
        records, holds, extra = split_source_unit(unit, size=size, overlap=overlap)
        chunks.extend(records)
        memberships[unit["id"]] = [r["id"] for r in records]
        details[unit["id"]] = dict(holds=holds, extra_counts=extra)
        report["holds"].extend(holds)
        counts.update(extra)
    report["input_counts"] = dict(counts)
    serialized, report = corpus_payload(chunks, report)
    output = Path(destination).resolve()
    atomic_write(output / "chunks.jsonl", serialized)
    save_json(output / "manifest.json", report)
    save_json(output / "verification.json", {k: v for k, v in report.items() if k != "input_files"})
    save_json(output / "source-units.json", unit_snapshot(units, memberships, report, details))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--progress", type=Path, default=Path("data/pdf-assets/full-book/progress.json"))
    parser.add_argument("--summaries", type=Path, default=Path("data/pdf-summaries/summary-index.json"))
    parser.add_argument("--output", type=Path, default=DEFAULT_DIRECTORY)
    args = parser.parse_args()
    try:
        report = prepare_corpus(args.progress, args.summaries, args.output)
    except Exception as error:
        print(json.dumps({"status": "failed", "code": str(error) if isinstance(error, CorpusError) else "corpus_preparation_failed"}))
        raise SystemExit(1) from None
    print(json.dumps({k: report[k] for k in ["status", "chunk_count", "chunk_types", "input_counts"]}))
    print(json.dumps({"held_items": len(report["holds"]), "excluded_assets": len(report["excluded_assets"])}))


if __name__ == "__main__":
    main()
