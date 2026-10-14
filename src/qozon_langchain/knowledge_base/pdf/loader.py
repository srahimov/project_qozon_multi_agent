"""Extract PDF text through LangChain's DoclingLoader, retaining page references.

Extracted documents are untrusted, unredacted source material. They must pass
document privacy/content checks before embedding or use in a model prompt.
No Supabase upload, embedding, vector indexing, or LLM calls happen here.
"""

from pathlib import Path
import shutil

from docling.chunking import HierarchicalChunker
from docling.datamodel.base_models import ConversionStatus, InputFormat
from langchain_core.documents import Document
from langchain_docling.loader import ConversionBackend, DoclingLoader, ExportType

from qozon_langchain.knowledge_base.pdf.downloader import DownloadedPDF
from qozon_langchain.knowledge_base.pdf.assets import PDFAssetError, save_pdf_assets


class PDFExtractionError(Exception):
    """A fixed extraction error without source text or upstream details."""


class _CheckedConverter:
    """Do not silently accept partial Docling conversion results."""

    def __init__(
        self, converter: ConversionBackend, *, assets_dir: Path | None = None,
        source_name: str = "", document_sha256: str = "",
    ) -> None:
        self.converter = converter
        self.assets_dir = assets_dir
        self.source_name = source_name
        self.document_sha256 = document_sha256
        self.asset_manifest: Path | None = None

    def convert(self, **kwargs):
        result = self.converter.convert(**kwargs)
        if result.status != ConversionStatus.SUCCESS:
            raise PDFExtractionError("pdf_conversion_incomplete")
        if self.assets_dir is not None:
            self.asset_manifest = save_pdf_assets(
                result.document, destination_dir=self.assets_dir,
                source_name=self.source_name, document_sha256=self.document_sha256,
            )
        return result


def load_pdf_documents(
    pdf: DownloadedPDF,
    *,
    source_name: str,
    page_range: tuple[int, int] = (1, 3),
    do_ocr: bool = True,
    assets_dir: Path | None = None,
    converter: ConversionBackend | None = None,
    allow_empty_text: bool = False,
) -> list[Document]:
    """Read a selected, inclusive range of 1-based PDF pages.

    Start with three sample pages. Page numbers mean physical PDF pages,
    which may differ from printed page labels. Docling's hierarchical export
    retains document blocks and their provenance without a tokenizer-based
    chunk size; LangChain recursive splitting will be a separate next step.

    Lazy loading yields blocks after conversion, not incremental PDF downloads.
    This function collects them so callers get either a complete result or an
    error. Conversion may download local OCR/layout model weights on first use.
    Pass assets_dir to preserve full pages, tables, pictures, and captions before
    chunk export. This local export does not call the description models.
    Full-book jobs may retain blank pages by setting allow_empty_text with an
    assets directory; the page images remain required even when text is absent.
    """
    if (
        not isinstance(page_range, tuple) or len(page_range) != 2
        or any(type(number) is not int for number in page_range)
        or page_range[0] < 1 or page_range[1] < page_range[0]
    ):
        raise PDFExtractionError("invalid_page_range")
    if not isinstance(source_name, str) or not source_name.strip():
        raise PDFExtractionError("invalid_source_name")
    if not isinstance(pdf.path, Path) or not pdf.path.is_file():
        raise PDFExtractionError("pdf_file_missing")
    if assets_dir is not None and not isinstance(assets_dir, Path):
        raise PDFExtractionError("invalid_asset_directory")
    if type(allow_empty_text) is not bool or (allow_empty_text and assets_dir is None):
        raise PDFExtractionError("invalid_empty_text_policy")

    checked_converter = None
    try:
        if converter is None:
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption

            options = PdfPipelineOptions(
                do_ocr=do_ocr,
                do_table_structure=True,
                generate_page_images=True,
                generate_picture_images=True,
                images_scale=2.0,
                do_picture_description=False,
                enable_remote_services=False,
            )
            converter = DocumentConverter(
                allowed_formats=[InputFormat.PDF],
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
            )
        checked_converter = _CheckedConverter(
            converter, assets_dir=assets_dir, source_name=source_name, document_sha256=pdf.sha256,
        )
        loader = DoclingLoader(
            file_path=str(pdf.path),
            converter=checked_converter,
            convert_kwargs={
                "page_range": page_range,
                "max_file_size": 128 * 1024 * 1024,
                "raises_on_error": True,
            },
            export_type=ExportType.DOC_CHUNKS,
            chunker=HierarchicalChunker(),
        )
        documents = []
        for document in loader.lazy_load():
            if not document.page_content.strip():
                continue
            provenance = document.metadata["dl_meta"]["doc_items"]
            pages = sorted({
                entry["page_no"] for item in provenance for entry in item.get("prov", [])
                if type(entry.get("page_no")) is int
            })
            if not pages or any(not page_range[0] <= page <= page_range[1] for page in pages):
                raise PDFExtractionError("pdf_page_metadata_missing")
            document.metadata.update(
                source=source_name,
                document_sha256=pdf.sha256,
                page_numbers=pages,
            )
            if checked_converter.asset_manifest is not None:
                document.metadata.update(
                    asset_manifest=str(checked_converter.asset_manifest),
                    element_refs=[item["self_ref"] for item in provenance],
                )
            documents.append(document)
        if not documents and not allow_empty_text:
            raise PDFExtractionError("pdf_text_empty")
        return documents
    except (PDFExtractionError, PDFAssetError):
        if checked_converter is not None and checked_converter.asset_manifest is not None:
            shutil.rmtree(checked_converter.asset_manifest.parent)
        raise
    except Exception:
        if checked_converter is not None and checked_converter.asset_manifest is not None:
            shutil.rmtree(checked_converter.asset_manifest.parent)
        raise PDFExtractionError("pdf_extraction_failed") from None
