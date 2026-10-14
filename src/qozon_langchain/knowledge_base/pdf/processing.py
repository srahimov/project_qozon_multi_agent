"""Resumable Terra ingestion for explicitly reviewed table and picture assets.

Call once per extraction manifest. No import-time calls, automatic source approval,
upload, chunking, or embedding. Saved successful results are reused when source,
model, prompt version, and privacy policy are unchanged. A provider call interrupted
before its result is saved cannot be guaranteed to run exactly once.
"""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Protocol

from qozon_langchain.security.output_gate import check_output
from qozon_langchain.security.pii import check_pii
from qozon_langchain.security.policies import PrivacyPolicy
from qozon_langchain.security.screening import screen_document_text
from qozon_langchain.security.secrets import check_secrets
from qozon_langchain.services.question_service import ModelInvocationError


DEFAULT_SUMMARIES_DIR = Path("data/pdf-summaries")


class PDFProcessingError(Exception):
    """Fixed error codes without source content or provider details."""


class TableSummaryModel(Protocol):
    model_name: str

    async def summarize_table(self, table_markdown: str, *, context: str = "") -> str:
        ...


class ImageDescriptionModel(Protocol):
    model_name: str

    async def describe_image(self, image_bytes: bytes, *, mime_type: str, context: str) -> str:
        ...


def _asset_file(root: Path, relative: str) -> Path:
    path = Path(relative)
    resolved = (root / path).resolve()
    if path.is_absolute() or not resolved.is_relative_to(root):
        raise PDFProcessingError("invalid_asset_path")
    if not resolved.is_file() or resolved.stat().st_size > 10 * 1024 * 1024:
        raise PDFProcessingError("invalid_asset_file")
    return resolved


def _source(manifest_path: Path, element_ref: str) -> tuple[dict, dict, str]:
    if manifest_path.stat().st_size > 1024 * 1024:
        raise PDFProcessingError("invalid_asset_manifest")
    manifest = json.loads(manifest_path.read_text())
    matches = [a for a in manifest["assets"] if a["element_ref"] == element_ref
               and a["kind"] in {"table", "picture"}]
    if len(matches) != 1:
        raise PDFProcessingError("invalid_asset_selection")
    asset = matches[0]
    root = manifest_path.parent.resolve()
    # Include captions, nearby text, provenance, and actual file bytes in approval.
    digest = hashlib.sha256(json.dumps({
        "asset": asset, "document_sha256": manifest["document_sha256"],
    }, sort_keys=True).encode())
    paths = [i["image"] for i in asset["images"]]
    if asset["kind"] == "table":
        paths += [asset["markdown"], asset["structured_table"]]
    for relative in paths:
        digest.update(relative.encode())
        digest.update(_asset_file(root, relative).read_bytes())
    return manifest, asset, digest.hexdigest()


def processing_fingerprint(manifest_path: Path, element_ref: str) -> str:
    """Identify the exact source to review; computing a hash does not approve it."""
    try:
        return _source(manifest_path, element_ref)[2]
    except Exception as error:
        if isinstance(error, PDFProcessingError):
            raise
        raise PDFProcessingError("invalid_processing_source") from None


def _checked_text(text: str, policy: PrivacyPolicy, *, limit: int) -> str:
    if not isinstance(text, str) or len(text) > limit:
        raise PDFProcessingError("invalid_source_text")
    if screen_document_text(text).decision != "allow":
        raise PDFProcessingError("source_text_held")
    if check_secrets(text).decision != "allow":
        raise PDFProcessingError("source_contains_secrets")
    result = check_pii(text, policy=policy, direction="input")
    if result.decision == "block" or result.text is None:
        raise PDFProcessingError("source_privacy_check_failed")
    if check_secrets(result.text).decision != "allow":
        raise PDFProcessingError("source_privacy_check_failed")
    return result.text


def _save(path: Path, record: dict) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".processing-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(record, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


async def process_pdf_assets(
    manifest_path: Path, *, reviewed_sources: dict[str, str],
    table_model: TableSummaryModel, image_model: ImageDescriptionModel,
    policy: PrivacyPolicy, destination_dir: Path = DEFAULT_SUMMARIES_DIR,
) -> list[Path]:
    """Process selected reviewed assets sequentially, preserving source references.

    reviewed_sources maps element_ref to its reviewed processing_fingerprint.
    Picture review must cover pixels AND caption/nearby text. An empty selection
    makes no model calls. Empty structured tables stop for repair before calling
    the model. On failure, earlier saved results survive for a later resume.
    By default, saves in data/pdf-summaries; run from project_Qozon as with .env.
    """
    destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = destination_dir / ".processing.lock"
    results = []
    try:
        with lock_path.open("a") as lock:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PDFProcessingError("processing_already_running") from None
            for ref, approved_digest in reviewed_sources.items():
                manifest, asset, digest = _source(manifest_path, ref)
                if digest != approved_digest:
                    raise PDFProcessingError("source_review_required")
                model = table_model if asset["kind"] == "table" else image_model
                identity = {
                    "source_sha256": digest, "model": model.model_name,
                    "policy": repr(policy), "processing_version": "v1",
                }
                key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
                saved = destination_dir / f"summary-{key}.json"
                if saved.exists():
                    record = json.loads(saved.read_text())
                    if record.get("processing_identity") != identity or not record.get("description", "").strip():
                        raise PDFProcessingError("invalid_saved_summary")
                    results.append(saved)
                    continue
                root = manifest_path.parent.resolve()
                nearby = "\n".join(item["text"] for item in asset.get("nearby_text", []))
                if asset["kind"] == "picture":
                    if len(asset["images"]) != 1:
                        raise PDFProcessingError("picture_requires_single_crop_review")
                    image_path = asset["images"][0]["image"]
                    image = _asset_file(root, image_path).read_bytes()
                    caption = _checked_text(asset["caption"], policy, limit=8_000)
                    context = _checked_text(caption + "\n\nNearby source text:\n" + nearby, policy, limit=8_000) if nearby else caption
                    text = await image_model.describe_image(image, mime_type="image/png", context=context)
                    record = {"kind": "picture_description", "image_index": 0,
                              "image": image_path, "image_sha256": hashlib.sha256(image).hexdigest(),
                              "caption": caption,
                              "context": context, "prompt_version": "image_description_v1",
                              "text_privacy_policy": policy.name}
                else:
                    table = json.loads(_asset_file(root, asset["structured_table"]).read_text())["data"]
                    if not any(c.get("text", "").strip() for c in table["table_cells"]):
                        raise PDFProcessingError("empty_structured_table_text")
                    markdown = _checked_text(_asset_file(root, asset["markdown"]).read_text(), policy, limit=100_000)
                    context = _checked_text(asset["caption"] + "\n" + nearby, policy, limit=8_000)
                    text = await table_model.summarize_table(markdown, context=context)
                    record = {"kind": "table_summary"}
                checked = check_output(text, policy=policy)
                if checked.decision != "allow" or checked.text is None:
                    code = "table_summary_withheld" if asset["kind"] == "table" else "picture_description_withheld"
                    raise PDFProcessingError(code)
                record.update({
                    "description": checked.text, "model": model.model_name, "factually_verified": False,
                    "processing_identity": identity, "element_ref": ref,
                    "page_numbers": asset["page_numbers"],
                    "document_sha256": manifest["document_sha256"],
                    "source": manifest["source"], "manifest": str(manifest_path.resolve()),
                    "original_images": [str(_asset_file(root, i["image"])) for i in asset["images"]],
                    "original_table": str(_asset_file(root, asset["structured_table"])) if asset["kind"] == "table" else None,
                    "original_markdown": str(_asset_file(root, asset["markdown"])) if asset["kind"] == "table" else None,
                    "source_approval": "explicit_source_fingerprint_approval",
                    "visual_privacy_verified": False,
                })
                if asset["kind"] == "picture":
                    record["pixel_review"] = "explicit_source_fingerprint_approval"
                _save(saved, record)
                results.append(saved)
        return results
    except Exception as error:
        if isinstance(error, PDFProcessingError):
            raise
        if isinstance(error, ModelInvocationError):
            raise PDFProcessingError(error.code) from None
        raise PDFProcessingError("asset_processing_failed") from None
