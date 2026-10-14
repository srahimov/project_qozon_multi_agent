"""Test the real LangChain/Docling export with an offline conversion result."""

from types import SimpleNamespace

from docling.datamodel.base_models import ConversionStatus
from docling_core.types.doc import BoundingBox, DocItemLabel, DoclingDocument, ProvenanceItem, Size
import pytest

from qozon_langchain.knowledge_base.pdf.downloader import DownloadedPDF
from qozon_langchain.knowledge_base.pdf.loader import PDFExtractionError, load_pdf_documents


class FakeConverter:
    def __init__(self, document, status=ConversionStatus.SUCCESS):
        self.document = document
        self.status = status
        self.calls = []

    def convert(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(document=self.document, status=self.status)


def sample_pdf(tmp_path):
    path = tmp_path / "sample.pdf"
    content = b"%PDF-synthetic"
    path.write_bytes(content)
    return DownloadedPDF(path=path, sha256="synthetic-content-hash", size_bytes=len(content))


def sample_document(with_provenance=True):
    doc = DoclingDocument(name="synthetic")
    for page, text in [(1, "Apples are fruit."), (2, "Carrots are vegetables.")]:
        doc.add_page(page_no=page, size=Size(width=600, height=800))
        doc.add_text(
            label=DocItemLabel.TEXT, text=text,
            prov=ProvenanceItem(
                page_no=page, bbox=BoundingBox(l=0, t=0, r=100, b=20),
                charspan=(0, len(text)),
            ) if with_provenance else None,
        )
    return doc


def test_langchain_docling_export_retains_physical_pages_and_hash(tmp_path):
    converter = FakeConverter(sample_document())
    pdf = sample_pdf(tmp_path)
    documents = load_pdf_documents(pdf, source_name="Book.pdf", page_range=(1, 2),
                                   converter=converter)
    assert [doc.page_content for doc in documents] == ["Apples are fruit.", "Carrots are vegetables."]
    assert [doc.metadata["page_numbers"] for doc in documents] == [[1], [2]]
    assert all(doc.metadata["document_sha256"] == pdf.sha256 for doc in documents)
    assert all(doc.metadata["source"] == "Book.pdf" for doc in documents)
    assert converter.calls == [{"source": str(pdf.path), "page_range": (1, 2),
                                "max_file_size": 128 * 1024 * 1024, "raises_on_error": True}]


@pytest.mark.parametrize("page_range", [(0, 2), (2, 1), (True, 2), (1,), [1, 2]])
def test_invalid_range_stops_before_conversion(tmp_path, page_range):
    converter = FakeConverter(sample_document())
    with pytest.raises(PDFExtractionError, match="invalid_page_range"):
        load_pdf_documents(sample_pdf(tmp_path), source_name="Book.pdf",
                           page_range=page_range, converter=converter)
    assert not converter.calls


@pytest.mark.parametrize("status", [ConversionStatus.PARTIAL_SUCCESS, ConversionStatus.FAILURE])
def test_partial_or_failed_conversion_is_withheld(tmp_path, status):
    converter = FakeConverter(sample_document(), status=status)
    with pytest.raises(PDFExtractionError, match="pdf_conversion_incomplete"):
        load_pdf_documents(sample_pdf(tmp_path), source_name="Book.pdf", converter=converter)


def test_missing_page_provenance_is_withheld(tmp_path):
    with pytest.raises(PDFExtractionError, match="pdf_page_metadata_missing"):
        load_pdf_documents(sample_pdf(tmp_path), source_name="Book.pdf",
                           converter=FakeConverter(sample_document(False)))


def test_empty_document_is_withheld(tmp_path):
    with pytest.raises(PDFExtractionError, match="pdf_text_empty"):
        load_pdf_documents(sample_pdf(tmp_path), source_name="Book.pdf",
                           converter=FakeConverter(DoclingDocument(name="empty")))


def test_upstream_error_is_replaced_with_fixed_code(tmp_path):
    class BrokenConverter:
        def convert(self, **kwargs):
            raise RuntimeError("sensitive upstream details")

    with pytest.raises(PDFExtractionError) as error:
        load_pdf_documents(sample_pdf(tmp_path), source_name="Book.pdf", converter=BrokenConverter())
    assert str(error.value) == "pdf_extraction_failed"


def test_missing_file_is_rejected(tmp_path):
    pdf = DownloadedPDF(path=tmp_path / "missing.pdf", sha256="hash", size_bytes=0)
    with pytest.raises(PDFExtractionError, match="pdf_file_missing"):
        load_pdf_documents(pdf, source_name="Book.pdf")
