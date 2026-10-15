"""Run an explicitly approved processing plan, checkpointing each Terra result."""

import argparse
import asyncio
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path

from qozon_multi_agent.knowledge_base.pdf.processing import (
    PDFProcessingError, _save, process_pdf_assets, processing_fingerprint,
)
from qozon_multi_agent.security.policies import training_policy


REVIEW_CODES = {
    "source_text_held", "source_contains_secrets", "source_privacy_check_failed",
    "invalid_source_text", "invalid_picture_caption", "picture_description_withheld",
    "table_summary_withheld", "empty_structured_table_text",
    "model_incomplete", "invalid_model_answer",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_processing_job(plan_path: Path, *, table_model, image_model,
                             continue_pending_after_failure: bool = False) -> dict:
    """No automatic provider retries; successful saved items survive interruption.

    Local safety holds are recorded and other independent items continue. A
    provider failure stops the run. An interrupted in-flight item without a
    saved summary requires attention instead of blindly repeating a paid call.
    """
    raw = plan_path.read_bytes()
    plan = json.loads(raw)
    if plan.get("status") != "approved" or not plan.get("approval"):
        raise PDFProcessingError("processing_plan_not_approved")
    if table_model.model_name != plan["table_model"] or image_model.model_name != plan["image_model"]:
        raise PDFProcessingError("processing_model_changed")
    selected = [i for i in plan["items"] if not i["issues"]]
    if len(selected) != plan["planned_calls_before_repairs"]:
        raise PDFProcessingError("invalid_processing_plan")
    # Verify the full approved selection before making any external call.
    for item in selected:
        if processing_fingerprint(Path(item["manifest"]), item["element_ref"]) != item["source_sha256"]:
            raise PDFProcessingError("source_review_required")
    root = Path(plan["output_directory"])
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    progress = root / "progress.json"
    plan_digest = hashlib.sha256(raw).hexdigest()
    with (root / ".job.lock").open("a") as lock:
        os.chmod(root / ".job.lock", 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PDFProcessingError("processing_already_running") from None
        state = json.loads(progress.read_text()) if progress.exists() else {
            "plan_sha256": plan_digest, "started_at": _now(), "items": [],
            "model_calls_started": 0, "excluded_items": [i for i in plan["items"] if i["issues"]],
        }
        if state["plan_sha256"] != plan_digest:
            raise PDFProcessingError("processing_plan_changed")
        state.update(status="running", pid=os.getpid(), total_items=len(selected),
                     table_model=table_model.model_name, image_model=image_model.model_name)

        def checkpoint():
            state["completed_items"] = sum(i["status"] == "complete" for i in state["items"])
            state["review_items"] = sum(i["status"] == "needs_review" for i in state["items"])
            state["failed_items"] = sum(i["status"] == "failed" for i in state["items"])
            state["updated_at"] = _now()
            _save(progress, state)

        checkpoint()
        existing = {i["source_sha256"]: i for i in state["items"]}
        current = None
        consecutive_transport_failures = 0

        def before_provider_call():
            if current.get("provider_call_started"):
                raise PDFProcessingError("interrupted_model_call_needs_attention")
            if state["model_calls_started"] >= len(selected):
                raise PDFProcessingError("approved_call_limit_reached")
            current["provider_call_started"] = True
            state["model_calls_started"] += 1
            checkpoint()

        class CountedTable:
            model_name = table_model.model_name

            async def summarize_table(self, markdown, *, context=""):
                before_provider_call()
                return await table_model.summarize_table(markdown, context=context)

        class CountedImage:
            model_name = image_model.model_name

            async def describe_image(self, image_bytes, *, mime_type, context):
                before_provider_call()
                return await image_model.describe_image(image_bytes, mime_type=mime_type, context=context)

        try:
            for number, item in enumerate(selected, 1):
                current = existing.get(item["source_sha256"])
                if current is None:
                    current = {k: item[k] for k in ("kind", "manifest", "element_ref", "page_numbers", "source_sha256")}
                    current.update(status="running", provider_call_started=False)
                    state["items"].append(current)
                if current["status"] == "needs_review":
                    continue
                if current["status"] == "failed" and continue_pending_after_failure:
                    continue
                if current.get("provider_call_started") and current["status"] != "complete":
                    raise PDFProcessingError("interrupted_model_call_needs_attention")
                completed_prior = current["status"] == "complete"
                # A saved summary is validated and reused by process_pdf_assets.
                # If no summary exists, the counted wrapper prevents a repeat call.
                current["status"] = "running"
                checkpoint()
                try:
                    outputs = await process_pdf_assets(
                        Path(item["manifest"]), reviewed_sources={item["element_ref"]: item["source_sha256"]},
                        table_model=CountedTable(), image_model=CountedImage(),
                        policy=training_policy(), destination_dir=root,
                    )
                    current.update(status="complete", summary=str(outputs[0]), error_code=None)
                    consecutive_transport_failures = 0
                except PDFProcessingError as error:
                    transport_failure = str(error) in {"model_connection_failed", "model_timeout"}
                    if transport_failure and continue_pending_after_failure:
                        current.update(status="failed", error_code=str(error))
                        consecutive_transport_failures += 1
                        checkpoint()
                        if consecutive_transport_failures >= 3:
                            raise
                        # Give the transport time to recover; never repeat this call.
                        await asyncio.sleep(2)
                    elif str(error) not in REVIEW_CODES:
                        raise
                    else:
                        current.update(status="needs_review", error_code=str(error))
                        consecutive_transport_failures = 0
                checkpoint()
                if not completed_prior:
                    print(json.dumps({"item": number, "total": len(selected), "kind": item["kind"],
                                      "page_numbers": item["page_numbers"], "status": current["status"],
                                      "completed": state["completed_items"], "review": state["review_items"]}), flush=True)
            state.update(status="complete_with_errors" if state["failed_items"] else
                         "complete_with_review_items" if state["review_items"] or state["excluded_items"] else "complete",
                         finished_at=_now(), error_code=None)
            checkpoint()
            return state
        except Exception as error:
            code = str(error) if isinstance(error, PDFProcessingError) else "processing_job_failed"
            if current is not None:
                current.update(status="failed", error_code=code)
            state.update(status="needs_attention", error_code=code)
            checkpoint()
            raise PDFProcessingError(code) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("data/pdf-summaries/processing-plan.json"))
    parser.add_argument("--continue-pending-after-failure", action="store_true",
                        help="Continue untouched assets, leaving previous failed calls unrepeated.")
    args = parser.parse_args()
    from qozon_multi_agent.core.config import Settings
    from qozon_multi_agent.llm.adapters import build_openai_image_visualizer, build_openai_table_summarizer
    try:
        plan = json.loads(args.plan.read_text())
        settings = Settings()
        if (settings.table_output_max_tokens != plan["table_output_max_tokens"]
                or settings.image_output_max_tokens != plan["image_output_max_tokens"]):
            raise PDFProcessingError("processing_budget_changed")
        state = asyncio.run(run_processing_job(args.plan,
            table_model=build_openai_table_summarizer(settings), image_model=build_openai_image_visualizer(settings),
            continue_pending_after_failure=args.continue_pending_after_failure))
        print(json.dumps({k: state[k] for k in ("status", "completed_items", "review_items", "failed_items", "model_calls_started")}), flush=True)
    except Exception as error:
        code = str(error) if isinstance(error, PDFProcessingError) else "processing_configuration_failed"
        print(json.dumps({"status": "needs_attention", "error_code": code}), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
