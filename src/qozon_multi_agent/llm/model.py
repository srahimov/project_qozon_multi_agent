"""Construct the configured LangChain OpenAI client; no provider calls here.

API agents receive this client directly. Approved offline table/image ingestion
uses the small adapters in adapters.py.
"""

from langchain_openai import ChatOpenAI

from qozon_multi_agent.core.config import Settings


def build_chat_client(settings: Settings, *, model_name: str, budget: int | None) -> ChatOpenAI:
    """Client construction makes no request; invocation remains explicit."""
    if settings.openai_api_key is None:
        raise ValueError("openai_key_not_configured")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
        raise ValueError("output_budget_required")
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model_name_required")
    return ChatOpenAI(
        model=model_name,
        api_key=settings.openai_api_key,
        use_responses_api=True,
        max_completion_tokens=budget,
        reasoning={"effort": "none"},
        timeout=30,
        max_retries=0,
        streaming=False,
        store=False,
        callbacks=[],
    )
