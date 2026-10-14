import json

from docling_core.types.doc import DoclingDocument

from qozon_langchain.knowledge_base.pdf.assets import save_pdf_assets
from qozon_langchain.knowledge_base.pdf.chunking import ordinary_items
from qozon_langchain.knowledge_base.pdf.repairs import repair_reviewed_sources
from .test_assets import rich_document


def test_repair_keeps_docling_references_and_correct_grid(tmp_path):
    mp = save_pdf_assets(rich_document(), destination_dir=tmp_path / "assets",
                         source_name="synthetic.pdf", document_sha256="a" * 64)
    manifest = json.loads(mp.read_text())
    table = next(a for a in manifest["assets"] if a["kind"] == "table")
    picture = next(a for a in manifest["assets"] if a["kind"] == "picture")
    plan = {"items": [
        {"manifest": str(mp), "element_ref": table["element_ref"], "rows": [["Apples", "12"]]},
        {"manifest": str(mp), "element_ref": picture["element_ref"], "caption_refs": picture["caption_refs"]},
    ]}
    repair_reviewed_sources(plan, backup_directory=tmp_path / "backup")
    docpath = mp.parent / manifest["document"]
    doc = DoclingDocument.load_from_json(docpath)
    assert [[c.text for c in row] for row in doc.tables[0].data.grid] == [["Topic", "Printed page"], ["Apples", "12"]]
    assert list(ordinary_items(json.loads(docpath.read_text())))
    assert [r.cref for r in doc.pictures[0].captions] == picture["caption_refs"]
    assert "Apples" in (mp.parent / table["markdown"]).read_text()
    assert len(list((tmp_path / "backup").iterdir())) == 4
