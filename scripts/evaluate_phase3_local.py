"""Local Phase 3 fixtures; --cloud uploads synthetic cases and SDK scores only.

Scripted replies never call an answer model or judge. No network without --cloud.
"""

import argparse
import asyncio
import json
from pathlib import Path

from qozon_langchain.evaluation.phase3_local import DEFAULT_CASES, load_phase3_cases, run_cloud_cases, run_local_cases
from qozon_langchain.knowledge_base.pdf.chunking import save_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--baseline", action="store_true", help="Run gates/service with scripted replies; no network or model calls.")
    mode.add_argument("--cloud", action="store_true", help="Upload synthetic fixtures and evaluation scores to LangSmith; no paid model calls.")
    parser.add_argument("--output", type=Path, default=Path("data/evaluations/phase3-latest.json"))
    args = parser.parse_args()
    cases = load_phase3_cases(args.cases)
    version = json.loads(args.cases.read_text())["version"]
    if not args.baseline and not args.cloud:
        print(json.dumps({"status": "validated_locally", "cases": len(cases), "synthetic_only": True, "external_model_calls": 0}))
        return
    report = asyncio.run(run_cloud_cases(cases, version) if args.cloud else run_local_cases(cases, dataset=version))
    save_json(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({"status": "failed", "code": "phase3_fixture_validation_or_execution_failed"}))
        raise SystemExit(1) from None
