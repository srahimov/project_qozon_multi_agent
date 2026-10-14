import json
from pathlib import Path

from PIL import Image
import pytest

from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.pdf.processing import processing_fingerprint


from qozon_langchain.knowledge_base.pdf import publication as module


def fixture(tmp_path):
    Image.new("RGB", (10, 10), "blue").save(tmp_path / "picture.png")
    (tmp_path / "document.json").write_text(json.dumps({"texts": [
        {"text": "Synthetic source picture.", "prov": [{"page_no": 1}]}]}))
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps({"document_sha256": "a" * 64, "document": "document.json", "assets": [
        {"kind": "picture", "element_ref": "#/pictures/0", "page_numbers": [1],
         "caption": "Synthetic source picture.", "caption_refs": ["#/texts/0"], "images": [{"image": "picture.png"}]}]}))
    sha = processing_fingerprint(mp, "#/pictures/0")
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"kind": "picture_description", "document_sha256": "a" * 64,
        "source_approval": "explicit_source_fingerprint_approval", "processing_identity": {"source_sha256": sha},
        "page_numbers": [1]}))
    settings = Settings(_env_file=None, supabase_url="https://synthetic.supabase.co",
                        supabase_assets_bucket="public-assets", rag_publication_manifest=tmp_path / "publication.json")
    progress = {"status": "complete", "completed_pages": 1, "total_pages": 1,
                "document_sha256": "a" * 64, "batches": [{"manifest": str(mp)}]}
    summaries = {"entries": [{"manifest": str(mp), "element_ref": "#/pictures/0", "source_sha256": sha,
                              "summary_file": str(summary)}]}
    review = {"review_scope": "Synthetic crop review.", "items": [{"manifest": str(mp), "element_ref": "#/pictures/0",
              "source_sha256": sha, "quality_notes": []}]}
    return settings, progress, summaries, review


def test_inventory_selects_only_fingerprint_reviewed_sources(tmp_path):
    args = fixture(tmp_path)
    report, selections = module.inventory(*args)
    assert len(selections) == report["ready_files"] == 1
    assert report["counts"] == {"ready": 1}
    args[3]["items"][0]["source_sha256"] = "changed"
    report, selections = module.inventory(*args)
    assert not selections
    assert "visual_source_review_missing_or_stale" in report["assets"][0]["issues"]


def test_wrong_caption_page_prevents_selection(tmp_path):
    args = fixture(tmp_path)
    dp = tmp_path / "document.json"
    document = json.loads(dp.read_text())
    document["texts"][0]["prov"][0]["page_no"] = 2
    dp.write_text(json.dumps(document))
    report, selections = module.inventory(*args)
    assert not selections
    assert "caption_page_mismatch" in report["assets"][0]["issues"]


def test_summary_without_source_approval_is_not_publishable(tmp_path):
    args = fixture(tmp_path)
    path = Path(args[2]["entries"][0]["summary_file"])
    record = json.loads(path.read_text())
    record["source_approval"] = "unreviewed"
    path.write_text(json.dumps(record))
    report, selections = module.inventory(*args)
    assert not selections
    assert "summary_source_approval_mismatch" in report["assets"][0]["issues"]


@pytest.mark.parametrize("plan", [{"items": []}, {"approval": "synthetic review", "public_upload_approved": False, "items": []}])
def test_publication_cli_holds_unapproved_plan_without_upload(tmp_path, monkeypatch, plan):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    monkeypatch.setattr("sys.argv", ["publication", "--publish", "--plan", str(path)])
    monkeypatch.setattr(module, "Settings", lambda: None)
    def forbidden(*args, **kwargs):
        pytest.fail("Unapproved plan must not reach Storage")
    monkeypatch.setattr(module, "publish_assets", forbidden)
    with pytest.raises(module.PublicationError, match="publication_not_approved"):
        module.main()


def test_publication_cli_requires_one_action(monkeypatch):
    monkeypatch.setattr("sys.argv", ["publication", "--write-plan", "--publish"])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
