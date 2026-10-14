"""Resumable local OCR and source export. No description or embedding calls."""

import argparse
import fcntl
import gc
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Literal

from qozon_langchain.knowledge_base.pdf.downloader import DownloadedPDF
from qozon_langchain.knowledge_base.pdf.loader import load_pdf_documents


def write_json(path: Path, value: dict | list) -> None:
    """Replace a checkpoint atomically so interruption cannot truncate it."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".checkpoint-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_batch(manifest_path: Path, start: int, end: int) -> dict:
    """Count only fully exported ranges with every physical page present."""
    manifest = json.loads(manifest_path.read_text())
    pages = sorted(page["page_no"] for page in manifest["pages"])
    if pages != list(range(start, end + 1)):
        raise ValueError("batch_page_coverage_incomplete")
    root = manifest_path.parent.resolve()
    for page in manifest["pages"]:
        path = (root / page["image"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("batch_page_image_missing")
    if not (root / manifest["document"]).is_file():
        raise ValueError("batch_document_missing")
    return {"page_range": [start, end], "manifest": str(manifest_path.resolve()),
            "pictures": sum(item["kind"] == "picture" for item in manifest["assets"]),
            "tables": sum(item["kind"] == "table" for item in manifest["assets"])}


def run_extraction_job(source_file: Path, output_dir: Path, *, batch_size: int = 10,
                       threads: int = 6, seed_manifest: Path | None = None,
                       device: Literal["cpu", "auto"] = "cpu") -> dict:
    if type(batch_size) is not int or not 1 <= batch_size <= 50:
        raise ValueError("invalid_batch_size")
    if type(threads) is not int or not 1 <= threads <= (os.cpu_count() or 1):
        raise ValueError("invalid_thread_count")
    if device not in ("cpu", "auto"):
        raise ValueError("invalid_device")
    source = json.loads(source_file.read_text())
    pdf_path = Path(source["path"]).resolve()
    digest = hashlib.sha256()
    with pdf_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != source["sha256"]:
        raise ValueError("source_fingerprint_changed")
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(pdf_path) as document:
        total_pages = len(document)
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = output_dir / ".job.lock"
    with lock_path.open("a") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        progress_path = output_dir / "progress.json"
        if progress_path.exists():
            state = json.loads(progress_path.read_text())
            if state["document_sha256"] != source["sha256"] or state["total_pages"] != total_pages:
                raise ValueError("checkpoint_source_mismatch")
            next_page = 1
            for batch in state["batches"]:
                start, end = batch["page_range"]
                if start != next_page:
                    raise ValueError("checkpoint_page_gap")
                read_batch(Path(batch["manifest"]), start, end)
                if batch.get("text_documents") and not Path(batch["text_documents"]).is_file():
                    raise ValueError("checkpoint_text_missing")
                next_page = end + 1
        else:
            state = {"source": source["source"], "document_sha256": source["sha256"],
                     "total_pages": total_pages, "batches": [], "measured_seconds": 0.0,
                     "measured_pages": 0, "external_model_calls": 0}
            next_page = 1
            if seed_manifest is not None:
                seed = json.loads(seed_manifest.read_text())
                if seed["document_sha256"] != source["sha256"]:
                    raise ValueError("seed_source_mismatch")
                last_page = max(page["page_no"] for page in seed["pages"])
                state["batches"].append(read_batch(seed_manifest, 1, last_page))
                next_page = last_page + 1
        state.update(status="running", pid=os.getpid(), threads=threads, batch_size=batch_size,
                     completed_pages=next_page - 1, error_code=None,
                     pictures=sum(item["pictures"] for item in state["batches"]),
                     tables=sum(item["tables"] for item in state["batches"]))
        state.pop("failure_stage", None)
        state.pop("verified_saved_pages", None)
        write_json(progress_path, state)
        try:
            # Bound nested image-resize workers. OpenCV is pinned separately
            # after a native resize crash in the ARM 5.0 build.
            import cv2
            cv2.setNumThreads(1)
            import torch
            from docling.datamodel.accelerator_options import AcceleratorOptions
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
            # CPU means CPU for layout/table models AND the OCR engine, even
            # when the host exposes an Apple GPU outside the sandbox.
            use_mps = device == "auto" and torch.backends.mps.is_available()
            current_device = "mps" if use_mps else "cpu"
            if state.get("timing_device", state.get("ocr_device")) != current_device:
                state.update(measured_seconds=0.0, measured_pages=0,
                             estimated_remaining_seconds=None)
            state["timing_device"] = current_device
            state["ocr_device"] = "mps" if use_mps else "cpu"
            state["accelerator_device"] = device
            write_json(progress_path, state)
            options = PdfPipelineOptions(
                accelerator_options=AcceleratorOptions(num_threads=threads, device=device),
                do_ocr=True, do_table_structure=True,
                ocr_options=RapidOcrOptions(backend="torch", lang=[],
                    rapidocr_params={"EngineConfig.torch.use_mps": use_mps,
                                     "EngineConfig.torch.use_cuda": False}),
                generate_page_images=True, generate_picture_images=True, images_scale=2.0,
                do_picture_description=False, enable_remote_services=False,
            )
            converter = DocumentConverter(allowed_formats=[InputFormat.PDF], format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
            downloaded = DownloadedPDF(pdf_path, source["sha256"], source["size_bytes"])
            while next_page <= total_pages:
                end = min(next_page + batch_size - 1, total_pages)
                state["active_page_range"] = [next_page, end]
                write_json(progress_path, state)
                print(f"Extracting pages {next_page}-{end}; completed {next_page-1}/{total_pages}", flush=True)
                started = time.monotonic()
                # One cached converter across all batches keeps loaded models reusable.
                documents = load_pdf_documents(downloaded, source_name=source["source"],
                    page_range=(next_page, end), assets_dir=output_dir / "assets",
                    converter=converter, allow_empty_text=True)
                candidates = list((output_dir / "assets").glob("extraction-*/manifest.json"))
                manifest_path = max(candidates, key=lambda path: path.stat().st_mtime_ns)
                batch = read_batch(manifest_path, next_page, end)
                text_path = manifest_path.parent / "text-documents.json"
                write_json(text_path, [{"page_content": item.page_content, "metadata": item.metadata}
                                       for item in documents])
                batch.update(text_documents=str(text_path.resolve()), text_blocks=len(documents))
                state["batches"].append(batch)
                state["measured_seconds"] += time.monotonic() - started
                state["measured_pages"] += end - next_page + 1
                next_page = end + 1
                state.update(completed_pages=end,
                    estimated_remaining_seconds=(total_pages-end) * state["measured_seconds"] / state["measured_pages"],
                    pictures=sum(item["pictures"] for item in state["batches"]),
                    tables=sum(item["tables"] for item in state["batches"]))
                write_json(progress_path, state)
                print(f"Saved {end}/{total_pages} pages; pictures {state['pictures']}; tables {state['tables']}", flush=True)
                del documents
                gc.collect()
            state.update(status="complete", active_page_range=None, estimated_remaining_seconds=0)
            write_json(progress_path, state)
            return state
        except BaseException:
            state.update(status="interrupted_or_failed", error_code="local_extraction_stopped")
            write_json(progress_path, state)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Local checkpointed PDF extraction; no LLM calls")
    parser.add_argument("--source", type=Path, default=Path("data/pdf-source.json"))
    parser.add_argument("--output", type=Path, default=Path("data/pdf-assets/full-book"))
    parser.add_argument("--seed-manifest", type=Path)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--threads", type=int, default=min(6, os.cpu_count() or 1))
    parser.add_argument("--device", choices=("cpu", "auto"), default="cpu")
    args = parser.parse_args()
    try:
        run_extraction_job(args.source, args.output, batch_size=args.batch_size,
                           threads=args.threads, seed_manifest=args.seed_manifest,
                           device=args.device)
    except Exception:
        print("Local extraction stopped; inspect the checkpoint and resume completed batches.", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
