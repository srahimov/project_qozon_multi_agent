"""Offline approved-plan execution, resume, and failure checkpoint checks."""

import asyncio
import json

import pytest

from qozon_langchain.knowledge_base.pdf.processing import PDFProcessingError, processing_fingerprint
from qozon_langchain.knowledge_base.pdf.processing_job import run_processing_job
from qozon_langchain.services.question_service import ModelInvocationError
from .test_processing import FakeImageModel
from .test_processing import FakeTableModel, source


def plan_source(tmp_path, picture_caption="A blue square."):
    items = []
    for kind in ("picture", "table"):
        folder = tmp_path / kind
        folder.mkdir()
        path, ref = source(folder, kind, picture_caption if kind == "picture" else "A table value.")
        items.append({"kind": kind, "manifest": str(path), "element_ref": ref,
                      "source_sha256": processing_fingerprint(path, ref), "page_numbers": [1], "issues": []})
    plan = {"status": "approved", "approval": "synthetic-user-approval",
            "table_model": FakeTableModel.model_name, "image_model": FakeImageModel.model_name,
            "planned_calls_before_repairs": 2, "output_directory": str(tmp_path / "results"), "items": items}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    return path


def run(path, table, image):
    return asyncio.run(run_processing_job(path, table_model=table, image_model=image))


def test_complete_checkpoint_and_resume_do_not_repeat_paid_calls(tmp_path):
    path = plan_source(tmp_path)
    table, image = FakeTableModel(), FakeImageModel()
    state = run(path, table, image)
    assert state["status"] == "complete" and state["completed_items"] == 2
    assert state["model_calls_started"] == 2
    assert run(path, table, image)["completed_items"] == 2
    assert len(table.calls) == len(image.calls) == 1


def test_unapproved_plan_never_calls_models(tmp_path):
    path = plan_source(tmp_path)
    plan = json.loads(path.read_text()); plan["status"] = "prepared"
    path.write_text(json.dumps(plan))
    table, image = FakeTableModel(), FakeImageModel()
    with pytest.raises(PDFProcessingError, match="processing_plan_not_approved"):
        run(path, table, image)
    assert table.calls == image.calls == []


def test_local_hold_does_not_stop_other_independent_assets(tmp_path):
    path = plan_source(tmp_path, "password=synthetic-secret-value")
    table, image = FakeTableModel(), FakeImageModel()
    state = run(path, table, image)
    assert state["status"] == "complete_with_review_items"
    assert state["review_items"] == state["completed_items"] == 1
    assert state["model_calls_started"] == 1
    assert image.calls == [] and len(table.calls) == 1


def test_provider_failure_stops_and_resume_does_not_blindly_repeat(tmp_path):
    class FailedImage(FakeImageModel):
        async def describe_image(self, *args, **kwargs):
            self.calls.append(True)
            raise ModelInvocationError("model_timeout")
    path = plan_source(tmp_path)
    table, image = FakeTableModel(), FailedImage()
    with pytest.raises(PDFProcessingError, match="model_timeout"):
        run(path, table, image)
    state = json.loads((tmp_path / "results/progress.json").read_text())
    assert state["status"] == "needs_attention" and state["model_calls_started"] == 1
    with pytest.raises(PDFProcessingError, match="interrupted_model_call_needs_attention"):
        run(path, table, image)
    assert len(image.calls) == 1 and table.calls == []


def test_all_source_fingerprints_checked_before_any_call(tmp_path):
    path = plan_source(tmp_path)
    plan = json.loads(path.read_text());plan["items"][1]["source_sha256"] = "changed"
    path.write_text(json.dumps(plan))
    table, image = FakeTableModel(), FakeImageModel()
    with pytest.raises(PDFProcessingError, match="source_review_required"):
        run(path, table, image)
    assert table.calls == image.calls == []


def test_explicit_continue_processes_pending_assets_without_retrying_failed_call(tmp_path):
    class FailedImage(FakeImageModel):
        async def describe_image(self, *args, **kwargs):
            self.calls.append(True)
            raise ModelInvocationError("model_connection_failed")
    path = plan_source(tmp_path)
    table, image = FakeTableModel(), FailedImage()
    with pytest.raises(PDFProcessingError, match="model_connection_failed"):
        run(path, table, image)
    state = asyncio.run(run_processing_job(path, table_model=table, image_model=image,
                                         continue_pending_after_failure=True))
    assert state["status"] == "complete_with_errors"
    assert state["completed_items"] == state["failed_items"] == 1
    assert state["model_calls_started"] == 2
    assert len(image.calls) == len(table.calls) == 1


def test_incomplete_provider_output_is_withheld_and_other_items_continue(tmp_path):
    class IncompleteImage(FakeImageModel):
        async def describe_image(self, *args, **kwargs):
            self.calls.append(True)
            raise ModelInvocationError("model_incomplete")
    path = plan_source(tmp_path)
    table, image = FakeTableModel(), IncompleteImage()
    state = run(path, table, image)
    assert state["status"] == "complete_with_review_items"
    assert state["completed_items"] == state["review_items"] == 1
    assert state["items"][0]["error_code"] == "model_incomplete"
    assert len(image.calls) == len(table.calls) == 1


def test_continue_mode_does_not_retry_transport_failure_and_processes_next_item(tmp_path, monkeypatch):
    async def no_sleep(_):
        pass
    monkeypatch.setattr("qozon_langchain.knowledge_base.pdf.processing_job.asyncio.sleep", no_sleep)
    class FailedImage(FakeImageModel):
        async def describe_image(self, *args, **kwargs):
            self.calls.append(True)
            raise ModelInvocationError("model_connection_failed")
    path = plan_source(tmp_path)
    table, image = FakeTableModel(), FailedImage()
    state = asyncio.run(run_processing_job(path, table_model=table, image_model=image,
                                         continue_pending_after_failure=True))
    assert state["status"] == "complete_with_errors"
    assert state["completed_items"] == state["failed_items"] == 1
    assert state["model_calls_started"] == 2
    assert len(image.calls) == len(table.calls) == 1
