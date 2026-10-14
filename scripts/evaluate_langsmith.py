"""Create a versioned LangSmith dataset and run the gated PDF RAG evaluation.

No cloud calls without --sync or --run. --run makes paid answer, embedding and
judge calls, and uploads reviewed examples, checked evidence and checked answers.
Original images stay out of LangSmith; a vision judge receives the retrieved
picture through OpenAI only. --no-judge runs deterministic scores alone.
"""

import argparse
import asyncio
from collections import defaultdict
import json
from pathlib import Path

from qozon_langchain.core.config import get_settings
from qozon_langchain.core.observability import langsmith_client
from qozon_langchain.evaluation.langsmith_rag import (
    AnswerJudge, DATASET_NAME, DEFAULT_CASES, EvaluationTarget, PublicSourceEvaluator,
    accepts_scores, deterministic_scores, load_cases, sync_dataset,
)
from qozon_langchain.knowledge_base.pdf.chunking import save_json
from qozon_langchain.knowledge_base.pdf.retrieval import build_retriever
from qozon_langchain.llm.model import build_openai_model
from qozon_langchain.security.evidence_verification import POLICY_VERSION


async def execute(args):
    cases = load_cases(args.cases)
    requested = set(args.case_id or [])
    if requested - {case.id for case in cases}:
        raise ValueError("unknown_evaluation_case")
    selected = [case for case in cases if not requested or case.id in requested]
    if not selected:
        raise ValueError("unknown_evaluation_case")
    if not args.sync and not args.run:
        print(json.dumps({"status": "validated_locally", "cases": len(selected),
                          "dataset_cases": len(cases), "dataset": args.dataset}))
        return
    client = langsmith_client()
    if client is None:
        raise ValueError("langsmith_not_configured")
    settings = get_settings()
    if not settings.langsmith_trace_content:
        raise ValueError("checked_content_upload_not_enabled")
    project = client.read_project(project_name=settings.langsmith_project)
    dataset = sync_dataset(client, cases, name=args.dataset)
    report = {"status": "dataset_ready", "dataset": dataset.name, "dataset_id": str(dataset.id),
              "project": project.name, "project_id": str(project.id), "cases": len(selected),
              "dataset_cases": len(cases), "case_ids": [case.id for case in selected]}
    save_json(args.output, report)
    print(json.dumps(report), flush=True)
    if not args.run:
        return
    if not settings.rag_enabled:
        raise ValueError("rag_not_enabled")
    target = EvaluationTarget(build_openai_model(settings), build_retriever(settings))
    evaluators = [deterministic_scores, PublicSourceEvaluator(settings, target).__call__]
    if not args.no_judge:
        evaluators.append(AnswerJudge(settings, target).__call__)
    corpus = json.loads((settings.rag_chunks_directory / "manifest.json").read_text())
    # Run precisely these cases, even if the remote dataset contains other examples.
    ids = {c.id for c in selected}
    examples = [e for e in client.list_examples(dataset_id=dataset.id)
                if (e.metadata or {}).get("case_id") in ids]
    if len(examples) != len(selected):
        raise ValueError("dataset_case_count_mismatch")
    results = await client.aevaluate(
        target.__call__, data=examples, evaluators=evaluators, max_concurrency=1,
        experiment_prefix=f"{settings.langsmith_project}-pdf-rag", num_repetitions=1,
        metadata={"answer_model": settings.model_name, "judge_model": settings.evaluation_model_name,
                  "rag_backend": settings.rag_backend,
                  "corpus_sha256": corpus["corpus_sha256"], "rag_top_k": settings.rag_top_k,
                  "rag_max_distance": settings.rag_max_distance,
                  "rag_context_characters": settings.rag_context_characters,
                  "case_ids": sorted(ids),
                  "public_source_checks": True,
                  "references_provisional": True, "prompt_version": "sentence-selection-v1",
                  "evidence_verification_policy": POLICY_VERSION},
        description="Text/table/image and synthetic privacy checks; provisional source references.",
        disable_evaluator_tracing=True,
    )
    rows, aggregate = [], defaultdict(list)
    references = {case.id: case.reference for case in selected}
    async for row in results:
        scores = []
        for score in row["evaluation_results"]["results"]:
            scores.append({"key": score.key, "score": score.score, "comment": score.comment})
            if score.score is not None:
                aggregate[score.key].append(score.score)
        case_id = row["example"].metadata["case_id"]
        run = row["run"]
        rows.append({"case_id": case_id, "run_id": str(run.id) if run else None,
                     "scores": scores, "status": (run.outputs or {}).get("status") if run else None,
                     "code": (run.outputs or {}).get("code") if run else None,
                     "answer_calls": (run.outputs or {}).get("model_calls", 0) if run else 0,
                     "accepted": run is not None and accepts_scores(scores, references[case_id], judge=not args.no_judge)})
    report.update(status="completed", experiment=results.experiment_name, results=rows,
                  scores={key: {"mean": sum(values) / len(values), "count": len(values)}
                          for key, values in aggregate.items()})
    report["accepted"] = len(rows) == len(selected) and all(row["accepted"] for row in rows)
    report["answer_calls"] = sum(row["answer_calls"] for row in rows)
    report["judge_calls"] = sum(any(s["key"] in {"answer_correctness", "judge_available"} for s in row["scores"]) for row in rows)
    report["acceptance_target"] = "All required case scores equal 1; missing feedback fails."
    if not report["accepted"]:
        report["status"] = "needs_attention"
    save_json(args.output, report)
    client.flush(timeout=15)
    print(json.dumps({"status": report["status"], "experiment": results.experiment_name,
                      "cases": len(rows), "scores": report["scores"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--dataset", default=DATASET_NAME)
    parser.add_argument("--case-id", action="append", help="Run selected cases; repeat to select more than one.")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("data/evaluations/langsmith-latest.json"))
    args = parser.parse_args()
    try:
        asyncio.run(execute(args))
    except Exception as error:
        # SDK/provider exceptions can hold credentials or response bodies.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
