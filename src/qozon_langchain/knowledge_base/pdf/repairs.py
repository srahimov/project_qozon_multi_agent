"""Apply explicit, visually reviewed corrections to saved Docling assets."""

import json
from pathlib import Path
import shutil

from docling_core.types.doc import DoclingDocument, RefItem, TableCell, TableData

from qozon_langchain.knowledge_base.pdf.chunking import digest, save_json


def _backup(path: Path, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (digest(str(path.resolve()))[:16] + "-" + path.name)
    if not target.exists():
        shutil.copy2(path, target)


def repair_reviewed_sources(plan: dict, *, backup_directory: Path):
    """Plan rows/caption refs must be checked against originals before invoking."""
    changes = []
    for item in plan["items"]:
        mp = Path(item["manifest"])
        manifest = json.loads(mp.read_text())
        asset = next(a for a in manifest["assets"] if a["element_ref"] == item["element_ref"])
        dp = mp.parent / manifest["document"]
        document = DoclingDocument.load_from_json(dp)
        _backup(mp, backup_directory)
        _backup(dp, backup_directory)
        if asset["kind"] == "table":
            table = document.tables[int(item["element_ref"].split("/")[-1])]
            rows = [["Topic", "Printed page"]] + item["rows"]
            table.data = TableData(num_rows=len(rows), num_cols=2, table_cells=[
                TableCell(text=text, start_row_offset_idx=r, end_row_offset_idx=r + 1,
                          start_col_offset_idx=c, end_col_offset_idx=c + 1,
                          column_header=r == 0, row_header=c == 0 and r > 0)
                for r, row in enumerate(rows) for c, text in enumerate(row)
            ])
            for name in [asset["markdown"], asset["structured_table"]]:
                _backup(mp.parent / name, backup_directory)
            # Compact Markdown preserves the complete reviewed table without export padding.
            markdown = "\n".join("| " + " | ".join(row) + " |" for row in rows)
            markdown = markdown.replace("| Topic | Printed page |\n", "| Topic | Printed page |\n| --- | --- |\n", 1)
            (mp.parent / asset["markdown"]).write_text(markdown + "\n")
            save_json(mp.parent / asset["structured_table"], table.model_dump(mode="json", by_alias=True))
            asset["repair"] = {"method": "visual_transcription", "physical_pages": asset["page_numbers"],
                               "columns": ["Topic", "Printed page"], "reviewed_rows": len(item["rows"])}
        else:
            picture = document.pictures[int(item["element_ref"].split("/")[-1])]
            texts = [document.texts[int(ref.split("/")[-1])] for ref in item["caption_refs"]]
            if any(not set(asset["page_numbers"]).intersection(p.page_no for p in t.prov) for t in texts):
                raise ValueError("caption_page_mismatch")
            picture.captions = [RefItem(cref=t.self_ref) for t in texts]
            for text in texts:
                text.label = "caption"
            asset["caption_refs"] = item["caption_refs"]
            asset["caption"] = picture.caption_text(document)
            # This reviewed picture needs its caption, not the unrelated quotation below it.
            asset["nearby_text"] = []
            asset["repair"] = {"method": "visual_caption_link", "physical_pages": asset["page_numbers"]}
        save_json(dp, document.model_dump(mode="json", by_alias=True))
        save_json(mp, manifest)
        changes.append({"manifest": str(mp), "element_ref": item["element_ref"], "kind": asset["kind"]})
    return changes
