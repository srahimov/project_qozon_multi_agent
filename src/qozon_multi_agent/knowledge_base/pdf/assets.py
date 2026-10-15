"""Preserve local Docling sources before text splitting; no model or cloud calls."""

import json
from pathlib import Path
import shutil
import tempfile

from docling_core.types.doc import DoclingDocument, ImageRefMode, PictureItem, TableItem, TextItem


class PDFAssetError(Exception):
    """Fixed export failures without document text or upstream details."""


def save_pdf_assets(
    document: DoclingDocument, *, destination_dir: Path, source_name: str, document_sha256: str,
) -> Path:
    """Save full pages, detected crops, tables, captions, and structured provenance.

    Each run has a private directory; failures remove only that run's files.
    Crops reflect detected boundaries, not a guarantee of extraction accuracy.
    Full pages remain available for review and as an evidence fallback.
    """
    output_dir = None
    try:
        destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        output_dir = Path(tempfile.mkdtemp(prefix="extraction-", dir=destination_dir))
        records = []
        pages = []
        for page_no, page in sorted(document.pages.items()):
            if page.image is None:
                raise PDFAssetError("pdf_page_image_missing")
            filename = f"page-{page_no}.png"
            page.image.pil_image.save(output_dir / filename, "PNG")
            pages.append({"page_no": page_no, "image": filename})
        if not pages:
            raise PDFAssetError("pdf_page_image_missing")

        items = list(document.iterate_items())
        for position, (element, _level) in enumerate(items):
            if not isinstance(element, (TableItem, PictureItem)):
                continue
            if not element.prov or any(prov.page_no not in document.pages for prov in element.prov):
                raise PDFAssetError("pdf_asset_provenance_missing")
            kind = "table" if isinstance(element, TableItem) else "picture"
            prefix = f"{kind}-{len(records) + 1}"
            element_pages = {prov.page_no for prov in element.prov}
            caption_refs = {ref.cref for ref in element.captions}
            nearby_text = [
                {"element_ref": candidate.self_ref, "text": candidate.text,
                 "page_numbers": sorted({prov.page_no for prov in candidate.prov})}
                for candidate, _ in items[max(0, position - 2):position + 6]
                if isinstance(candidate, TextItem) and candidate.self_ref not in caption_refs
                and element_pages.intersection(prov.page_no for prov in candidate.prov)
            ]
            record = {
                "kind": kind, "element_ref": element.self_ref,
                "page_numbers": sorted({prov.page_no for prov in element.prov}),
                "caption": element.caption_text(document),
                "caption_refs": [ref.cref for ref in element.captions],
                "nearby_text": nearby_text,
                "provenance": [prov.model_dump(mode="json") for prov in element.prov],
                "images": [],
            }
            for index, prov in enumerate(element.prov):
                image = element.get_image(document, prov_index=index)
                if image is None:
                    raise PDFAssetError("pdf_asset_image_missing")
                filename = f"{prefix}-page-{prov.page_no}-{index + 1}.png"
                image.save(output_dir / filename, "PNG")
                record["images"].append({"page_no": prov.page_no, "image": filename})
            if isinstance(element, TableItem):
                filename = f"{prefix}.md"
                (output_dir / filename).write_text(element.export_to_markdown(doc=document), encoding="utf-8")
                record["markdown"] = filename
                filename = f"{prefix}.json"
                (output_dir / filename).write_text(element.model_dump_json(indent=2), encoding="utf-8")
                record["structured_table"] = filename
            records.append(record)

        # Preserve the rich representation, including reading order and text;
        # referenced images avoid flattening everything into one text document.
        document.save_as_json(
            output_dir / "document.json", artifacts_dir=output_dir / "docling-images",
            image_mode=ImageRefMode.REFERENCED,
        )
        manifest = {
            "source": source_name, "document_sha256": document_sha256,
            "document": "document.json", "pages": pages, "assets": records,
            "privacy_status": "unreviewed", "descriptions_generated": False,
        }
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        for path in output_dir.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
        return output_dir / "manifest.json"
    except Exception as error:
        if output_dir is not None:
            shutil.rmtree(output_dir)
        if isinstance(error, PDFAssetError):
            raise
        raise PDFAssetError("pdf_asset_export_failed") from None
