"""Core runtime dependency checks without provider calls."""

import importlib
from importlib.metadata import version


def test_foundation_dependencies_import_without_provider_calls() -> None:
    for distribution, module in [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("langchain", "langchain"),
        ("langchain-openai", "langchain_openai"),
        ("pydantic-settings", "pydantic_settings"),
    ]:
        assert version(distribution)
        assert importlib.import_module(module)
