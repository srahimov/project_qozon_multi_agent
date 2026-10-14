"""Offline adapter checks with synthetic configuration and a fake chat client."""

import asyncio

import pytest
from langchain_core.messages import AIMessage

from qozon_langchain.core.config import Settings
from qozon_langchain.llm import model
from qozon_langchain.services.question_service import ModelInvocationError
from qozon_langchain.knowledge_base.pdf.retrieval import Evidence
from qozon_langchain.security.evidence_verification import verify_evidence


class FakeChatClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def ainvoke(self, messages, *, config):
        self.calls.append((messages, config))
        return self.response


def test_adapter_extracts_text_blocks_and_passes_approved_question() -> None:
    client = FakeChatClient(AIMessage(content=[{"type": "text", "text": "Synthetic answer"}]))
    answer = asyncio.run(model.OpenAIAnswerModel(client).generate_answer("Approved question"))
    assert answer == "Synthetic answer"
    assert client.calls[0][0][-1].content == "Approved question"
    assert client.calls[0][1] == {"callbacks": []}


@pytest.mark.parametrize("response,code", [
    (AIMessage(content="partial", response_metadata={"status": "incomplete"}), "model_incomplete"),
    (AIMessage(content=""), "invalid_model_answer"),
    (AIMessage(content="", tool_calls=[{"name": "example", "args": {}, "id": "synthetic"}]), "invalid_model_answer"),
    ("invalid", "invalid_model_answer"),
])
def test_unusable_model_responses_are_withheld(response, code) -> None:
    with pytest.raises(ModelInvocationError) as caught:
        asyncio.run(model.OpenAIAnswerModel(FakeChatClient(response)).generate_answer("Approved question"))
    assert caught.value.code == code


def test_adapter_failure_never_exposes_provider_error() -> None:
    class BrokenClient:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("synthetic-private-provider-value")
    with pytest.raises(ModelInvocationError) as caught:
        asyncio.run(model.OpenAIAnswerModel(BrokenClient()).generate_answer("Approved question"))
    assert str(caught.value) == "model_unavailable"
    assert caught.value.__suppress_context__


def test_factory_requires_key_and_explicit_budget(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    with pytest.raises(ValueError, match="openai_key_not_configured"):
        model.build_openai_model(settings, max_output_tokens=128)
    settings = Settings(_env_file=None, openai_api_key="synthetic-test-value", output_max_tokens=None)
    with pytest.raises(ValueError, match="output_budget_required"):
        model.build_openai_model(settings)


def test_factory_uses_selected_model_and_bounded_nonstreaming_request(monkeypatch) -> None:
    options = {}
    def fake_chat(**kwargs):
        options.update(kwargs)
        return FakeChatClient(AIMessage(content="4"))
    monkeypatch.setattr(model, "ChatOpenAI", fake_chat)
    settings = Settings(_env_file=None, openai_api_key="synthetic-test-value")
    adapter = model.build_openai_model(settings, max_output_tokens=128)
    assert isinstance(adapter, model.OpenAIAnswerModel)
    assert options["model"] == "gpt-6-luna"
    assert options["use_responses_api"] and not options["streaming"]
    assert options["max_tokens"] == 128 and options["max_retries"] == 0
    assert options["timeout"] == 30 and options["store"] is False


class SelectionClient(FakeChatClient):
    def __init__(self, ids, *, parsing_error=None):
        super().__init__({"raw": AIMessage(content='{"sentence_ids": []}'),
                          "parsed": model.GroundedSelection(sentence_ids=ids), "parsing_error": parsing_error})
    def with_structured_output(self, schema, **kwargs):
        assert schema is model.GroundedSelection
        assert kwargs == {"method": "json_schema", "include_raw": True}
        return self


def evidence(text, n=1):
    return Evidence(str(n), "book", "fixture.txt", (n,), "text", "", text)


def test_grounded_selection_copies_original_sentences_and_canonical_citations():
    items = [evidence("The box is red. The box contains five stones."), evidence("The gate is not open.", 2)]
    client = SelectionClient(["S1:2", "S2:1"])
    answer = asyncio.run(model.OpenAIAnswerModel(client).generate_grounded_answer("What does the evidence say?", items))
    assert answer == "The box contains five stones. [S1]\nThe gate is not open. [S2]"
    assert verify_evidence(answer, items).cited == (1, 2)
    assert len(client.calls) == 1
    assert '"S1:2": "The box contains five stones."' in client.calls[0][0][-1].content[0]["text"]


@pytest.mark.parametrize("ids", [["S9:1"], ["S1:9"], ["Invented answer"]])
def test_selection_cannot_introduce_unknown_sentences(ids):
    with pytest.raises(ModelInvocationError, match="invalid_model_answer"):
        asyncio.run(model.OpenAIAnswerModel(SelectionClient(ids)).generate_grounded_answer("Question?", [evidence("The box is red.")]))


def test_empty_selection_abstains_without_fabricated_sources():
    items = [evidence("The box is red.")]
    answer = asyncio.run(model.OpenAIAnswerModel(SelectionClient([])).generate_grounded_answer("What is its age?", items))
    assert verify_evidence(answer, items).mode == "abstention"
    assert verify_evidence(answer, items).cited == ()


def test_selection_requires_conflicting_sources_to_remain_disclosed():
    items = [evidence("The jar contains four stones."), evidence("The jar contains six stones.", 2)]
    answer = asyncio.run(model.OpenAIAnswerModel(SelectionClient(["S1:1", "S2:1"])).generate_grounded_answer("What is the count?", items))
    assert verify_evidence(answer, items).mode == "conflict_disclosure"


def test_failed_structured_parse_is_withheld():
    with pytest.raises(ModelInvocationError, match="invalid_model_answer"):
        asyncio.run(model.OpenAIAnswerModel(SelectionClient(["S1:1"], parsing_error=ValueError("synthetic"))).generate_grounded_answer("Question?", [evidence("The box is red.")]))


def test_valid_parsed_selection_does_not_require_raw_text_and_deduplicates_ids():
    client = SelectionClient(["S1:1", "S1:1"])
    client.response["raw"] = AIMessage(content="")
    answer = asyncio.run(model.OpenAIAnswerModel(client).generate_grounded_answer("Question?", [evidence("The box is red.")]))
    assert answer == "The box is red. [S1]"


def test_table_selection_can_include_more_than_eight_supported_rows():
    text = "\n".join(f"Topic {n} is listed." for n in range(1, 13))
    items = [evidence(text)]
    client = SelectionClient([f"S1:{n}" for n in range(1, 13)])
    answer = asyncio.run(model.OpenAIAnswerModel(client).generate_grounded_answer("List the topics.", items))
    assert verify_evidence(answer, items).cited == (1,)
    assert answer.count("[S1]") == 12
