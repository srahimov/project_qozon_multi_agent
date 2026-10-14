"""Preservation tests using real Docling elements and synthetic page pixels."""

import json
import stat

from docling_core.types.doc import (
    BoundingBox, CoordOrigin, DocItemLabel, DoclingDocument, ImageRef,
    ProvenanceItem, Size, TableCell, TableData,
)
from PIL import Image
import pytest

from qozon_langchain.knowledge_base.pdf.assets import PDFAssetError, save_pdf_assets
from qozon_langchain.knowledge_base.pdf.loader import load_pdf_documents
from .test_loader import FakeConverter, sample_pdf


def rich_document():
    doc = DoclingDocument(name="synthetic")
    doc.add_page(page_no=1, size=Size(width=100, height=100),
                 image=ImageRef.from_pil(Image.new("RGB", (100, 100), "white"), dpi=72))
    prov = ProvenanceItem(page_no=1, bbox=BoundingBox(l=10, t=10, r=60, b=60,
                           coord_origin=CoordOrigin.TOPLEFT), charspan=(0, 0))
    caption = doc.add_text(label=DocItemLabel.CAPTION, text="Figure: synthetic blue square", prov=prov)
    doc.add_picture(caption=caption, prov=prov,
                    image=ImageRef.from_pil(Image.new("RGB", (50, 50), "blue"), dpi=72))
    caption = doc.add_text(label=DocItemLabel.CAPTION, text="Table: fruit counts", prov=prov)
    cells = []
    for row, values in enumerate((("Item", "Count"), ("Apples", "10"))):
        for col, text in enumerate(values):
            cells.append(TableCell(text=text, start_row_offset_idx=row, end_row_offset_idx=row + 1,
                         start_col_offset_idx=col, end_col_offset_idx=col + 1, column_header=row == 0))
    doc.add_table(data=TableData(num_rows=2, num_cols=2, table_cells=cells), caption=caption, prov=prov)
    doc.add_text(label=DocItemLabel.TEXT, text="Nearby explanation of the figure and table.", prov=prov)
    return doc


def test_preserves_table_picture_caption_full_page_and_reading_order(tmp_path):
    manifest_path = save_pdf_assets(rich_document(), destination_dir=tmp_path / "assets",
                                   source_name="Book.pdf", document_sha256="synthetic-hash")
    manifest = json.loads(manifest_path.read_text())
    root = manifest_path.parent
    assert manifest["privacy_status"] == "unreviewed"
    assert manifest["descriptions_generated"] is False
    with Image.open(root / manifest["pages"][0]["image"]) as page:
        assert page.size == (100, 100)
    picture, table = manifest["assets"]
    assert picture["caption"] == "Figure: synthetic blue square"
    assert picture["caption_refs"] and picture["page_numbers"] == [1]
    assert any("Nearby explanation" in item["text"] for item in picture["nearby_text"])
    with Image.open(root / picture["images"][0]["image"]) as image:
        assert image.size == (50, 50) and image.getpixel((20, 20)) == (0, 0, 255)
    assert "Apples" in (root / table["markdown"]).read_text()
    data = json.loads((root / table["structured_table"]).read_text())
    assert data["data"]["num_rows"] == 2 and data["data"]["num_cols"] == 2
    assert table["caption"] == "Table: fruit counts"
    restored = DoclingDocument.load_from_json(root / manifest["document"])
    assert len(restored.tables) == len(restored.pictures) == 1
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in root.rglob("*") if path.is_file())


def test_loader_links_chunks_to_saved_sources_from_one_conversion(tmp_path):
    converter = FakeConverter(rich_document())
    docs = load_pdf_documents(sample_pdf(tmp_path), source_name="Book.pdf", page_range=(1, 1),
                              assets_dir=tmp_path / "assets", converter=converter)
    assert len(converter.calls) == 1
    assert docs and all(doc.metadata["element_refs"] for doc in docs)
    assert len({doc.metadata["asset_manifest"] for doc in docs}) == 1
    assert len(list((tmp_path / "assets").glob("extraction-*/manifest.json"))) == 1


def test_runs_preserve_previous_assets_instead_of_overwriting(tmp_path):
    first = save_pdf_assets(rich_document(), destination_dir=tmp_path, source_name="Book.pdf", document_sha256="hash")
    second = save_pdf_assets(rich_document(), destination_dir=tmp_path, source_name="Book.pdf", document_sha256="hash")
    assert first != second and first.is_file() and second.is_file()


def test_missing_page_image_cleans_failed_export_only(tmp_path):
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("existing")
    doc = DoclingDocument(name="synthetic")
    doc.add_page(page_no=1, size=Size(width=100, height=100))
    with pytest.raises(PDFAssetError, match="pdf_page_image_missing"):
        save_pdf_assets(doc, destination_dir=tmp_path, source_name="Book.pdf", document_sha256="hash")
    assert list(tmp_path.iterdir()) == [sentinel]


def test_export_failure_withholds_results_and_suppresses_upstream_details(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic-private-document-value")
    monkeypatch.setattr(DoclingDocument, "save_as_json", fail)
    with pytest.raises(PDFAssetError) as error:
        load_pdf_documents(sample_pdf(tmp_path), source_name="Book.pdf", converter=FakeConverter(rich_document()),
                           assets_dir=tmp_path / "assets")
    assert str(error.value) == "pdf_asset_export_failed"
    assert error.value.__suppress_context__
    assert list((tmp_path / "assets").iterdir()) == []
