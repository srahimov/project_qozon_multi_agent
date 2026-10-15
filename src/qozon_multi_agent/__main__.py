"""Print a local installation report without credentials or model calls."""

from importlib.metadata import version
import json
import platform


def main() -> None:
    packages = [
        "qozon-multi-agent",
        "fastapi",
        "uvicorn",
        "langchain",
        "langchain-openai",
        "langchain-docling",
        "langchain-text-splitters",
        "langchain-chroma",
        "chromadb",
        "pydantic-settings",
        "python-dotenv",
    ]
    print(
        json.dumps(
            {
                "stage": "pdf_rag_implemented",
                "python": platform.python_version(),
                "packages": {name: version(name) for name in packages},
                "configuration": "not_loaded_by_installation_report",
                "question_answering": "api_wired_requires_model_configuration",
                "retrieval": "requires_rag_enabled_and_matching_local_index",
                "model_calls": "none_in_installation_report",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
