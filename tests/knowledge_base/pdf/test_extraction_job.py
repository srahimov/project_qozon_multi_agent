"""Checkpoint recovery and blank-page preservation with local synthetic sources."""

import hashlib
import json
from types import SimpleNamespace

from docling.datamodel.base_models import ConversionStatus
from docling_core.types.doc import (
    BoundingBox, DocItemLabel, DoclingDocument, ImageRef, ProvenanceItem, Size,
)
from PIL import Image
import pypdfium2 as pdfium
import pytest

from qozon_langchain.knowledge_base.pdf.extraction_job import read_batch, run_extraction_job, write_json


def source_file(tmp_path):
    pdf_path = tmp_path / "two-pages.pdf"
    with pdfium.PdfDocument.new() as pdf:
        for _ in range(2):
            pdf.new_page(100, 100).close()
        pdf.save(pdf_path)
    source = tmp_path / "source.json"
    write_json(source, {"path": str(pdf_path), "source": "synthetic.pdf",
                       "size_bytes": pdf_path.stat().st_size,
                       "sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest()})
    return source


class Converter:
    def __init__(self):
        self.calls = []
        self.fail_second = True

    def convert(self, **kwargs):
        start, end = kwargs["page_range"]
        self.calls.append((start, end))
        if start == 2 and self.fail_second:
            raise RuntimeError("synthetic interruption")
        doc = DoclingDocument(name="synthetic")
        for page in range(start, end + 1):
            doc.add_page(page_no=page, size=Size(width=100, height=100),
                image=ImageRef.from_pil(Image.new("RGB", (100, 100), "white"), dpi=72))
            if page == 1:
                doc.add_text(label=DocItemLabel.TEXT, text="Synthetic page.",
                    prov=ProvenanceItem(page_no=page, charspan=(0, 15),
                        bbox=BoundingBox(l=10, t=80, r=90, b=60)))
        return SimpleNamespace(document=doc, status=ConversionStatus.SUCCESS)


def test_resume_skips_committed_pages_and_keeps_blank_page(tmp_path, monkeypatch):
    converter = Converter()
    monkeypatch.setattr("docling.document_converter.DocumentConverter", lambda **kwargs: converter)
    source = source_file(tmp_path)
    output = tmp_path / "job"
    with pytest.raises(Exception):
        run_extraction_job(source, output, batch_size=1, threads=1)
    state = json.loads((output / "progress.json").read_text())
    assert state["completed_pages"] == 1 and state["status"] == "interrupted_or_failed"
    first_manifest = state["batches"][0]["manifest"]
    converter.fail_second = False
    state = run_extraction_job(source, output, batch_size=1, threads=1)
    assert state["status"] == "complete" and state["completed_pages"] == 2
    assert converter.calls == [(1, 1), (2, 2), (2, 2)]
    assert state["batches"][0]["manifest"] == first_manifest
    assert state["batches"][1]["text_blocks"] == 0
    assert state["external_model_calls"] == 0
    assert json.loads((output / "progress.json").read_text())["batches"] == state["batches"]


def test_changed_source_is_rejected_before_conversion(tmp_path, monkeypatch):
    source = source_file(tmp_path)
    pdf_path = json.loads(source.read_text())["path"]
    with open(pdf_path, "ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="source_fingerprint_changed"):
        run_extraction_job(source, tmp_path / "job", threads=1)
    assert not (tmp_path / "job" / "progress.json").exists()


def test_page_coverage_gap_is_not_counted_as_complete(tmp_path):
    manifest = tmp_path / "manifest.json"
    write_json(manifest, {"pages": [{"page_no": 1, "image": "page-1.png"}], "assets": []})
    with pytest.raises(ValueError, match="batch_page_coverage_incomplete"):
        read_batch(manifest, 1, 2)


def test_atomic_checkpoint_is_private_and_leaves_no_temporary_file(tmp_path):
    path = tmp_path / "progress.json"
    write_json(path, {"completed_pages": 1})
    write_json(path, {"completed_pages": 2})
    assert json.loads(path.read_text()) == {"completed_pages": 2}
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [path]


def test_cpu_override_disables_gpu_even_when_mps_is_available(tmp_path, monkeypatch):
    converter = Converter()
    converter.fail_second = False
    options = []
    def build(**kwargs):
        options.append(kwargs["format_options"])
        return converter
    monkeypatch.setattr("docling.document_converter.DocumentConverter", build)
    monkeypatch.setattr("torch.backends.mps.is_available", lambda: True)
    source = source_file(tmp_path)
    state = run_extraction_job(source, tmp_path / "job", batch_size=1, threads=1, device="cpu")
    pipeline = next(iter(options[0].values())).pipeline_options
    assert pipeline.accelerator_options.device == "cpu"
    assert pipeline.ocr_options.rapidocr_params["EngineConfig.torch.use_mps"] is False
    assert pipeline.ocr_options.rapidocr_params["EngineConfig.torch.use_cuda"] is False
    assert state["ocr_device"] == "cpu" and state["status"] == "complete"


def test_resume_on_cpu_resets_previous_gpu_time_estimate(tmp_path, monkeypatch):
    converter = Converter()
    monkeypatch.setattr("docling.document_converter.DocumentConverter", lambda **kwargs: converter)
    source = source_file(tmp_path)
    output = tmp_path / "job"
    with pytest.raises(Exception):
        run_extraction_job(source, output, batch_size=1, threads=1)
    state = json.loads((output / "progress.json").read_text())
    state.update(ocr_device="mps", timing_device="mps", measured_seconds=100_000,
                 measured_pages=1, estimated_remaining_seconds=100_000)
    write_json(output / "progress.json", state)
    converter.fail_second = False
    state = run_extraction_job(source, output, batch_size=1, threads=1, device="cpu")
    assert state["measured_pages"] == 1 and state["measured_seconds"] < 100_000
    assert state["timing_device"] == "cpu"
    assert converter.calls == [(1, 1), (2, 2), (2, 2)]
