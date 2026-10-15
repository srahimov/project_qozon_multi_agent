"""Buffered adapters for approved offline PDF ingestion; no import-time credentials or calls.

Ingestion adapters accept caller-approved document content. They do not implement
document/image privacy checks or persist results; ingestion must apply those checks
before invocation and validate generated descriptions before indexing.
"""

import base64

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langsmith import tracing_context
from openai import AuthenticationError, RateLimitError, APIConnectionError, APITimeoutError, NotFoundError

from qozon_multi_agent.core.config import Settings
from qozon_multi_agent.llm.model import build_chat_client
from qozon_multi_agent.llm.prompts import (
    IMAGE_DESCRIPTION_PROMPT, TABLE_SUMMARY_PROMPT,
)
from qozon_multi_agent.services.question_service import ModelInvocationError


class _BufferedOpenAIModel:
    """Shared invocation and safe error handling for ingestion model roles."""

    def __init__(self, client: ChatOpenAI) -> None:
        self._client = client

    @property
    def model_name(self) -> str:
        """Record which configured model generated an ingestion description."""
        return self._client.model_name

    async def _invoke(self, messages: list[SystemMessage | HumanMessage]):
        try:
            with tracing_context(enabled=False):
                response = await self._client.ainvoke(
                    messages,
                    config={"callbacks": []},
                )
        except AuthenticationError:
            raise ModelInvocationError("model_authentication_failed") from None
        except RateLimitError:
            raise ModelInvocationError("model_rate_limited") from None
        except APITimeoutError:
            raise ModelInvocationError("model_timeout") from None
        except APIConnectionError:
            raise ModelInvocationError("model_connection_failed") from None
        except NotFoundError:
            raise ModelInvocationError("model_not_available") from None
        except Exception:
            raise ModelInvocationError("model_unavailable") from None
        if not isinstance(response, AIMessage) or response.tool_calls:
            raise ModelInvocationError("invalid_model_answer")
        if response.response_metadata.get("status") not in {None, "completed"}:
            raise ModelInvocationError("model_incomplete")
        answer = str(response.text)
        if not answer.strip():
            raise ModelInvocationError("invalid_model_answer")
        return answer


def _check_context(context: str) -> None:
    if not isinstance(context, str) or len(context) > 8_000:
        raise ValueError("invalid_document_context")


class OpenAITableSummarizer(_BufferedOpenAIModel):
    """Summarize a complete, approved table without silently truncating its rows."""

    async def summarize_table(self, table_markdown: str, *, context: str = "") -> str:
        if (
            not isinstance(table_markdown, str) or not table_markdown.strip()
            or len(table_markdown) > 100_000
        ):
            raise ValueError("invalid_table_input")
        _check_context(context)
        return await self._invoke([
            SystemMessage(content=TABLE_SUMMARY_PROMPT),
            HumanMessage(content=f"Source context:\n{context}\n\nComplete table:\n{table_markdown}"),
        ])


class OpenAIImageVisualizer(_BufferedOpenAIModel):
    """Describe an approved picture; this adapter does not generate images."""

    async def describe_image(
        self, image_bytes: bytes, *, mime_type: str = "image/png", context: str = "",
    ) -> str:
        _check_context(context)
        if not isinstance(image_bytes, bytes) or not 0 < len(image_bytes) <= 10 * 1024 * 1024:
            raise ValueError("invalid_image_input")
        # Basic format checks only, not a full image decoder or privacy scanner.
        valid_format = (
            mime_type == "image/png" and image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
            or mime_type == "image/jpeg" and image_bytes.startswith(b"\xff\xd8\xff")
            or mime_type == "image/webp" and image_bytes.startswith(b"RIFF")
            and image_bytes[8:12] == b"WEBP"
        )
        if not valid_format:
            raise ValueError("invalid_image_format")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return await self._invoke([
            SystemMessage(content=IMAGE_DESCRIPTION_PROMPT),
            HumanMessage(content=[
                {"type": "text", "text": f"Caption and source context:\n{context}"},
                {"type": "image_url", "image_url": {
                    "url": f"data:{mime_type};base64,{encoded}", "detail": "high",
                }},
            ]),
        ])


def build_openai_table_summarizer(
    settings: Settings, *, max_output_tokens: int | None = None,
) -> OpenAITableSummarizer:
    """Build using the independent QOZON_TABLE_MODEL_NAME setting."""
    return OpenAITableSummarizer(build_chat_client(
        settings,
        model_name=settings.table_model_name,
        budget=max_output_tokens if max_output_tokens is not None else settings.table_output_max_tokens,
    ))


def build_openai_image_visualizer(
    settings: Settings, *, max_output_tokens: int | None = None,
) -> OpenAIImageVisualizer:
    """Build using the independent QOZON_IMAGE_MODEL_NAME setting."""
    return OpenAIImageVisualizer(build_chat_client(
        settings,
        model_name=settings.image_model_name,
        budget=max_output_tokens if max_output_tokens is not None else settings.image_output_max_tokens,
    ))
