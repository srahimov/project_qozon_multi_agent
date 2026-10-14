"""Publish explicitly reviewed assets; resolve only verified public source URLs."""

import argparse
from collections import Counter
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.pdf.chunking import checked_document_text, digest, local_file, save_json
from qozon_langchain.knowledge_base.pdf.processing import processing_fingerprint


class PublicationError(Exception):
    """Fixed codes only; never expose response bodies or credential headers."""


def _base(settings):
    base = (settings.supabase_url or "").rstrip("/")
    parsed = urlparse(base)
    bucket = settings.supabase_assets_bucket or ""
    if (parsed.scheme != "https" or not re.fullmatch(r"[a-z0-9]+\.supabase\.co", parsed.netloc)
            or parsed.path or parsed.query or parsed.fragment or not re.fullmatch(r"[a-z0-9-]+", bucket)):
        raise PublicationError("invalid_public_storage_configuration")
    return base, bucket


def public_url(settings, key):
    base, bucket = _base(settings)
    if not re.fullmatch(r"[a-f0-9]{64}/[a-f0-9]{64}/[a-f0-9]{64}\.(png|md|json)", key):
        raise PublicationError("invalid_public_asset_key")
    return f"{base}/storage/v1/object/public/{quote(bucket, safe='')}/{key}"


def published_links(settings: Settings, document_id: str, asset_id: str, source_sha256: str):
    """No network calls on queries; changed or unpublished assets have no links."""
    path = settings.rag_publication_manifest
    if not path.exists() or not asset_id:
        return {}
    try:
        saved = json.loads(path.read_text())
        if saved["bucket"] != settings.supabase_assets_bucket or saved["project_url"] != settings.supabase_url.rstrip("/"):
            return {}
        record = saved["assets"].get(asset_id)
        if not record or record["source_sha256"] != source_sha256 or record["document_id"] != document_id:
            return {}
        links = {}
        for entry in record["files"]:
            if not entry["verified_public"] or not entry["key"].startswith(f"{document_id}/{asset_id}/"):
                return {}
            role = entry["role"]
            if role not in {"url", "image_url", "structured_url"}:
                return {}
            links[role] = public_url(settings, entry["key"])
        return links
    except Exception:
        return {}


def _request(client, method, url, *, progress=None, **kwargs):
    """Bound transient failures; content-addressed POSTs never overwrite objects."""
    for attempt in range(3):
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                return response
            reason = "transient_http_status"
        except httpx.RequestError as error:
            if attempt == 2:
                raise
            reason = type(error).__name__
        if progress:
            progress({"status": "request_retry", "method": method, "attempt": attempt + 2, "reason": reason})
        time.sleep(attempt + 1)


def publish_assets(settings: Settings, selections: list[dict], *, authenticated=None, anonymous=None, progress=None):
    """Hash approval covers pixels and text. Uploads never overwrite existing objects.

    Reuse matching objects and verify every public response byte-for-byte without
    credentials before saving its URLs. Only PNG crops and table MD/JSON are sent.
    """
    base, bucket = _base(settings)
    if not settings.supabase_secret_key:
        raise PublicationError("storage_key_not_configured")
    # Check every approval before starting the first external upload.
    for selection in selections:
        if processing_fingerprint(Path(selection["manifest"]), selection["element_ref"]) != selection["source_sha256"]:
            raise PublicationError("publication_source_review_required")
    owned_auth, owned_public = authenticated is None, anonymous is None
    # Avoid recycling stale proxy/server connections on this long batch job.
    limits = httpx.Limits(max_keepalive_connections=0)
    authenticated = authenticated or httpx.Client(timeout=30, follow_redirects=False, limits=limits)
    anonymous = anonymous or httpx.Client(timeout=30, follow_redirects=False, limits=limits)
    headers = {"apikey": settings.supabase_secret_key.get_secret_value()}
    try:
        response = _request(authenticated, "GET", f"{base}/storage/v1/bucket/{bucket}", headers=headers, progress=progress)
        if response.status_code != 200 or response.json().get("public") is not True:
            raise PublicationError("public_bucket_not_verified")
        registry = (json.loads(settings.rag_publication_manifest.read_text())
                    if settings.rag_publication_manifest.exists() else
                    {"bucket": bucket, "project_url": base, "assets": {}})
        if registry["bucket"] != bucket or registry["project_url"] != base:
            raise PublicationError("publication_destination_changed")
        for selection in selections:
            mp = Path(selection["manifest"]).resolve()
            manifest = json.loads(mp.read_text())
            asset = next(a for a in manifest["assets"] if a["element_ref"] == selection["element_ref"])
            if len(asset["images"]) != 1:
                raise PublicationError("publication_requires_single_crop_review")
            asset_id = digest([manifest["document_sha256"], str(mp), selection["element_ref"]])
            sources = [("image_url" if asset["kind"] == "table" else "url", asset["images"][0]["image"], "image/png")]
            if asset["kind"] == "table":
                sources += [("url", asset["markdown"], "text/markdown"),
                            ("structured_url", asset["structured_table"], "application/json")]
            files = []
            for role, name, mime in sources:
                path = local_file(mp.parent, name)
                payload = path.read_bytes()
                if not 0 < len(payload) <= 6 * 1024 * 1024:
                    raise PublicationError("publication_file_size_invalid")
                if mime != "image/png":
                    checked, _, _ = checked_document_text(payload.decode())
                    if checked != payload.decode().strip():
                        # Whitespace normalization is not required for originals.
                        if checked != payload.decode():
                            raise PublicationError("publication_text_needs_review")
                elif not payload.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise PublicationError("publication_image_invalid")
                sha = hashlib.sha256(payload).hexdigest()
                key = f"{manifest['document_sha256']}/{asset_id}/{sha}{path.suffix}"
                url = public_url(settings, key)
                public = _request(anonymous, "GET", url, progress=progress)
                if public.status_code != 200:
                    if public.status_code not in {400, 404}:
                        raise PublicationError("public_asset_check_failed")
                    result = _request(authenticated, "POST", f"{base}/storage/v1/object/{bucket}/{key}", content=payload,
                                      headers={**headers, "Content-Type": mime, "x-upsert": "false"}, progress=progress)
                    if result.status_code not in {200, 201, 409}:
                        raise PublicationError("asset_upload_failed")
                    public = _request(anonymous, "GET", url, progress=progress)
                if public.status_code != 200 or public.content != payload:
                    raise PublicationError("public_asset_verification_failed")
                files.append({"role": role, "key": key, "sha256": sha, "mime_type": mime,
                              "size_bytes": len(payload), "verified_public": True})
            registry["assets"][asset_id] = {"document_id": manifest["document_sha256"],
                "source_sha256": selection["source_sha256"], "physical_pages": asset["page_numbers"], "files": files}
            save_json(settings.rag_publication_manifest, registry)
            if progress:
                progress({"status": "asset_verified", "physical_pages": asset["page_numbers"],
                          "source_assets": len(registry["assets"]),
                          "public_files": sum(len(a["files"]) for a in registry["assets"].values())})
        return registry
    except PublicationError:
        raise
    except httpx.TimeoutException:
        raise PublicationError("storage_timeout") from None
    except httpx.RequestError:
        raise PublicationError("storage_connection_failed") from None
    except (OSError, UnicodeError):
        raise PublicationError("publication_source_read_failed") from None
    except ValueError:
        raise PublicationError("storage_response_invalid") from None
    except Exception:
        raise PublicationError("asset_publication_failed") from None
    finally:
        if owned_auth:
            authenticated.close()
        if owned_public:
            anonymous.close()


def inventory(settings, progress, summaries, review):
    from PIL import Image

    if progress["status"] != "complete" or progress["completed_pages"] != progress["total_pages"]:
        raise ValueError("extraction_incomplete")
    entries = {(str(Path(e["manifest"]).resolve()), e["element_ref"]): e for e in summaries["entries"]}
    reviewed = {(str(Path(e["manifest"]).resolve()), e["element_ref"]): e for e in review["items"]}
    rows, selections = [], []
    for batch in progress["batches"]:
        mp = Path(batch["manifest"]).resolve()
        manifest = json.loads(mp.read_text())
        if manifest["document_sha256"] != progress["document_sha256"]:
            raise ValueError("mixed_source_documents")
        document = json.loads(local_file(mp.parent, manifest["document"]).read_text())
        for asset in manifest["assets"]:
            ref = asset["element_ref"]
            identity = digest([manifest["document_sha256"], str(mp), ref])
            fingerprint = processing_fingerprint(mp, ref)
            row = dict(asset_id=identity, manifest=str(mp), element_ref=ref, kind=asset["kind"],
                       physical_pages=asset["page_numbers"], source_sha256=fingerprint,
                       caption=asset.get("caption", ""), files=[], issues=[], quality_notes=[])
            if len(asset["images"]) != 1:
                row["issues"].append("multiple_crops_require_review")
            review_item = reviewed.get((str(mp), ref))
            if not review_item or review_item["source_sha256"] != fingerprint:
                row["issues"].append("visual_source_review_missing_or_stale")
            else:
                row["quality_notes"] = review_item.get("quality_notes", [])
            linked = []
            for caption_ref in asset.get("caption_refs", []):
                section, number = caption_ref.removeprefix("#/").split("/")
                item = document[section][int(number)]
                pages = {p["page_no"] for p in item.get("prov", [])}
                if not pages or not pages <= set(asset["page_numbers"]):
                    row["issues"].append("caption_page_mismatch")
                linked.append(item.get("text", ""))
            if asset.get("caption") and "".join(linked) != asset["caption"]:
                row["issues"].append("caption_reference_text_mismatch")
            sources = [("image_url" if asset["kind"] == "table" else "url", i["image"], "image/png")
                       for i in asset["images"]]
            if asset["kind"] == "table":
                table = json.loads(local_file(mp.parent, asset["structured_table"]).read_text())["data"]
                row["table_rows"], row["table_columns"] = table.get("num_rows"), table.get("num_cols")
                if not any(c.get("text", "").strip() for c in table["table_cells"]):
                    row["issues"].append("empty_structured_table_text")
                sources += [("url", asset["markdown"], "text/markdown"),
                            ("structured_url", asset["structured_table"], "application/json")]
            for role, name, mime in sources:
                path = local_file(mp.parent, name)
                raw = path.read_bytes()
                file = dict(path=str(path), role=role, mime_type=mime, size_bytes=len(raw),
                            sha256=hashlib.sha256(raw).hexdigest())
                if not 0 < len(raw) <= 6 * 1024 * 1024:
                    row["issues"].append("publication_file_size_invalid")
                if mime == "image/png":
                    with Image.open(path) as image:
                        file["dimensions"] = list(image.size)
                        image.verify()
                    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                        row["issues"].append("publication_image_invalid")
                else:
                    text = raw.decode()
                    checked, _, _ = checked_document_text(text)
                    if checked != text and checked != text.strip():
                        row["issues"].append("publication_text_needs_review")
                row["files"].append(file)
            entry = entries.get((str(mp), ref))
            if not entry:
                row["issues"].append("approved_summary_missing")
            else:
                saved = json.loads(Path(entry["summary_file"]).read_text())
                if (entry["source_sha256"] != fingerprint
                        or saved["processing_identity"]["source_sha256"] != fingerprint
                        or saved.get("source_approval") != "explicit_source_fingerprint_approval"
                        or saved["document_sha256"] != manifest["document_sha256"]
                        or saved["page_numbers"] != asset["page_numbers"]):
                    row["issues"].append("summary_source_approval_mismatch")
                expected_kind = "table_summary" if asset["kind"] == "table" else "picture_description"
                if saved.get("kind") != expected_kind:
                    row["issues"].append("summary_asset_kind_mismatch")
            if row["issues"]:
                row["status"] = "excluded"
            elif published_links(settings, manifest["document_sha256"], identity, fingerprint):
                row["status"] = "already_published"
            else:
                row["status"] = "ready"
                selections.append({"manifest": str(mp), "element_ref": ref, "source_sha256": fingerprint})
            rows.append(row)
    ready = [r for r in rows if r["status"] == "ready"]
    return {"bucket": settings.supabase_assets_bucket, "document_id": progress["document_sha256"],
            "counts": dict(Counter(r["status"] for r in rows)),
            "ready_assets_by_kind": dict(Counter(r["kind"] for r in ready)),
            "ready_files": sum(len(r["files"]) for r in ready),
            "ready_bytes": sum(f["size_bytes"] for r in ready for f in r["files"]),
            "review_scope": review["review_scope"], "factually_verified": False, "assets": rows}, selections


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write-plan", action="store_true")
    action.add_argument("--publish", action="store_true", help="Upload only the fingerprint-approved plan; this makes Storage calls.")
    parser.add_argument("--plan", type=Path, default=Path("data/source-publication/publication-plan.json"))
    args = parser.parse_args()
    settings = Settings()
    if args.publish:
        plan = json.loads(args.plan.read_text())
        if not plan.get("approval") or plan.get("public_upload_approved") is False:
            raise PublicationError("publication_not_approved")
        saved = publish_assets(settings, plan["items"], progress=lambda event: print(json.dumps(event), flush=True))
        print(json.dumps({"status": "published_and_verified", "bucket": saved["bucket"],
                          "source_assets": len(saved["assets"]),
                          "public_files": sum(len(a["files"]) for a in saved["assets"].values())}))
        return
    progress = json.loads(Path("data/pdf-assets/full-book/progress.json").read_text())
    summaries = json.loads(Path("data/pdf-summaries/summary-index.json").read_text())
    review = json.loads(Path("data/source-publication/review/visual-review.json").read_text())
    report, items = inventory(settings, progress, summaries, review)
    save_json(Path("data/source-publication/inventory.json"), report)
    if args.write_plan:
        path = args.plan
        previous = json.loads(path.read_text()) if path.exists() else {}
        approved = {(i["manifest"], i["element_ref"], i["source_sha256"]) for i in previous.get("items", [])}
        covered = (previous.get("public_upload_approved") is True and previous.get("bucket") == report["bucket"]
                   and all((i["manifest"], i["element_ref"], i["source_sha256"]) in approved for i in items))
        save_json(path, {
            "approval": previous.get("approval") if covered else None,
            "public_upload_approved": bool(covered), "bucket": report["bucket"],
            "review_report": str(Path("data/source-publication/inventory.json").resolve()),
            "items": items,
        })
    print(json.dumps({k: v for k, v in report.items() if k != "assets"}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        code = str(error) if isinstance(error, PublicationError) else "publication_failed"
        print(json.dumps({"status": "failed", "code": code}))
        raise SystemExit(1) from None
