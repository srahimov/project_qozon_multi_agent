"""Offline ingestion adapter tests; no local credentials or paid model calls."""

import asyncio
import base64
import json

import httpx
import pytest
from langchain_core.messages import AIMessage

from qozon_langchain.core.config import Settings
from qozon_langchain.llm import model
from qozon_langchain.services.question_service import ModelInvocationError


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII="
)


class FakeChatClient:
    def __init__(self, response=None):
        self.response = response if response is not None else AIMessage(content="Synthetic description")
        self.calls = []

    async def ainvoke(self, messages, *, config):
        self.calls.append((messages, config))
        return self.response


def test_table_adapter_keeps_headers_rows_and_context_without_truncation():
    client = FakeChatClient()
    table = "| Item | Count |\n|---|---|\n| Apples | 10 |\n| Carrots | 20 |"
    summary = asyncio.run(model.OpenAITableSummarizer(client).summarize_table(table, context="Page 7"))
    assert summary == "Synthetic description"
    messages, config = client.calls[0]
    assert messages[-1].content.endswith(table)
    assert "Page 7" in messages[-1].content
    assert config == {"callbacks": []}


def test_image_adapter_sends_picture_pixels_and_caption_together():
    client = FakeChatClient()
    description = asyncio.run(model.OpenAIImageVisualizer(client).describe_image(PNG, context="Figure 2"))
    assert description == "Synthetic description"
    content = client.calls[0][0][-1].content
    assert "Figure 2" in content[0]["text"]
    assert content[1]["image_url"]["detail"] == "high"
    assert base64.b64decode(content[1]["image_url"]["url"].split(",", 1)[1]) == PNG


@pytest.mark.parametrize("table", ["", "  ", None, "x" * 100_001], ids=["empty", "blank", "wrong-type", "oversized"])
def test_invalid_or_oversized_table_never_calls_model(table):
    client = FakeChatClient()
    with pytest.raises(ValueError, match="invalid_table_input"):
        asyncio.run(model.OpenAITableSummarizer(client).summarize_table(table))
    assert client.calls == []


@pytest.mark.parametrize("image,mime,code", [
    (b"", "image/png", "invalid_image_input"),
    ("not bytes", "image/png", "invalid_image_input"),
    (b"not an image", "image/png", "invalid_image_format"),
    (PNG, "image/jpeg", "invalid_image_format"),
    (PNG, "image/svg+xml", "invalid_image_format"),
    (b"x" * (10 * 1024 * 1024 + 1), "image/png", "invalid_image_input"),
], ids=["empty", "wrong-type", "bad-header", "mime-mismatch", "unsupported-format", "oversized"])
def test_invalid_image_never_calls_model(image, mime, code):
    client = FakeChatClient()
    with pytest.raises(ValueError, match=code):
        asyncio.run(model.OpenAIImageVisualizer(client).describe_image(image, mime_type=mime))
    assert client.calls == []


@pytest.mark.parametrize("kind", ["table", "image"])
def test_ingestion_rejects_oversized_context_before_call(kind):
    client = FakeChatClient()
    adapter = model.OpenAITableSummarizer(client) if kind == "table" else model.OpenAIImageVisualizer(client)
    task = adapter.summarize_table("Table", context="x" * 8_001) if kind == "table" else adapter.describe_image(PNG, context="x" * 8_001)
    with pytest.raises(ValueError, match="invalid_document_context"):
        asyncio.run(task)
    assert client.calls == []


@pytest.mark.parametrize("kind", ["table", "image"])
def test_incomplete_ingestion_output_is_withheld(kind):
    client = FakeChatClient(AIMessage(content="partial", response_metadata={"status": "incomplete"}))
    task = model.OpenAITableSummarizer(client).summarize_table("Table") if kind == "table" else model.OpenAIImageVisualizer(client).describe_image(PNG)
    with pytest.raises(ModelInvocationError, match="model_incomplete"):
        asyncio.run(task)


def test_builders_select_three_models_and_budgets_independently(monkeypatch):
    options = []
    def fake_chat(**kwargs):
        options.append(kwargs)
        return FakeChatClient()
    monkeypatch.setattr(model, "ChatOpenAI", fake_chat)
    settings = Settings(
        _env_file=None, openai_api_key="synthetic", output_max_tokens=128,
        table_output_max_tokens=256, image_output_max_tokens=512, image_model_name="gpt-6-luna",
    )
    assert isinstance(model.build_openai_model(settings), model.OpenAIAnswerModel)
    assert isinstance(model.build_openai_table_summarizer(settings), model.OpenAITableSummarizer)
    assert isinstance(model.build_openai_image_visualizer(settings), model.OpenAIImageVisualizer)
    assert [(item["model"], item["max_tokens"]) for item in options] == [
        ("gpt-6-luna", 128), ("gpt-5.6-terra", 256), ("gpt-6-luna", 512),
    ]
    assert settings.image_model_name == "gpt-6-luna"
    assert all(item["store"] is False and not item["streaming"] and item["max_retries"] == 0 for item in options)


def test_separate_environment_model_settings(monkeypatch):
    monkeypatch.setenv("QOZON_TABLE_MODEL_NAME", "gpt-6-luna")
    monkeypatch.setenv("QOZON_IMAGE_MODEL_NAME", "gpt-5.6-terra")
    monkeypatch.setenv("QOZON_TABLE_OUTPUT_MAX_TOKENS", "256")
    settings = Settings(_env_file=None)
    assert settings.table_model_name == "gpt-6-luna"
    assert settings.image_model_name == "gpt-5.6-terra"
    assert settings.table_output_max_tokens == 256


def test_real_langchain_serializes_image_to_responses_api_with_mock_transport():
    """Exercise the installed LangChain/OpenAI serializers without network access."""
    payloads = []
    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "resp_synthetic", "object": "response", "created_at": 1,
            "model": "gpt-5.6-terra", "status": "completed",
            "output": [{"id": "msg_synthetic", "type": "message", "role": "assistant",
                        "status": "completed", "content": [{"type": "output_text",
                        "text": "Synthetic image description", "annotations": []}]}],
        })
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            client = model.ChatOpenAI(
                model="gpt-5.6-terra", api_key="synthetic", use_responses_api=True,
                max_tokens=512, max_retries=0, store=False, callbacks=[],
                http_async_client=http_client,
            )
            return await model.OpenAIImageVisualizer(client).describe_image(PNG, context="Figure 2")
    assert asyncio.run(run()) == "Synthetic image description"
    assert len(payloads) == 1
    image = payloads[0]["input"][-1]["content"][1]
    assert image["type"] == "input_image"
    assert image["image_url"].startswith("data:image/png;base64,")
    assert payloads[0]["max_output_tokens"] == 512
    assert payloads[0]["store"] is False
