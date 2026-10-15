# Qozon: current execution history and next phases

Current execution-only fork policy is recorded in the main platform blueprint below.

Current fork package: `src/qozon_multi_agent/`. The inherited execution records below retain the original project and module names; the current fork plan is [MULTI_AGENT_PLAN.md](docs/MULTI_AGENT_PLAN.md).

Current deployment target: independent `qozon-multi-agent-api` Cloudflare Worker,
Basic container built from this fork's Dockerfile, separate Durable Object quota
namespace and admission secret. Runtime secrets are supplied through ignored
`cloudflare/.env.deploy`. Deployment publication status is recorded in README.md.
The original `qozon-api` and separate React website are not retargeted.

Reconciled on October 13, 2026; commands simplified and expanded Phase 3 acceptance verified on October 12. Current supported commands are in README.md; executed command names below may be historical.

The editable source is `../phase-tracker/plan.json`; the browser view is
[the local phase tracker](http://127.0.0.1:8894/index.html). `phase-tracker/index.html` loads the JSON source on refresh and contains an offline fallback snapshot.

Project: `/Users/sardoravaz/udemy-lc/langchain-enterprise/project_Qozon`.
Tracker: `/Users/sardoravaz/udemy-lc/langchain-enterprise/phase-tracker/index.html`.

Current focus: October 13: public React chat at https://srahimov.site/multimodal-rag is connected to the deployed Qozon API. Approved frontend commit 1150664 pushed and exact build published to existing Pages project; public JS bytes match. Seven client tests/build/local saved-answer-citation UI checks pass; actual browser JSON/CORS and model-blocked input error verified, no new paid calls. Prior 21 hosted reads/privacy/citation checks, durable quota retention and one live page-4 answer remain accepted. Q&A/approved citations public; original PDF private. User manages OpenAI cap; full hosted lifecycle/image rollback acceptance remains. Later SQL/Wikipedia specialists and LangGraph orchestration remain planned; no phase is marked fully production-accepted.

Latest executed offline regression checkpoint (October 13): **639 passed, 1 live test skipped, 27 library warnings** (existing deprecations/SDK warnings emitted by additional SDK tests). Expanded Phase 3 acceptance passes **50/50 locally and 50/50 in LangSmith with scripted replies**. The original screening-v2 checkpoint passed **25/25**. Live PDF acceptance is **9/9 across the full and focused reruns**, with seven correctness and groundedness judgments passing. The 319 retrieved source-sentence checks also pass. The original **18/25** and intermediate **23/25** reports are preserved. Conservative evidence matching is unchanged and can withhold valid paraphrases; these fixtures do not establish general semantic truth or complete injection protection.

The initial reconciliation made no new provider, cloud evaluation, Storage or database calls. Subsequent Phase 3 acceptance uploaded fictional cases and scripted results to LangSmith, then ran explicitly approved live PDF evaluations and focused reruns. Total paid attempts: 16 answer, 7 judge and 16 query-embedding invocations. Reviewed checked book content was uploaded with explicit permission; original images stayed out of LangSmith. Live/cloud steps below are historical executions backed by saved reports; paid/upload commands are references and require their own scope/approval before any new run. Commands/functions are summarized; module paths and flags should be checked before execution.

## Main platform blueprint — current fork policy

**This project contains execution code only. All LLM evaluation, observability and monitoring are handled solely through LangSmith.**

- **LangChain:** real supervisor and PDF subagent, delegation tools, model calls, retrieval and registered PII middleware.
- **LangGraph:** LangChain's internal runtime; no custom graph is planned for this fork.
- **LangSmith:** the sole external platform for LLM quality evaluation, traces, token/latency/cost visibility and monitoring. Use native platform/SDK integration rather than custom judges, scoring functions, telemetry wrappers or local reporting systems.

Do not add test suites, fake-model runners, evaluation scripts or monitoring modules to this project. Do not run tests or paid evaluations during development unless the user explicitly changes this direction. Keep only the execution code and controls required for privacy, request validation, citation/schema integrity, source access, deadlines and usage limits.

Implemented API ingress boundary: `POST /questions` sanitizes the visitor question once, screens it and checks input credentials before constructing/invoking the supervisor. Neither agent repeats these input checks. Runtime PII remains exclusively on registered supervisor middleware. The PDF delegation wrapper forwards the PII-checked question unchanged and copies the specialist result through supervisor output hooks without a model rewrite. The API returns answer text and approved citation details; request deadlines and usage limits remain.

The inherited direct-model service and extractive answer adapter have been replaced. The normal successful flow uses one supervisor routing call, one PDF synthesis call and one embedding. This integration has only static source/configuration inspection: no local tests, evaluation, provider calls, monitoring, exports, push or deployment were run.

The runtime support-review judge, local evaluation/test directories and custom observability wrapper have been removed from this fork. A reference copy is preserved outside the project. LangSmith configuration remains available, but this cleanup did not enable tracing, export content or deploy anything. The original Qozon project and production deployment remain unchanged.

Records below describe the inherited original project and superseded commands, not the current fork's active tooling.

## Phase overview

| Phase | Source status |
| --- | --- |
| 1. Simple complete English QA API | QA demo live-verified |
| 2. Local PDF RAG: text, tables and images | Local PDF RAG live-verified |
| 3. Layered guardrails and evidence verification | Accepted · training scope |
| 4. Supabase PDF pipeline and cloud retrieval | Public chat/API connected · final operations acceptance pending |
| 5. Supabase English business directory SQL | Not started · schema needed |
| 6. Wikipedia specialist | Not started · approved links needed |
| 7. LangGraph multi-agent orchestration | Not started · specialists first |
| 8. Evaluation and operations | Partial · evaluations done, operations pending |

## Phase 1: Simple complete English QA API

Packaged Python project, strict contracts, local privacy/security gates, buffered LangChain adapter, service and POST /questions are implemented. Recorded live service and HTTP checks succeeded. This is a training demo; English/relevance enforcement and comprehensive detector coverage are not complete.

### Executed steps and verification

#### 1. Initialize the Python package and isolated environment

Processing: Local setup

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
uv init --package --name qozon-langchain --python 3.12.14 --vcs none --no-workspace project_Qozon; uv sync --locked
```

Outputs: project_Qozon, src/qozon_langchain, .venv, exact dependency pins and uv.lock. Reused uv 0.12.9 / Python 3.12.14.

Verification: Initial install policy mismatch was fixed by aligning the resolver configuration; later dependency additions have their current policies recorded in pyproject.toml.

Evidence: `pyproject.toml`, `.python-version`, `uv.lock`, `README.md`.

#### 2. Configure local dotenv and strict API schemas

Processing: Local; synthetic tests

Inputs: Blank local template and synthetic test values; no credentials displayed.

Recorded command/function:

```text
uv add --bounds exact python-dotenv; Settings(); QuestionRequest(); QuestionResponse()
```

Outputs: python-dotenv 1.2.4 is a direct dependency. Credentials stay in ignored local configuration; Settings loads lazily. Request text is strict, required, nonblank and at most 200 original Unicode characters.

Verification: Synthetic file loading, environment precedence, hidden key representations and schema boundaries were tested. Current response adds resolved sources. No credential values are copied to the plan.

Evidence: `core/config.py`, `api/schemas.py`, `tests/core/test_dotenv.py`, `tests/api/test_schemas.py`.

#### 3. Implement sanitization and local instruction screening

Processing: Local; no paid classifier

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
sanitize_question(); screen_question()
```

Outputs: Original length validation, NFC text normalization, whitespace collapse, selected unwanted-control rejection and allow/review/reject signals.

Verification: Historical checkpoints: 64 tests after sanitization, 100 after screening. Selected rules cover the eight teaching groups; false positives and obfuscation gaps remain.

Evidence: `security/sanitization.py`, `security/screening.py`, `tests/security/test_sanitization.py`, `tests/security/test_screening.py`.

#### 4. Implement selected PII policies, secrets and both gates

Processing: Local; configured redaction

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
training_policy(); check_pii(); check_secrets(); check_input(); check_output()
```

Outputs: Five LangChain built-ins plus SSN, numbered English address, labeled medical-card ID, labeled DOB and age patterns. Names are deliberately preserved. Secrets block separately; checker failures withhold text.

Verification: Input and buffered output checks, redaction, block/review behavior and safe failures were exercised. Names/phones/other formats and image privacy are not generally covered. No GDPR/HIPAA compliance claim.

Evidence: `security/policies.py`, `security/custom_pii.py`, `security/input_gate.py`, `security/output_gate.py`, `tests/security/`.

#### 5. Connect the service, LangChain OpenAI adapter and API

Processing: Local code + previously approved remote/paid checks

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
answer_question(); build_openai_model(); POST /questions
```

Outputs: One approved question flows through the input gate, lazy GPT-6 Luna generation, buffered output gate and response. The last recorded live API budget was 512 generation tokens, separate from the 200-character question cap.

Verification: October 9 record: live service and real HTTP synthetic arithmetic checks returned the checked answer; blocked/held input avoids model construction/calls. Provider error details are withheld. No new live calls during this plan update.

Evidence: `services/question_service.py`, `llm/model.py`, `api/questions.py`, `api/dependencies.py`, `README.md`.

#### 6. Verify the current local test suite

Processing: Offline; freshly executed October 11, 2026

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
QOZON_RUN_LIVE_TEST=0 LANGSMITH_TRACING=false QOZON_LANGSMITH_TRACE_CONTENT=false .venv/bin/python -m pytest -q
```

Outputs: 446 tests passed; 2 opt-in live tests skipped; 7 library warnings.

Verification: Exit code 0. This is separate from the Phase 3 behavioral baseline: unit tests also document known gaps. No provider calls or cloud evaluation were requested.

Evidence: `tests/`, `phase-tracker/verification.json`.

### Planned next steps

1. Review the working Phase 1 API and policy decisions, without treating selected detectors as complete protection.
2. Keep input privacy/screening before retrieval/model calls and output checks before release as new sources are added.
3. Decide whether and how to enforce English/task relevance and remaining detector formats; record exclusions deliberately.
4. Keep API budgets/timeouts distinct from question length and verify logging/trace boundaries when changing integrations.

Next inputs/decision: Phase 3 training acceptance is complete. Current next work is Phase 4 public cloud retrieval and reviewed index import; no repeat paid connectivity smoke is needed.


## Phase 2: Local PDF RAG: text, tables and images

Local full-book extraction, approved table/picture processing, persistent Chroma + lexical retrieval and cited API answers are implemented. The active corpus has 2,451 chunks; whole-book OCR/factual accuracy is not fully verified.

### Executed steps and verification

#### 1. Download and extract the first PDF sample

Processing: Previously executed Storage download + local OCR

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
download_pdf(); load_pdf_documents()
```

Outputs: The approved private PDF was downloaded (86,588,927 bytes). Initial physical pages 1–3 produced 19 text blocks, three page images and one picture.

Verification: The sample export and preserved page images were reviewed. OCR extracts image text; it does not itself interpret picture semantics.

Evidence: `README.md`, `data/extraction-summary.json`, `data/asset-extraction-summary.json`.

#### 2. Complete full-book extraction with resumable checkpoints

Processing: Local Docling CPU/OCR; no OpenAI extraction call

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
python -m qozon_langchain.knowledge_base.pdf.extraction_job --batch-size 10 --threads 6 --device cpu
```

Outputs: 641 physical pages, 98 pictures and 49 tables exported with provenance, captions, rich JSON, page images and crops.

Verification: Full-book verification reports complete page coverage. One empty structured table on physical page 6 remains excluded. Full transcription/layout accuracy is unreviewed.

Evidence: `data/pdf-assets/full-book/progress.json`, `data/pdf-assets/full-book/verification.json`.

#### 3. Process approved table/picture assets and retry only failed pictures

Processing: Previously approved remote/paid GPT-5.6 Terra ingestion

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
python -m qozon_langchain.knowledge_base.pdf.processing_job --plan data/pdf-summaries/processing-plan.json
```

Outputs: The initial approved run made 146 attempts; eight explicitly approved picture retries completed the selected set of 98 image descriptions + 48 table summaries.

Verification: 146 saved results pass selected local text checks and page/source linkage. The recorded initial/retry attempt total is 154; this is not a total for all later repair/evaluation calls. Generated descriptions are not all factually/visually verified.

Evidence: `data/pdf-summaries/completion.json`, `data/pdf-summaries/verification.json`, `data/pdf-summaries/summary-index.json`.

#### 4. Chunk, embed, persist and retrieve the corpus

Processing: Local splitting/Chroma; previously approved paid embedding calls

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
python -m qozon_langchain.knowledge_base.pdf.chunking; python -m qozon_langchain.knowledge_base.pdf.indexing --batch-size 32
```

Outputs: Recursive splitting, 1,000-character target / 150 overlap, checked text, OpenAI embeddings (text-embedding-3-small, 1,536 dimensions), persistent vectors, BM25 + semantic fusion and canonical physical-page citations.

Verification: The original 2,450-record index was reopened and verified; an interrupted batch resumed via cached vectors. Later reviewed repairs produce the active 2,451-chunk revision.

Evidence: `data/pdf-chunks/verification.json`, `data/chroma/index-manifest.json`, `knowledge_base/pdf/retrieval.py`.

#### 5. Exercise real RAG HTTP paths and citation/PII handling

Processing: Previously approved remote/paid query + answer checks

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
Historical: retired verify_pdf_rag.py smoke; current endpoint: POST /questions
```

Outputs: Text, table and picture queries returned checked answers with resolved source/page metadata; selected sensitive input was redacted and selected secret input was blocked.

Verification: Saved live and HTTP reports verify the exercised examples. Empty retrieval abstains without generation; valid source IDs are checked, not arbitrary claim entailment.

Evidence: `data/chroma/live-api-verification.json`, `data/chroma/http-verification.json`, `data/rag-completion.json`.

#### 6. Repair reviewed table/caption sources and refresh only changed vectors

Processing: Local reviewed repair + approved Terra/embedding refresh

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
Historical: repair_reviewed_sources() and retired two-source refresh script. Current reviewed processing: knowledge_base.pdf.processing_job.
```

Outputs: Page-5 contents cells and page-2 caption linkage were repaired with backups; original assets/PDF stay unchanged. Reviewed Terra summaries update the active 2,451-chunk index.

Verification: Source fingerprints and before/after histories are preserved. New embeddings were limited to changed texts; manual-review and original baselines remain retained.

Evidence: `data/source-repairs/repair-report.json`, `data/source-repairs/terra-refresh-v1/index-report.json`, `data/chroma/index-manifest.json`.

#### 7. Add incremental Chroma updates and recovery

Processing: Local dry run/adoption; embedding misses can be paid only on apply

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
python -m qozon_langchain.knowledge_base.pdf.incremental --initialize; python -m qozon_langchain.knowledge_base.pdf.incremental --apply
```

Outputs: Stable source units, changed-only splitting, obsolete-chunk deletion, cached embeddings, reader/writer locks and journaled recovery.

Verification: The recorded unchanged apply kept 2,451 chunks with zero split units, new embedding texts or record writes. Recovery/deletion/metadata changes are covered with synthetic tests.

Evidence: `data/chroma/incremental-last-update.json`, `knowledge_base/pdf/incremental.py`, `tests/knowledge_base/pdf/test_incremental.py`.

### Planned next steps

1. Review and repair the excluded empty page-6 table before changing its approval/index state.
2. Use the passing 50-case Phase 3 baseline when adding representative source/quality cases; review conservative false-withhold behavior before expanding answer claims.
3. Add representative OCR/table/row and image-caption review cases; passing small evaluation samples does not validate the entire book.
4. Use the incremental dry run for future source corrections, then authorize changed-text embedding calls and verify the committed revision.

Next inputs/decision: The current local PDF demo is working. Remaining inputs are targeted source/quality reviews; no full-book re-extraction or paid rerun is needed for this plan update.


## Phase 3: Layered guardrails and evidence verification

**Accepted for the stated training scope.** Expanded acceptance passes **50/50 locally and 50/50 in LangSmith** under the final guard policy. Live PDF acceptance is **9/9 across the full and focused reruns**: seven previously accepted full-run cases plus the two focused table repairs. Every applicable final case score passes, including seven answer correctness/groundedness judgments. The final offline suite passes **516 tests, with 1 live test skipped**. All **319 retrieved source-sentence checks** pass.

LangChain structured output selects source sentence IDs; the application copies the original text and attaches canonical citations. Unknown IDs fail; duplicates are normalized. Table selections may contain up to 24 sentences within the existing token/evidence budgets, and valid parsed output need not contain free-form raw text. **Extractive-v2** preserves quote characters. Valid arbitrary paraphrases and numeral substitutions remain outside this policy; a judge evaluates quality without replacing the service evidence guard.

The original 18/25, intermediate 23/25, screening-v2 25/25 and first failed live reports remain intact. The QA model has no SQL, web, shell or write tools, and tool-call replies remain rejected. Future specialists need their own authorization boundaries. The 45-second deadline cancels cooperative async waits; it cannot preempt synchronous CPU work or guarantee provider-side cancellation. One answer invocation per request, positive output-token budgets, bounded context, provider timeouts and disabled automatic model retries provide the implemented call/time controls; a hard dollar quota is not claimed.

This is finite training acceptance on reviewed examples from physical pages 2, 4 and 5. It does not establish whole-book accuracy, general semantic entailment or production security certification. The final acceptance combines a full experiment and focused repairs; previously passing cases were not paid-rerun after the last table-format adjustment. All offline regression checks passed afterward. The completion report records source hashes and exact experiment provenance.

### Executed steps and verification

#### 1. Define synthetic service and source-gate evaluation lanes

Processing: Local; synthetic only

Outputs: 25 cases cover grounding, conflict, citations, retrieved instructions, benign controls, privacy and availability. Service probes use checked fictional evidence and scripted replies.

Verification: Dataset shape, unique IDs and lane separation are validated; tests do not send fixture data to providers or LangSmith.

Evidence: `evals/phase3_synthetic_cases_v1.json`, `evals/phase3_synthetic_cases_v1.schema.json`, `tests/evaluation/test_phase3_local.py`.

#### 2. Preserve the original behavioral baseline

Processing: Recorded local baseline; zero external model calls/uploads

Outputs: 25 probes: 18 pass, 7 fail. Gaps: irrelevant evidence, unsupported claims using a valid ID, silent conflict selection, valid ID attached to wrong passage, fabricated page text, spaced obfuscation and benign quoted text held incorrectly.

Verification: Saved report status is baseline_has_gaps. Unit tests preserve the diagnosis; they do not claim these seven desired behaviors are implemented. Timeout injection checks an error path, not a wall-clock deadline.

Evidence: `data/evaluations/phase3-local-baseline.json`.

#### 3. Record the previously implemented extractive-verification revision

Processing: Local scripted fixtures; no provider calls

Outputs: 23 probes pass; 2 screening cases remain unresolved.

Verification: Read the saved report; the guard code was not changed by this simplification. This is finite-fixture checking, not a general quality guarantee.

Evidence: `security/evidence_verification.py`, `data/evaluations/phase3-evidence-verification-v1.json`.

#### 4. Fix the two remaining screening cases and verify the offline suite

Processing: Local synthetic evaluation and offline tests, executed October 12, 2026.

Inputs: Unchanged 25-case dataset plus regression cases for spaced instructions, descriptive quotations and attempts to enact or hide instructions beside a quotation.

Recorded commands:

```sh
QOZON_RUN_LIVE_TEST=0 QOZON_RUN_LIVE_PDF_TEST=0 LANGSMITH_TRACING=false QOZON_LANGSMITH_TRACE_CONTENT=false .venv/bin/python scripts/evaluate_phase3_local.py --baseline --output data/evaluations/phase3-screening-v2.json
QOZON_RUN_LIVE_TEST=0 QOZON_RUN_LIVE_PDF_TEST=0 LANGSMITH_TRACING=false QOZON_LANGSMITH_TRACE_CONTENT=false .venv/bin/python -m pytest -q
```

Outputs: 25/25 behavioral probes pass; 495 tests pass, 1 opt-in live test skips, 7 existing library warnings. No provider calls or uploads.

Verification: Spaced override signals hold questions and documents. Only instruction-override matches inside a complete descriptive educational quotation are exempted for documents. Bare quotes, additional matched signals, unquoted overrides and requests to enact the example remain held. Question screening stays conservative. Evidence-verification behavior is unchanged.

Evidence: `security/screening.py`, `tests/security/test_screening.py`, `tests/evaluation/test_phase3_local.py`, `data/evaluations/phase3-screening-v2.json`, `phase-tracker/verification.json`.

#### 5. Expand local acceptance and fix newly exposed source variants

Processing: Local synthetic fixtures; no paid calls or uploads.

Inputs: The original 25 cases plus 25 fictional source, quotation, conflict, citation and extractive-policy controls. All original cases remain unchanged.

Recorded command:

```sh
LANGSMITH_TRACING=false QOZON_LANGSMITH_TRACE_CONTENT=false .venv/bin/python scripts/evaluate_phase3_local.py --cases evals/phase3_synthetic_cases_v2.json --baseline --output data/evaluations/phase3-acceptance-v1.json
```

Outputs: **50/50 pass**. Dotted/hyphenated override signals and multiline encoded-execution signals now hold. One fixture's invisible-character error identifier was corrected to match the existing rejection policy. Valid paraphrase withholding is recorded as an explicit extractive-policy tradeoff.

Evidence: `evals/phase3_synthetic_cases_v2.json`, `data/evaluations/phase3-acceptance-before-v1.json`, `data/evaluations/phase3-acceptance-v1.json`, `security/screening.py`.

#### 6. Enforce the workflow deadline and strict evaluation acceptance

Processing: Local code and offline tests.

Outputs: **502 passed, 1 live test skipped**. Real hanging retrieval/model waits are cancelled by the workflow deadline; HTTP timeout maps to 504. Caller cancellation propagates. Any failed required score, missing judge feedback or missing run prevents evaluation acceptance. The two evaluation scripts remain the only scripts; no dependency, ingestion or index changes were made.

Verification: Deadline tests use actual async waits rather than injecting a timeout exception. Existing tool-call output rejection remains covered. An installed-SDK offline contract test verifies synthetic dataset example reuse.

Evidence: `services/question_service.py`, `api/questions.py`, `evaluation/langsmith_rag.py`, `tests/services/test_rag_question_service.py`, `tests/evaluation/test_phase3_local.py`, `tests/evaluation/test_langsmith_rag.py`.

#### 7. Execute LangSmith synthetic acceptance

Processing: Authorized upload of fictional fixtures and scripted results; zero external model calls.

Recorded command:

```sh
LANGSMITH_TRACING=true QOZON_LANGSMITH_TRACE_CONTENT=true .venv/bin/python scripts/evaluate_phase3_local.py --cases evals/phase3_synthetic_cases_v2.json --cloud --output data/evaluations/phase3-langsmith-acceptance-v1.json
```

Outputs: **50/50 pass** in [the LangSmith synthetic experiment](https://smith.langchain.com/o/32ee7fde-eac9-4caf-8d73-ecb088aa8048/datasets/8856d232-2fec-4bea-acd4-bfb67b07e762/compare?selectedSessions=be68e8cf-b154-4865-aa55-e300e2eb1b36). No book content or images were uploaded. Stable IDs, immutable comparisons and batched synchronization preserve versioned examples.

Evidence: `data/evaluations/phase3-langsmith-acceptance-v1.json`, `evaluation/phase3_local.py`.

#### 8. Prepare and authorize the live PDF acceptance run

Processing: Local validation followed by explicit export and bounded paid-run approval.

Inputs: Six previously reviewed text/table/image/privacy cases plus three rephrased questions using the same reviewed source references. These cover physical pages 2, 4 and 5, not the entire book.

Prepared command:

```sh
LANGSMITH_TRACING=true QOZON_LANGSMITH_TRACE_CONTENT=true .venv/bin/python scripts/evaluate_langsmith.py --cases evals/pdf_rag_cases_v5.json --dataset project_qozon-phase3-pdf-v1 --run --output data/evaluations/phase3-pdf-langsmith-v1.json
```

Acceptance targets: Every case must pass all applicable workflow/privacy, retrieval, citation, public-source and correctness/groundedness judge scores. Missing scores fail. Maximum seven answer calls, seven judge calls and seven query-embedding calls; concurrency one, one repetition, no automatic model retries. Answer output is capped at 512 tokens per call and judge output at 768. LangChain runs the adapters/retrieval and LangSmith runs the evaluation, following the [official evaluation workflow](https://docs.langchain.com/langsmith/evaluation-types).

Status: **Executed after explicit approval.** Initial automatic approval review required explicit book-content export permission; the user supplied it, then approved bounded extensions after the failed runs. Questions, references, checked evidence and answers were uploaded to LangSmith. Original images stayed out of LangSmith; selected reviewed pixels went to the OpenAI adapters. Actual outcomes are recorded below.

Evidence: `evals/pdf_rag_cases_v5.json`, `data/evaluations/phase3-acceptance-plan.json`, `scripts/evaluate_langsmith.py`.

#### 9. Execute the first live run and preserve its failures

Outputs: The two security cases pass; all seven book answers are withheld, and one rephrased question misses its expected source page. The experiment is not accepted. Seven answer/query-embedding calls are used; no judge calls occur because the replies are withheld.

Evidence: `data/evaluations/phase3-pdf-langsmith-v1.json`, `data/evaluations/phase3-pdf-diagnosis-v1.json`.

#### 10. Repair generation, quotation handling and the rephrased query

Outputs: LangChain selects sentence IDs and the application copies source text. Quote characters are preserved instead of stripped from claims. A small aims/purpose lexical alias ranks the preface first. All 319 retrieved source sentences pass locally. Unknown IDs and malformed selections remain blocked; output/privacy/citation checks still apply.

Verification: Valid parsed output can have empty raw text; duplicate IDs are normalized and table selection allows up to 24 sentences. All 516 tests pass, 1 live test skips; 27 existing SDK/deprecation warnings are emitted. No dependencies, source documents, approved summaries or index records change.

Evidence: `llm/model.py`, `security/evidence_verification.py`, `knowledge_base/pdf/retrieval.py`, `tests/llm/test_model.py`, `tests/security/test_evidence_verification.py`, `data/evaluations/phase3-source-sentence-roundtrip-v2.json`.

#### 11. Verify the full rerun and focused table repairs

Processing: Each additional paid-call budget was explicitly approved; the reviewed export scope stays the same.

Outputs: [Full live rerun](https://smith.langchain.com/o/32ee7fde-eac9-4caf-8d73-ecb088aa8048/datasets/28fb3bfb-604e-498e-b621-4d628421effb/compare?selectedSessions=3935e093-2fe6-45c8-98bc-0f3900a4e3ee) accepts 7/9 cases with seven answer calls and five judge calls. The [focused table rerun](https://smith.langchain.com/o/32ee7fde-eac9-4caf-8d73-ecb088aa8048/datasets/28fb3bfb-604e-498e-b621-4d628421effb/compare?selectedSessions=eb89b7eb-3e36-4ab2-a59a-b9f720979d54) accepts 2/2, using two answer calls and the two unused judge calls.

Acceptance: The latest result for each of the nine cases passes every applicable workflow/privacy, retrieval, citation, public-source and judge score. This is cumulative acceptance, not one final all-nine experiment. Missing/failed scores still fail acceptance. Total approved paid attempts across all runs: **16 answer, 7 judge, 16 query-embedding invocations**, no automatic model retries.

Evidence: `data/evaluations/phase3-pdf-langsmith-v2.json`, `data/evaluations/phase3-pdf-langsmith-v3-table.json`, `data/evaluations/phase3-completion-v1.json`.

#### 12. Refresh synthetic acceptance and record completion

Outputs: 50/50 local cases and [50/50 LangSmith synthetic cases](https://smith.langchain.com/o/32ee7fde-eac9-4caf-8d73-ecb088aa8048/datasets/8856d232-2fec-4bea-acd4-bfb67b07e762/compare?selectedSessions=2e6e1d69-55ab-433a-a8df-97b9a8149da6) pass under extractive-v2 / local-screening-v3. Synthetic checks make no paid model calls. Completion records code hashes, per-case experiment provenance, approved call accounting and finite-coverage limitations.

Evidence: `data/evaluations/phase3-acceptance-v2.json`, `data/evaluations/phase3-langsmith-acceptance-v2.json`, `data/evaluations/phase3-completion-v1.json`.

### Planned next steps

1. Begin Phase 4 by reviewing the existing Supabase project, cloud-index schema and document/tenant authorization requirements.
2. Retain the Phase 3 local fixtures and LangSmith datasets as regressions for new sources and the later LangGraph workflow.
3. Keep broader semantic paraphrase support, full-book source review, new tool permissions and production operations as explicit future work; this training acceptance does not certify them.

Next inputs/decision: Phase 4 public LangChain retrieval and reviewed corpus activation; original PDF private. Phase 3 training acceptance is complete; there is no pending export approval or acceptance rerun.

## Phase 4: Supabase PDF pipeline and cloud retrieval

The [current access design](docs/PHASE4_DESIGN.md) implements the user's clarification: **public Q&A and approved citations, original PDF private**. Visitors require no login or owner assignment. Public reads are opt-in through `public_read=true` and active-revision RLS; trusted ingestion/admin jobs retain write control. The original-PDF route and private transfer proxy are removed. The approved public asset registry remains the citation authority. The public LangChain retriever and reviewed import are implemented; the nine-case LangSmith comparison is accepted and the configured API backend is now Supabase.

| Technology | Phase 4 role |
| --- | --- |
| LangChain | Model/embedding/retriever interfaces and checked sentence selection |
| LangGraph | Main workflow/state platform as orchestration expands; specialist graph remains Phase 7 |
| LangSmith | Cloud/local quality and citation comparisons before the retrieval switch |
| Postgres + pgvector + RLS | Reviewed public active chunks; private/staged/deleted data and all writes restricted |
| Supabase Storage | Private original PDF; previously approved public citation crops/tables |
| Existing FastAPI/HTTPX/Python/uv | Public read endpoints, existing gates, deadlines and trusted ingestion |

Configured project: ai_projects, Postgres 17.11, pgvector 0.8.2. The three introduced tables and four pre-existing checkpoint tables remain separate. Owner/share columns/rules are historical compatibility, not an MVP dependency. The current schema uses a publishable-key anonymous reader; LangGraph's Qozon workflow remains planned.

Historical executions below record the earlier owner/share design; step 6 supersedes its visitor access flow.

### Executed steps and verification

#### 1. Connect existing private Storage downloads

Processing: Recorded Storage integration

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
download_pdf()
```

Outputs: An authorized private PDF is streamed to a bounded local file for extraction; credentials remain backend-only.

Verification: Local downloader tests and the recorded actual PDF transfer exist. This is not directory SQL integration or automatic cloud index ingestion.

Evidence: `knowledge_base/pdf/downloader.py`, `tests/knowledge_base/pdf/test_downloader.py`, `README.md`.

#### 2. Publish the previously reviewed and approved source assets

Processing: Previously explicitly approved public Storage writes

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
Historical: prepare_publication.py / publish_reviewed_assets.py (retired). Current: python -m qozon_langchain.knowledge_base.pdf.publication --write-plan / --publish --plan <approved-plan>
```

Outputs: 146 summarized assets now resolve 242 public files / 25,164,548 bytes. The page-6 empty table is excluded. The original PDF remains private.

Verification: Saved verification confirms indexed links, anonymous byte checks and unchanged 2,451-chunk corpus/collection. Public approval applied to reviewed fingerprints, not arbitrary future uploads.

Evidence: `data/source-publication/publication-verification.json`, `data/pdf-assets/publication.json`, `data/source-publication/live-api-verification.json`.

#### 3. Draft the cloud index schema and document access

Processing: Current Supabase/LangChain documentation review, read-only catalog queries and local design files, October 12, 2026.

Outputs: `qozon_documents`, `qozon_document_access` and versioned `qozon_chunks`; 1,536-dimensional embeddings; owner/share RLS; authenticated read-only RPCs using `SECURITY INVOKER`; staged revision activation; private-source access and explicit handling of legacy public crops.

Verification: Catalog metadata only was read. No cloud schemas, buckets, source data or dependencies changed; no model or embedding calls occurred. Static design review covers role scope, non-recursive owner/share policies, authenticated identity, revision visibility and bounded search. SQL execution and access-denial tests remain the next implementation checkpoint.

Evidence: `docs/PHASE4_DESIGN.md`, `supabase/migrations/20261012195706_qozon_document_access.sql`, `phase-tracker/verification.json`.

#### 4. Apply and verify the document tables and access rules

Processing: User-authorized database setup, October 12, 2026. The user enabled pgvector before implementation.

Recorded execution:

```text
Supabase CLI 2.120.0: migration new qozon_document_access
Isolated PostgreSQL/pgvector validation: tests/database/phase4_access.sql
Supabase apply_migration: qozon_document_access, recorded version 20261012195706
Supabase execute_sql: the same 73 database assertions, transaction rolled back
Post-apply catalog, privilege, migration-history and security/performance advisor checks
```

Outputs: Three document tables with RLS; authenticated read-only table access; two bounded SECURITY INVOKER vector/keyword readers. Anonymous and unrelated users are denied. No source or vector import, package change, model call or LangSmith export occurred. The CLI-generated file was synchronized to the remote migration's recorded timestamp; the duplicate design SQL was retired.

Verification: **73/73 locally and 73/73 on Supabase** cover ownership/sharing, denied writes, absent identity, cross-user filters, revoked sharing, staged/deleted revisions, evidence text and limits. Fictional fixtures rolled back; zero documents/chunks/shares or test users remain. Local Postgres 16.14 used the official pgvector 0.8.2 module/script; cloud tests used actual Supabase 17.11 with the installed extension. Database-role/JWT tests do not establish HTTP token or private Storage access. No security advisor findings concern the new objects; pre-existing checkpoint/trigger findings remain documented in the report. New unused-index INFO notices are expected before import.

Evidence: `supabase/migrations/20261012195706_qozon_document_access.sql`, `tests/database/phase4_access.sql`, `data/evaluations/phase4-schema-access-v1.json`.

#### 5. Historical: implement and verify the private document proxy (superseded)

Processing: User-authorized API/access implementation, October 12, 2026; existing HTTPX and FastAPI, with no dependency additions.

Recorded execution:

```text
GET /documents and /documents/{uuid}: verified Supabase bearer token + RLS
GET /documents/{uuid}/source and /citations/{chunk_hash}/{kind}: canonical private proxy
Supabase CLI migration new + apply_migration: qozon_private_sources, then qozon_proxy_only_sources
52 API boundary cases; 22 local Storage-denial assertions
29 real Auth/Data API/Storage/API checks with fictional fixtures and cleanup
Full offline pytest: 568 passed, 1 skipped, 27 existing warnings, 12.70 seconds
Final cloud catalog and security advisor checks
```

Outputs: Request-scoped verified-user database clients; bounded metadata reads; private PDF/PNG/JSON responses from canonical references; buffered access/revision recheck and no-store headers. The privileged Storage client is separate and never reads database rows. The missing publishable key was appended privately to the existing configuration without replacing credentials.

Verification: Owner/shared API reads succeed; missing/forged tokens, unrelated users, revoked shares and inactive/deleted sources are denied. Real tests exposed a cached direct Storage GET after revocation, so the final corrective migration removed direct user Storage access. All 29 final HTTP checks pass with that policy. Three fictional users and three small files per run were removed; no source corpus was imported and no Auth users/documents/chunks/grants/test objects remain. Existing private PDF and approved public crops remain in their buckets. Previous failed reports/cache diagnostic are retained. Storage SQL-fixture calls failed at the connector request-state layer; actual HTTP checks provide the final cloud verification. No new-object security advisor finding; no model/embedding calls or LangSmith exports.

Evidence: `knowledge_base/documents.py`, `api/documents.py`, `api/dependencies.py`, `tests/api/test_documents.py`, `tests/database/phase4_private_sources.sql`, `supabase/migrations/20261012202749_qozon_private_sources.sql`, `supabase/migrations/20261012211850_qozon_proxy_only_sources.sql`, `data/evaluations/phase4-private-access-v1.json`, `data/evaluations/phase4-private-http-proxy-v2.json`.

Scope: These protected `/documents` endpoints are complete for this checkpoint. `/questions` remains the local Chroma demonstration; request-bound cloud question authorization and private citation attachment must be integrated with the cloud retriever. LangChain, LangGraph and LangSmith remain the main build/workflow/evaluation platforms. Production transfer concurrency remains unmeasured.

#### 6. Adopt public Q&A/approved citations and keep the original PDF private

Processing: User-selected public-access scope, October 12, 2026. Existing publication resolver and HTTPX client reused; no new packages.

Recorded execution:

```text
Supabase CLI migration new + apply_migration: qozon_public_qa_reads, version 20261012214522
Public-read opt-in and active-revision RLS; owner field optional; anonymous reader RPCs
Retire visitor Auth/token handling, private transfer client and original-PDF API route
37 public API boundary cases; 31 isolated local database assertions
26 real anonymous Data API/RPC/API checks plus approved asset byte hashes; fixtures removed
Offline pytest: 553 passed, 1 skipped, 27 existing warnings, 11.95 seconds
Final catalog/privilege checks and security advisors
```

Outputs: Visitors use no app account. Public document summaries and PNG/JSON/Markdown citation redirects use only the publishable anonymous database role and the verified public asset registry. Public rows require explicit opt-in and a complete active revision; private/pending/staged/deleted data is hidden. Anonymous writes, sharing rows, owner IDs and private PDF locator columns are denied. Original PDF bucket privacy and Storage RLS remain unchanged; there is no PDF download route. Owner/share schema is retained only for compatibility.

Verification: 37 API cases, 31 local SQL assertions and all 26 real HTTP checks pass. Test document/chunk records were removed. No accounts, files, original corpus imports, model/embedding calls or LangSmith exports were created. Current test count replaces the superseded 52-case private API suite with 37 public-contract cases; the other 516 tests remain passing. Already approved public asset URLs still resolve byte-for-byte. Final cloud index is empty, with the existing private PDF retained. No new-object security advisor finding; existing checkpoint/trigger notices remain in the report.

Evidence: `docs/PHASE4_DESIGN.md`, `knowledge_base/documents.py`, `api/documents.py`, `tests/api/test_documents.py`, `tests/database/phase4_public_access.sql`, `supabase/migrations/20261012214522_qozon_public_qa_reads.sql`, `data/evaluations/phase4-public-access-v1.json`, `data/evaluations/phase4-public-http-v1.json`.

#### 7. Connect one public LangChain cloud retriever

Processing: Existing LangChain BaseRetriever, Embeddings, HTTPX and publication resolver; no new packages.

Execution: `CloudPDFRetriever.ainvoke()/retrieve()`; API and existing LangSmith runner both call `build_retriever(settings)` with `QOZON_RAG_BACKEND=chroma|supabase`.

Outputs: Bounded anonymous vector/full-text RPCs, existing fusion/evidence gates, complete reviewed parent contexts, hash-checked approved image and canonical public citations. Cloud rows are rechecked before answer release; hidden/changed/mixed revisions withhold buffered answers. The backend reader never uses the ingestion secret.

Verification: 35 new fake/cached-vector boundary cases; full suite **588 passed, 1 skipped, 27 warnings**, 12.15 seconds. The local resolver/fusion is shared with Chroma. No dependency or graph service added.

Evidence: `knowledge_base/cloud.py`, `knowledge_base/pdf/retrieval.py`, `services/question_service.py`, `tests/knowledge_base/test_cloud.py`.

#### 8. Import, verify and publish the reviewed cloud index

Processing: Trusted Supabase backend writes using the existing ingestion key; cached vectors only.

Execution: `python -m qozon_langchain.knowledge_base.cloud_import --check`; `--import-reviewed`.

Outputs: 2,451 chunks (2,249 text, 128 image, 74 table), 146 approved asset references, all 1,536-dimensional cached vectors. The public contract excludes raw extraction files, local paths, private PDF locators, credentials and arbitrary URLs. No original PDF or new asset was uploaded.

Verification: Source/corpus hashes and approved fingerprints checked before writes; immutable duplicate-ignoring staging resumed after connection failures. Full text/metadata/float32-vector read-back matched before one conditional active-revision/public-flag update. Zero paid embedding/model calls. One public document and 2,451 active chunks; original bucket private, original object count one, Auth users zero, Storage user policies zero. No schema migration added.

Evidence: `knowledge_base/cloud_import.py`, `data/evaluations/phase4-cloud-index-v1.json`.

#### 9. Verify real anonymous cloud integration and prepare the quality comparison

Execution: Real HTTP public read/retrieval/API checks with existing fixed corpus vectors and a scripted extractive answer; existing LangSmith case validation against `evals/pdf_rag_cases_v5.json`.

Verification: **22/22 real checks pass**, including all 2,451 public text/metadata rows, private-locator/share denial, text/table/image context, approved assets, secret input blocking and absent PDF route. Nine quality cases validate locally. No paid calls or LangSmith exports ran; these checks establish integration only.

Evidence: `data/evaluations/phase4-cloud-http-v1.json`, `data/evaluations/phase4-langsmith-plan-v1.json`.

#### 10. Run the approved cloud comparison and correct the source evaluator

Processing: Explicit approval for nine cases and at most seven new answer, query-embedding and judge calls each, including the stated checked-content LangSmith export.

Execution: Existing LangSmith runner with `QOZON_RAG_BACKEND=supabase`, `evals/pdf_rag_cases_v5.json` and `project_qozon-phase3-pdf-v1`.

Verification: Seven answer cases passed correctness, groundedness, retrieval/citation and privacy metrics; both blocked cases passed. Four asset checks initially failed because the evaluator referenced Chroma's local record map. That assumption was removed: the evaluator uses recorded Evidence/source fingerprints for either backend. Changed-fingerprint regression passes.

Execution correction: Replay the same saved live responses in a new LangSmith experiment, rechecking anonymous asset bytes/hashes and deterministic scores while reusing the original seven quality judgments. **61/61 required scores pass; 9/9 cases accepted.** Zero new paid calls during source recheck. Initial report and experiment remain preserved. Total Phase 4 paid calls: **7 answer, 7 query embedding, 7 judge**; no automatic paid rerun.

Evidence: `data/evaluations/phase4-pdf-langsmith-v1.json`, `data/evaluations/phase4-pdf-langsmith-v2-sources.json`, `data/evaluations/phase4-langsmith-plan-v1.json`, `tests/evaluation/test_public_sources.py`.

#### 11. Select the accepted cloud backend and verify real API wiring

Execution: Set only `QOZON_RAG_BACKEND=supabase` in existing local configuration, preserving other settings. Verify startup dependency, `/health`, real anonymous `/documents` and absent original-PDF route.

Verification: CloudPDFRetriever is the configured API retriever; one public document is listed. Chroma remains available as the local fallback. Final full suite: **589 passed, 1 skipped, 27 warnings**, 12.24 seconds. API verification made zero paid calls. No new dependency, runtime script, schema migration or visitor account was added.

Evidence: `data/evaluations/phase4-cloud-default-v1.json`, `.env.example`, `README.md`.

#### 12. Verify document updates, withdrawal and revision rollback

Processing: Existing trusted importer, LangChain cloud retriever, public API and bounded RPCs; one isolated temporary document with six revisions. Fixed vectors and scripted answers; no new paid calls or uploads.

Execution: Real HTTP update/rollback/withdrawal checks; offline LangSmith SDK scoring with uploads disabled and run writes stubbed; 12 repeatable lifecycle regressions in `tests/knowledge_base/test_cloud_lifecycle.py`.

Verification: **59/59 real checks** and **59/59 offline SDK scores** pass. Incomplete/staged revisions stay hidden. Resumed updates activate only after full read-back; repeated imports add no duplicates. Rollback restores exact text/metadata/vectors and approved citation links while retaining both revisions. Competing activation, withdrawal/deletion during import and corrupted staged/prior payloads are rejected. Updates/withdrawal/deletion during generation withhold valid buffered old answers. Hidden documents/citations return 404, retrieval is empty for the isolated source and the model is not called. Anonymous writes/public management routes are unavailable.

Integrity: All fixture rows removed. Original full-payload SHA-256 and active revision match before/after; the actual public corpus still has 2,451 chunks. Original PDF private, original object count one, Auth users/grants zero, Storage user policies zero. No Storage write, model/judge/embedding call, LangSmith export, new runtime module, migration or dependency.

Limits: Controlled interleavings and fixed vectors; no arbitrary concurrent-load claim. Previously approved public asset files stay public after withdrawal; final access checks cannot recall delivered answers. The existing nine-case live quality acceptance was not rerun.

Final offline suite: **601 passed, 1 skipped, 27 warnings**, 12.63 seconds.

Evidence: `data/evaluations/phase4-lifecycle-http-v1.json`, `data/evaluations/phase4-lifecycle-integrity-v1.json`, `tests/knowledge_base/test_cloud_lifecycle.py`.

#### 13. Verify concurrency, deadlines and failure recovery

Processing: Existing LangChain retriever/service, asyncio/HTTPX, Supabase conditional activation and Uvicorn admission. LangSmith SDK scores offline outcomes; LangGraph remains the planned state/routing platform for additional sources.

Fix: Two lane-failure regressions exposed a waiting sibling after gather returned an error. Replace that pair with `asyncio.TaskGroup` to cancel/join sibling work before closing its client; normal ranking/evidence is unchanged. No new runtime module or dependency.

Verification: **33 real-cloud checks + seven local socket/admission checks** pass. Eight concurrent questions retain separate answers/citations; all eight old buffered answers are withheld after activation. Scaled three-second deadline and provider-timeout probes return safe 504s, clean up and recover on a subsequent request. RPC failures return safe 503s and the shared retriever recovers. Partial insert/lost activation replies resume without duplicates. A real two-publisher race yields exactly one winning activation. Uvicorn accepts eight normal socket requests; ten of a 24-request burst receive 503 with the 16-connection/task limit, then normal questions recover.

Recorded launch: Existing API command plus `--limit-concurrency 16`. The limit is per worker and requires that launch flag; it is not per-user rate limiting or a spending quota.

Platform scoring: **40/40 offline LangSmith SDK scores**, uploads disabled and run writes stubbed. No paid model/embedding/judge calls or new LangSmith/Storage exports. Earlier nine-case live quality acceptance remains recorded, not rerun.

Final suite: **612 passed, one skipped, 27 warnings**, 13.16 seconds; **11 new regressions**. Original corpus payload/revision unchanged, 2,451 active chunks, zero Auth users, one private original object, no Storage user policies. Fixture rows removed; temporary server stopped.

Limits: Controlled eight-request and overload probes, not a capacity/SLA estimate. Async cancellation cannot preempt synchronous CPU work or recall provider-side processing. Hosting, durable rate/cost limits and public release remain pending.

Evidence: `data/evaluations/phase4-resilience-http-v1.json`, `phase4-admission-http-v1.json`, `phase4-resilience-langsmith-offline-v1.json`, `phase4-resilience-integrity-v1.json` in the same directory; `tests/knowledge_base/test_cloud.py`, `tests/knowledge_base/test_cloud_lifecycle.py`.

#### 14. Prepare release checklist, hosting and request/cost limits

Processing: Local implementation and configuration verification; no deployment

Inputs: Existing public cloud API, authoritative approved citation registry and current official hosting/provider cost documentation.

Execution: Added one SQLite admission counter, enabled in the prepared release configuration. Atomically reserve before retrieval/generation: five attempts/IP/fixed UTC minute and 100 attempts/service/UTC day. Failure/cancellation keeps the slot; counter errors stop paid work. Created an allowlisted Docker context and optional Render Blueprint for one worker/instance, concurrency 16 and a persistent counter disk. Explained Render/Railway/VPS and every stack component in `docs/PHASE4_RELEASE.md`.

Verification: **621 passed, one skipped, 27 existing warnings**, 15.41 seconds; nine new admission regressions. Counter concurrency/restart/reset, fixed safe errors, no model/retrieval on rejection and ignored raw forwarding headers pass. Release registry's 146 assets/242 files preserve every canonical public link. Hosting YAML parsed; no ingestion secret/private-source locator in its environment. No paid calls, uploads, database writes, dependencies or Supabase migrations.

Release status: Hosting and monthly OpenAI cap are not selected/configured. Docker is unavailable locally; Linux image build, resource sizing and real-host proxy/persistent-disk/cloud/logging verification remain pending. Request allowance is a call-volume cap, not a dollar estimate. LangChain/LangGraph/LangSmith remain the main platforms, with the current PDF path linear. Public Q&A/approved citations remain public; original PDF excluded and private.

Evidence: `api/limits.py`, `tests/api/test_limits.py`, `Dockerfile`, `.dockerignore`, `render.yaml`, `release/publication.json`, `docs/PHASE4_RELEASE.md`, `data/evaluations/phase4-release-preparation-v1.json`.

#### 15. Prepare the confirmed Cloudflare React frontend connection

Processing: Local API/browser boundary implementation; no website deployment

Input: User-confirmed React website on Cloudflare at `https://srahimov.site`.

Execution: Add standard FastAPI CORS using lazily loaded exact-origin settings, GET/POST, Content-Type, no credentials and exposed Retry-After. Configure the prepared release for the confirmed origin. Document HTTPS chat POST, answer/source rendering, timeout/error handling and backend-only secrets. Clarify frontend hosting is settled while Python backend hosting remains pending; no Workers migration is assumed.

Verification: **630 passed, one skipped, 27 existing warnings**, 13.88 seconds. Nine browser regressions cover approved/rejected origins/methods/headers, safe answer/error access, preflight with no paid work or quota use, readable 429 Retry-After, public non-browser requests and absent original-PDF route. No paid calls, uploads, database/Cloudflare account changes or new dependencies. Existing local private .env unchanged.

Evidence: `api/app.py`, `core/config.py`, `tests/api/test_cors.py`, `.env.example`, `render.yaml`, `docs/PHASE4_RELEASE.md`, `data/evaluations/phase4-cloudflare-browser-v1.json`.

#### 16. Prepare the API contract and React integration client

Processing: Local API handoff; no backend deployment or paid calls

Input: Confirmed Cloudflare React website, existing Python API and release configuration.

Execution: Export OpenAPI directly from the app without reading credentials; document the actual fixed public error envelope, Retry-After and 307 approved-citation redirect. Deliver one small dependency-free browser client posting only the current question, enforcing 200 Unicode characters, normalizing empty sources and supporting cancellation/60-second browser timeout with no automatic retries. Record the four-step API/release plan and stack roles in the release guide.

Verification: **632 Python tests passed**, one skipped, 27 existing warnings, 13.28 seconds; **six JavaScript client checks passed**. Two new schema/HTTP contract regressions pass. Export matches app schema; original-PDF route absent. No paid calls, uploads, database/Cloudflare changes, new dependency, graph, queue or backend service. Actual backend HTTPS URL and live website connection remain pending.

Evidence: `release/openapi.json`, `release/qozon-api.mjs`, `tests/api/test_openapi.py`, `tests/api/test_chat_client.mjs`, `docs/PHASE4_RELEASE.md`, `data/evaluations/phase4-api-handoff-v1.json`.

#### 17. Check preferred LangSmith hosting against the free-plan assumption

Processing: Current official pricing/deployment-documentation review; no migration

Input: User prefers LangSmith as backend host, expecting free Developer hosting.

Verification: Published Developer plan is $0/seat/month with 5,000 base traces/month; Deployment is marked N/A. Plus is $39/seat/month and includes one small serverless deployment. Cloud quickstart requires Plus or above and an exported graph. Account-specific free entitlement/trial is not verified; clarification requested. Existing code/API/client, private-original boundary and evaluations remain intact. No subscription/deployment/paid-call/upload/code/dependency changes.

Account verification: The signed-in Plans and Pricing page shows Current plan Developer — Free and Deployment Requires upgrade. Plus displays $39/seat/month and one Serverless Small deployment included. Read-only check; no account changes. Evidence: `data/evaluations/phase4-langsmith-account-plan-v1.json`.

Next decision: Clarify hosting cost preference before preparing a migration. LangSmith remains preferred if an eligible plan/trial matches the user's cost constraint; current Developer evaluation use continues.

Evidence: `data/evaluations/phase4-langsmith-hosting-plan-check-v1.json`, [current pricing](https://www.langchain.com/pricing), [deployment prerequisites](https://docs.langchain.com/langsmith/deployment-quickstart).

#### 18. Document the Cloudflare Containers tech stack and rollout plan

Processing: Documentation-only architecture/implementation plan; October 13

Input: User requests a standard Python 3.12.14 Docker/Cloudflare Containers plan; existing API, client, registry and official current platform documentation.

Execution: Keep one Linux Python/FastAPI application and the main LangChain/LangGraph/LangSmith blueprint. Plan one small Worker/SQLite-backed Durable Object for HTTPS/routing/readiness and durable request quotas. Specify serving dependency slimming, trusted ingress/bypass checks, no-refund atomic counters, image measurement, private secrets, spending and hosted acceptance.

Verification: Current Cloudflare docs confirm Linux/amd64 container runtime, ephemeral container disk and durable object storage; published paid plan is $5/month minimum with additional metered usage. Current Dockerfile/project require Python 3.12.14; Docker command unavailable. Existing cloud API and prior 632 Python/six JavaScript checkpoint remain intact and were not rerun for this plan-only update. No runtime code, package, account, deployment, paid-call, upload or database changes.

Evidence: `docs/PHASE4_RELEASE.md`, `docs/PHASE4_DESIGN.md`, `data/evaluations/phase4-cloudflare-containers-plan-v1.json`. This plan supersedes the earlier pending LangSmith hosting preference; Developer evaluation use continues.

#### 19. Implement the selected TypeScript Worker/Durable Object and slim serving setup

Processing: Authorized implementation and offline preparation; October 13

Input: User selects TypeScript/Durable Objects and requests Phase 4 finalization, with payment activation announced only when ready. Existing Python API, reviewed cloud index, public/private boundary and locked dependencies.

Execution: Separate the ingestion dependency group while retaining its default local installation; make Chroma/BM25/Pillow ingestion imports lazy. Prepare one native-API/default-scheduling Worker/SQLite Durable Object, pinned npm tooling and max_instances=1. Reserve minute/day quotas before startup/paid forwarding; strip visitor admission/forwarding/auth/cookies; require the private edge secret in Python Cloudflare mode. Share readiness, retain slots on failure, bound deadlines, preserve manual citation redirects and forbid original/interactive-docs routes at the edge. Create no new AI orchestration/evaluation framework.

Verification: **639 Python tests pass**, one skipped, 27 existing warnings, 15.56 seconds; **21 Worker checks** and **six chat-client checks pass**. TypeScript passes. Wrangler dry-run validates/bundles with container rollout disabled and no upload. Fresh macOS serving install: **54 packages**, 113,185,649 installed-file bytes, API/cloud retriever startup and private-admission checks pass without ingestion libraries. Release registry matches 146 assets/242 files; build context/configuration privacy reviewed. Worker tests use real SQLite and scripted container/base class; Linux image/resource and actual hosted behavior are not proven. No paid calls, LangSmith exports, Supabase writes/Storage uploads, account/billing change or deployment. User selected Docker Desktop on this Mac; installation/running engine still pending.

Evidence: `cloudflare/src/index.ts`, `cloudflare/wrangler.json`, `cloudflare/package-lock.json`, `Dockerfile`, `pyproject.toml`, `uv.lock`, `tests/api/test_cloudflare_admission.py`, `tests/knowledge_base/test_serving_imports.py`, `cloudflare/test/worker.test.mjs`, `data/evaluations/phase4-cloudflare-implementation-v1.json`.

#### 20. Build Linux image and verify native Worker/container lifecycle

Processing: Authorized local Docker build and synthetic integration; October 13.

Input: User confirms Docker Desktop engine ready; existing serving image and native Worker/SQLite adapter.

Execution: Build Linux/amd64 Python 3.12.14 image, inspect actual files/packages and run native local Wrangler/Docker HTTP, concurrency, deadline, quota, sleep and full-runtime-restart checks. Correct the measured cold-start allowance to 15 seconds, preserve manual citation redirects across both bindings, clear completed deadline timers and restore inactivity policy on object restart.

Verification: October 13: Linux/amd64 Python 3.12.14 image built and inspected; 54 serving packages, private files/test overlay absent. Nine production-image checks and 25 native Worker HTTP checks pass. Eight overlapping questions peak at 176 MiB under quarter CPU/1 GiB; 45-second cancellation/recovery, atomic daily cap, idle restart and full Worker restart pass. 22 Worker/six client checks and TypeScript/dry-run pass; prior 639 Python checkpoint retained. Ready for Workers Paid activation; hosted release pending. Public Q&A/citations; original PDF private. Docker reports 365,322,261 image bytes; exported regular files total 267,138,958 bytes. Peak tested request memory 184,569,856 bytes; cold start 9.526 seconds. Daily cap allowed exactly three of 12 concurrent attempts and remained at 54 through full-runtime restart; rejection did not start the container. No paid calls, exports, Supabase writes/uploads or account/deployment changes. Production image retained, temporary checks stopped.

Evidence: `data/evaluations/phase4-linux-container-checks-v1.json`, `cloudflare/src/index.ts`, `cloudflare/test/worker.test.mjs`, `docs/PHASE4_RELEASE.md`. Local synthetic checks do not establish hosted capacity or live-provider acceptance.

#### 21. Deploy production secrets and pinned Cloudflare API

Processing: User-authorized production deployment; October 13.

Input: User confirms Workers Paid active and asks for production secrets/deployment; user will manage OpenAI cap.

Execution: Verify account and unused Worker name, prepare exactly four private runtime secrets, upload only allowlisted serving image and provision Worker/SQLite DO/private-network Basic container. Recover registry TLS uploads using a verified temporary official crane uploader over HTTP/1.1; pin the published digest. Run hosted public/citation/privacy/CORS/quotas and unchanged Worker-update retention probes.

Verification: October 13: Workers Paid active; production API at https://qozon-api.qozontech.workers.dev. Four private runtime secrets, one Basic/max-one container and immutable image deployed. 21 hosted public-read/citation/CORS/private-route checks pass; approved citation bytes match registry. Input-gated quota probes pass, and same-minute 429 survives unchanged Worker redeploy. No paid answers/embeddings, LangSmith exports, Supabase writes or original uploads. User manages OpenAI cap; paid answer smoke, React and full hosted lifecycle/rollback acceptance remain. The first retention probe was inconclusive; the final probe uses the same IPv4 connection/server UTC minute and preserves 429 through redeploy. Latest Worker version `e8780247-4fac-4dd4-8d76-242834829912`; container application `a030ccc1-d728-4a2a-ae0f-33563ef52a85`; immutable image digest `77292e288afc8981a08b7408e1d9fbbf1e3234c2238aa57c08c989b6496aba0d`. No website or DNS changes.

Evidence: `data/evaluations/phase4-production-deployment-v1.json`, `cloudflare/wrangler.json`, `docs/PHASE4_RELEASE.md`, `release/qozon-api.mjs`.

#### 22. Verify one approved hosted answer and active citation

Processing: User approves maximum one embedding/one answer; October 13.

Input: Prepared preface-purpose reviewed question; deployed public API, original PDF private.

Execution: Single hosted question POST, no retries, judges or LangSmith exports. Verify returned answer/schema, both purposes, page-4 citation, source sentence/hash and current revision with anonymous database reads.

Verification: HTTP 200 in **7.282 seconds**; both purposes returned; copied source sentences, citation page 4, evidence hash and active revision pass. One query embedding/one answer inferred from the fixed serving path; no additional paid call, original download or database write. One case only, not broad quality/capacity acceptance.

Evidence: `data/evaluations/phase4-hosted-answer-smoke-v1.json`, `data/evaluations/phase4-production-deployment-v1.json`.

#### 23. Connect existing React chat locally; publication approval pending

User supplied `/Users/sardoravaz/ReactNativeProjects/srahimov_site` and requested using its existing chat/response windows. The client now posts JSON questions to the production API, retains the layout, renders actual source/page fields and approved links, applies 200-character/no-retry/deadline handling, and removes unsupported upload/demo code and unused styles. Seven client checks and production build pass. Local browser replay verifies the saved answer/page-4 citation, Unicode limit, Enter submission, 429 wait and malformed-source safe error; no new paid calls or dependency. Temporary replay/preview stopped.

Automatic approval review rejected the attempted commit/push to `srahimov/srahimov` main because it triggers public Pages publication and explicit publication authorization was missing. No commit or push occurred; the concrete five-file change is ready and approval is pending. Evidence: `data/evaluations/phase4-react-integration-local-v1.json`.

#### 24. Publish approved React chat and verify actual browser/API boundary

User explicitly approved the reviewed five-file commit and push/publication. Commit `1150664b6526ea8e281e98eb09a1d1d617ccc71d` pushed to `srahimov/srahimov` main. No Git build appeared despite enabled Pages settings; the exact tested artifact was published to the existing `srahimov` Pages project with Wrangler, without changing Git settings. Deployment `a9387cd7-8d3c-4c78-9244-1a77fb504a8a` now serves the custom domain.

Verification: October 13: public React chat at https://srahimov.site/multimodal-rag is connected to the deployed Qozon API. Approved frontend commit 1150664 pushed and exact build published to existing Pages project; public JS bytes match. Seven client tests/build/local saved-answer-citation UI checks pass; actual browser JSON/CORS and model-blocked input error verified, no new paid calls. Prior 21 hosted reads/privacy/citation checks, durable quota retention and one live page-4 answer remain accepted. Q&A/approved citations public; original PDF private. User manages OpenAI cap; full hosted lifecycle/image rollback acceptance remains. The actual browser showed the backend's safe credential rejection after one synthetic input; no new embedding/answer/judge or LangSmith call. Successful answer/citation UI used the already approved response in local replay. Screenshot: `/private/tmp/qozon-react-chat-live.png`. No unrelated site/backend/secret/database changes. Evidence: `data/evaluations/phase4-react-publication-v1.json`.

### Planned next steps

1. User configures/chooses the monthly OpenAI hard cap; maintain private runtime secrets and stable admission key.
2. Complete full hosted idle/container recovery and distinct image rollback acceptance; preserve durable quota data and record final release ownership.
3. Review Git-to-Pages automatic build delivery separately: settings are enabled but this publication needed direct upload of the approved build.

## Phase 5: Supabase English business directory SQL

The SQL package remains a documented placeholder. No business-directory query integration or schema assumptions are implemented.

### Executed steps and verification

No working integration or external execution is recorded; future features are documented without placeholder modules.

### Planned next steps

1. Supply the actual directory schema, relationships, permitted English fields, access/tenant policy and representative business/product/service questions.
2. Configure a dedicated restricted read-only database role and LangChain SQL tools with an allowlisted schema; do not use unrestricted generated SQL.
3. Validate bounded SELECT queries, parameters/identifiers, result limits, statement timeouts and function/tool permissions before execution.
4. Add tested explicit source selection to the same API contract before automatic orchestration; retain the 200-character question cap.
5. Verify representative U.S. service/product businesses, products/services, privacy policy and source/citation correctness, plus denied writes/out-of-scope queries.

Next inputs/decision: Need actual schema and scoped database access. Existing Supabase Storage usage is separate. English only initially; the existing directory’s other five languages remain a later rollout.


## Phase 6: Wikipedia specialist

The web package remains a placeholder; Wikipedia ingestion/retrieval is not implemented.

### Executed steps and verification

No working integration or external execution is recorded; future features are documented without placeholder modules.

### Planned next steps

1. Supply the first approved English Wikipedia article links and agree on the refresh policy.
2. Restrict scheme/host/article scope and validate every redirect; do not enable general arbitrary browsing.
3. Normalize and privacy/screen source content as untrusted data, then chunk/index it with article, section, revision and retrieval-time provenance.
4. Expose explicit source selection and test cited answers/abstention before adding automatic routing.
5. Verify rejection of unapproved URLs and source instructions, then track changed/deleted revisions without stale citations.

Next inputs/decision: Need approved English links. Existing public PDF source links are citations, not a Wikipedia integration.


## Phase 7: LangGraph multi-agent orchestration

The current API has one question service with optional PDF retrieval. LangGraph may be installed transitively, but no multi-specialist graph, automatic source router or session memory is implemented.

### Executed steps and verification

No working integration or external execution is recorded; future features are documented without placeholder modules.

### Planned next steps

1. Finish/review SQL, PDF and Wikipedia specialist interfaces, keeping source authorization checks outside model discretion.
2. Generalize the current PDF evidence/citation contracts across source types; retain canonical application resolution and source freshness metadata.
3. Build a bounded LangGraph router over the one question API, with explicit multi-source decomposition and fallback/abstention behavior.
4. Parallelize independent retrieval; sequence dependent calls. Apply call/token/time budgets and cancellation/error handling in code.
5. Synthesize supported claims with citations, conflicts and insufficient-evidence responses; reuse the Phase 3 acceptance probes.
6. Introduce only temporary, isolated session/checkpoint memory initially and test authorization/privacy at every boundary before adding persistence.

Next inputs/decision: Need reviewed specialist contracts, mixed-source evaluation questions and a temporary memory/isolation policy. No long-term memory is assumed.


## Phase 8: Evaluation and operations

Explicit LangSmith observability, synthetic/cloud dataset checks, versioned RAG evaluations and local incremental recovery are implemented. Deployment readiness, API authentication/tenant isolation and full production operations are not complete.

### Executed steps and verification

#### 1. Verify explicit metadata-only observability and a synthetic cloud smoke dataset

Processing: Previously approved LangSmith network access; synthetic fake-model smoke

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
Historical: verify_langsmith.py (retired synthetic connectivity smoke)
```

Outputs: Explicit workflow/gate/retrieval/generation spans; automatic raw provider tracing suppressed. Three synthetic cloud cases passed deterministic scoring without OpenAI/book calls.

Verification: Saved synthetic traces and cloud feedback were read back. Checked-content uploads have separate consent and metadata-only remains the ordinary default.

Evidence: `core/observability.py`, `data/evaluations/langsmith-smoke.json`, `data/evaluations/observability-verification.json`.

#### 2. Preserve baseline feedback and version the reviewed book evaluation

Processing: Previously approved book-content upload + paid answers/embeddings/Terra judge

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
python scripts/evaluate_langsmith.py --run
```

Outputs: Original six-case baseline retained a preface reference/citation issue. Reviewed v2 preface and full six-case v3 evaluations passed their small-sample scores; secret/review cases made no answer-model calls.

Verification: Versioned datasets/reports preserve old failures rather than relabeling them. Successful sample scores are not whole-book grounding or privacy proof.

Evidence: `data/evaluations/langsmith-baseline-v1.json`, `data/evaluations/langsmith-preface-v2.json`, `data/evaluations/langsmith-six-cases-v3.json`.

#### 3. Verify reviewed source repairs and final public-source evaluation

Processing: Previously approved remote/paid two-case v4 reruns

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
python scripts/evaluate_langsmith.py --run --case-id contents-table --case-id physician-picture
```

Outputs: The latest public-source run checks two table/picture cases in the six-case dataset. All 18 feedback scores pass; every evaluated source link resolves verified public bytes.

Verification: Saved cloud verification is true and 18 feedback records were read back. This latest run covers two cases, not a new full six-case or full-book evaluation.

Evidence: `data/evaluations/langsmith-public-source-links.json`, `data/source-publication/publication-verification.json`.

#### 4. Document fresh regression status separately from behavioral gaps

Processing: Offline; freshly executed October 11

Inputs: Existing approved configuration and source files.

Recorded command/function:

```text
QOZON_RUN_LIVE_TEST=0 LANGSMITH_TRACING=false QOZON_LANGSMITH_TRACE_CONTENT=false .venv/bin/python -m pytest -q
```

Outputs: 446 passed, 2 skipped. Separately, Phase 3 baseline remains 18/25 with seven desired-behavior gaps.

Verification: The suite includes local service, ingestion, publication, incremental locking/recovery and SDK mocks; live/cloud evaluation was not rerun today.

Evidence: `tests/`, `phase-tracker/verification.json`.

### Planned next steps

1. Use LangSmith to version a broader quality/privacy/cost/latency acceptance dataset beyond the passing local Phase 3 fixtures; retain historical failures.
2. Add API authentication, tenant/session/document isolation and negative authorization checks before broader exposure.
3. Implement end-to-end source synchronization scheduling, job ownership, bounded retries, deadlines/cost controls and recovery/runbooks across source types.
4. Review the installed BM25 integration’s deprecation warning and select a supported replacement after checking current primary documentation; do not silently migrate it in a plan edit.
5. Define readiness/liveness, containers, backup/restore, resource limits and deployment acceptance; review the deployment target before release.
6. Add Russian, Uzbek, Kyrgyz, Kazakh and Tajik only after English baseline acceptance, with per-language retrieval, normalization, privacy and citation tests.

Next inputs/decision: Public PDF Q&A/citation scope is agreed. Need acceptance targets, source-specific release checks, operations ownership and deployment destination. LangSmith connectivity and passing sample scores are not production readiness.

## Cross-phase boundaries

- Each new question is capped at 200 original Unicode characters, including spaces/punctuation. Input validation precedes normalization; context/output budgets are separate.
- The selected input/output policy redacts five built-ins and selected custom types. Names are deliberately preserved; coverage gaps are explicit. Secrets block separately.
- Model outputs are buffered. Citation-ID resolution verifies canonical references, not claim-to-evidence entailment; Phase 3 covers that gap.
- Local OCR, summaries, embeddings, vector updates, public uploads and evaluations are distinct jobs with distinct privacy/authorization/cost implications.
- The original PDF is private. Only previously reviewed fingerprint-approved crop assets are in the recorded public publication registry.
- LangSmith defaults to metadata-only explicit spans. Previously authorized checked-content evaluations do not authorize future unrestricted trace uploads.
- Common PII, GDPR and HIPAA tables remain training references in the tracker, not detector completeness or compliance certification.
- Browser notes/status/checks retain their original localStorage key and IDs and remain independent from implementation status.
- The localhost tracker serves only the phase-tracker directory; it does not serve the project `.env`, private data directory or credentials.
