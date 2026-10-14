"""Cloud serving must start without native/local ingestion packages installed."""

import os
import subprocess
import sys


def test_cloud_retriever_imports_without_ingestion_packages(tmp_path):
    code = '''
import importlib.abc
import sys
class NoIngestion(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"chromadb", "langchain_chroma", "langchain_community",
                                     "langchain_docling", "cv2", "docling", "torch", "PIL"}:
            raise AssertionError("serving_imported_ingestion")
sys.meta_path.insert(0, NoIngestion())
from qozon_langchain.api.app import create_app
from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.pdf.retrieval import build_retriever
settings = Settings(_env_file=None, rag_backend="supabase", openai_api_key="synthetic-offline-key")
assert type(build_retriever(settings)).__name__ == "CloudPDFRetriever"
assert "/questions" in create_app().openapi()["paths"]
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                            env={**os.environ, "LANGSMITH_TRACING": "false"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
