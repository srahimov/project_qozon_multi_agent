# Qozon Multi Agent

This separate project starts from the Qozon multimodal RAG backend. The agentic
synthesis workflow is planned; the current implementation still uses extractive
answering. Its copied Cloudflare configuration targets the existing Qozon API.
Publishing this repository does not deploy it. Configure separate Cloudflare
resources before deploying it as an independent application.

A LangChain question API with local/cloud PDF retrieval, approved citations and input/output checks.

LangChain, LangGraph and LangSmith are the main platforms for building and testing
the project: LangChain for models, retrieval and tools; LangGraph for the planned
bounded workflows; LangSmith for tracing, datasets and evaluations. Keep local
Python checks and pytest small; use these platforms instead of adding parallel
custom orchestration or evaluation frameworks. LangGraph is still planned.

## Public repository

[Try the chat](https://srahimov.site/multimodal-rag) ·
[API contract](release/openapi.json) · [Project blueprint](PLAN.md)

This repository contains the backend, Cloudflare Worker and Durable Object,
database migrations, tests, evaluation case definitions and deployment guides.
The React website is maintained separately in
[srahimov/srahimov](https://github.com/srahimov/srahimov).
Credentials, the original PDF, extracted corpus, embeddings, generated reports,
local environments and deployment caches are excluded. Historical report paths
under `data/` refer to local execution evidence, not bundled public files.

```sh
git clone https://github.com/srahimov/project_qozon_multi_agent.git
cd project_qozon_multi_agent
cp -n .env.example .env
uv sync --locked
uv run --locked pytest -q
```

Run commands from this repository's root, `project_qozon_multi_agent`, called `project_Qozon` in the original
training notes. Configure your own provider and database credentials privately
before making live requests. A clone does not include the deployed document
index. For the demo's approved public citation registry, use
`QOZON_RAG_PUBLICATION_MANIFEST=release/publication.json`; the original PDF stays
private. Deploying your own instance also requires your own Cloudflare resources
and container image reference; the checked-in deployment describes the live demo.

Production LangSmith tracing is now enabled in `qozon-production`. It records
explicit workflow steps, timing, model names, token usage and citation references;
question, answer and evidence text remain excluded. Local tracing defaults off.
The API key is stored as a Cloudflare secret and forwarded only to the Python
container. No automatic paid production judge is configured. LangGraph workflow
orchestration remains planned.

## Run locally

From `project_qozon_multi_agent`:

```sh
uv sync --locked
uv run --locked uvicorn qozon_langchain.api.app:app --host 127.0.0.1 --port 8000 --limit-concurrency 16 --no-access-log
```

Configure credentials privately in `.env`; use `.env.example` for the setting names.
Questions require `OPENAI_API_KEY` and a positive `QOZON_OUTPUT_MAX_TOKENS`.
Enable the existing local PDF index with `QOZON_RAG_ENABLED=true` and its matching
chunk/vector directories. Environment variables override `.env` values.
Never print credentials or commit `.env` or private `data/` contents.

- `GET /health`: configuration and local index readiness; no provider authentication check.
- `POST /questions`: `{"question": "Your question"}` → checked answer and optional sources.
- `GET /documents` and `GET /documents/{id}`: reviewed public document summaries; no visitor account needed.
- `GET /documents/{id}/citations/{chunk_hash}/{image|structured|text}`: redirect to a verified approved PNG/JSON/Markdown citation asset.
- `/docs`: interactive API documentation. Submitting a question may make paid provider calls.

Document reads use `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` on the backend,
with the anonymous database role. Visitor bearer tokens/cookies are not used.
Only documents marked `public_read=true` with a complete active revision are
visible. Index publication and writes are restricted to trusted ingestion/admin.
There is no original-PDF download route. Its `pdf_rag` bucket stays private;
`SUPABASE_SECRET_KEY` remains for backend ingestion/publication only.

Approved citations reuse the existing verified public asset registry. Unreviewed,
changed or invented links are rejected. The original PDF is never a citation
asset. Restart the API after code/configuration changes. The LangChain cloud retriever is connected through `QOZON_RAG_BACKEND=supabase`;
`supabase` is now the configured default after nine-case LangSmith acceptance;
`chroma` remains available for local use. The public cloud index contains 2,451 verified chunks and reused vectors.
No app-user ownership setup is required.

Each question is limited to **200 original Unicode characters**, including spaces
and punctuation. The shared workflow cancels waiting async work after 45 seconds;
provider requests also have their own timeout. Generation and retrieval budgets
are separate. Synchronous CPU work cannot be preempted by this deadline.

## Request flow

```text
API → input checks → LangChain local/cloud retrieval → LangChain model
    → buffered output/evidence checks → cloud access recheck → approved citations
```

The input gate normalizes text, screens selected instruction patterns, blocks
selected secrets, and applies the configured local PII policy. Rejected/held input
never reaches the answer model. Output is buffered and checked before release.
Errors use safe categories rather than echoing raw input or provider responses.

For PDF answers, LangChain structured output selects source sentence IDs. The
application copies those sentences and attaches citations; unknown IDs are
rejected. This avoids asking the model to recreate exact source wording.

PII coverage is deliberately limited. Names remain preserved by the training
policy; text detectors do not inspect image pixels. Current evidence verification
is conservative and extractive: unsupported paraphrases can be withheld. It is
not a general factual verifier or compliance guarantee.

## Code layout

| Area | Responsibility |
| --- | --- |
| `api/` | HTTP routes, schemas, lazy dependency construction |
| `services/question_service.py` | The question workflow |
| `security/` | Local input/output, PII, secrets and evidence checks |
| `llm/` | LangChain model adapters and prompts |
| `knowledge_base/pdf/` | Extraction, approved asset processing, indexing, retrieval and publication |
| `knowledge_base/documents.py` | Public document summaries and approved citation links |
| `core/` | Lazy configuration and explicit LangSmith observability |
| `evaluation/` | Offline behavioral probes and LangSmith scoring |

SQL, Wikipedia and multi-agent features are planned in [PLAN.md](PLAN.md).
They have no empty implementation placeholders in the current package.

## PDF maintenance

Ingestion is separate from questions. The API reads an existing index; it never
extracts or reprocesses the book for each question. Existing source fingerprints,
summary/cache formats, index data and resumable checkpoints are retained.

```sh
# Local extraction using the configured PDF source:
uv run --locked python -m qozon_langchain.knowledge_base.pdf.extraction_job

# Process an explicitly reviewed asset plan; makes paid table/image calls:
uv run --locked python -m qozon_langchain.knowledge_base.pdf.processing_job --plan data/pdf-summaries/processing-plan.json

# Preview a local incremental index update:
uv run --locked python -m qozon_langchain.knowledge_base.pdf.incremental

# Apply only reviewed changes; cache misses may make paid embedding calls:
uv run --locked python -m qozon_langchain.knowledge_base.pdf.incremental --apply
```

Tables and pictures use one processor in `processing.py`: source approval and
local checks → model → output checks → one saved summary. Successful results are
cached. Locks and atomic writes protect resumable jobs and the committed index.
Source changes need renewed fingerprint review; do not blindly retry an ambiguous
interrupted provider call. Original data remains under `data/`.

## Source publication

One module handles inventory, plan preparation and explicitly approved uploads:

```sh
# Local inventory; no Storage calls:
uv run --locked python -m qozon_langchain.knowledge_base.pdf.publication

# Prepare a fingerprint-reviewed plan; new selections are not auto-approved:
uv run --locked python -m qozon_langchain.knowledge_base.pdf.publication --write-plan

# Only after the plan has explicit public-upload approval:
uv run --locked python -m qozon_langchain.knowledge_base.pdf.publication --publish --plan data/source-publication/publication-plan.json
```

The publisher checks reviewed fingerprints, never overwrites objects, and verifies
public bytes before recording citation links. This publishes reviewed source
assets, not the original private PDF. Preparation and publication are separate
mutually exclusive actions.

## Reviewed cloud index

The importer reuses all existing embeddings, validates source hashes and approved
asset fingerprints, and uploads only checked text plus allowlisted metadata.
Staging stays hidden. Complete row/vector read-back precedes one conditional
update of the active revision and public flag. Existing rows are immutable;
interrupted imports resume without overwriting them. No PDF is uploaded.

```sh
# Local validation only; no network or paid calls:
uv run --locked python -m qozon_langchain.knowledge_base.cloud_import --check

# Trusted backend import/publication (requires the private ingestion key):
uv run --locked python -m qozon_langchain.knowledge_base.cloud_import --import-reviewed

# Select the cloud API backend (accepted for this corpus); no visitor login:
QOZON_RAG_BACKEND=supabase uv run --locked uvicorn qozon_langchain.api.app:app --host 127.0.0.1 --port 8000 --limit-concurrency 16 --no-access-log
```

Cloud reads send the publishable key only. The LangChain retriever combines exact
pgvector and Postgres full-text RPC results using the existing rank fusion. It
keeps complete reviewed parent context, one hash-checked approved image and the
existing evidence contract. Anonymous rows are rechecked before the buffered
answer is released. Withdrawal/revision changes withhold the answer; already
published asset files remain public. `GET /health` reports cloud configuration,
not remote readiness. The current index report is
`data/evaluations/phase4-cloud-index-v1.json`.

The same LangSmith runner selects either backend through `QOZON_RAG_BACKEND`.
The approved nine-case cloud comparison passes. It used seven answer, seven
query-embedding and seven judge calls. A Chroma-specific source-evaluator assumption
was corrected, then the saved answers and original judgments were replayed with
new anonymous asset-byte checks; this added zero paid calls. All 61 scores pass.
See `data/evaluations/phase4-pdf-langsmith-v2-sources.json` and the retained initial
report/experiment. The original PDF stayed private and images stayed out of LangSmith.

## Document updates, withdrawal and rollback

Updates use the same reviewed importer: prepare the new checked local corpus and
matching cached vectors, then import it. Pending chunks stay hidden until complete
read-back succeeds. The final update checks the expected prior revision and public
flag, so a competing activation, withdrawal or deletion interrupts publication.
Repeated imports add no duplicates; prior revisions remain stored for rollback.

Rollback uses the same importer with the previously reviewed local corpus and
matching vector cache restored. It verifies that old payload again before activating
it. A corrupted prior/staged payload is withheld rather than overwritten. Save
versioned `--report` outputs to retain revision history.

Withdrawal is a trusted backend change of `qozon_documents.public_read` to false;
soft deletion sets `deleted` to true. Both hide the document/chunks from anonymous
reads and make API citation redirects return 404. An in-flight answer is withheld
by the final evidence check. Public readers have no management/write endpoint.
Already approved public asset files remain public after withdrawal.

**59 real lifecycle checks**, **59/59 offline LangSmith SDK scores** and **12 new
regression tests** pass. One temporary document exercised six revisions; all test
rows were removed. The actual 2,451-chunk payload/revision is unchanged and the
original PDF remains private. No paid calls, Storage writes, LangSmith uploads,
new runtime module, schema change or dependency was added. See
`data/evaluations/phase4-lifecycle-http-v1.json` and
`data/evaluations/phase4-lifecycle-integrity-v1.json`.

## Concurrency, deadlines and failure recovery

| Part | Plain explanation | Implementation |
| --- | --- | --- |
| Concurrency | Several questions can wait for network work at the same time. Each keeps its own answer and citations. | FastAPI/Uvicorn, asyncio and the LangChain cloud retriever. The documented launch command limits connections/tasks to 16 per worker. |
| Deadlines | A slow question eventually stops waiting and returns a safe 504. No partial answer is released. | 45-second cooperative question deadline; 30-second LangChain model timeout; HTTPX reads 10 seconds/connect 5 seconds. |
| Failure recovery | A later request can succeed after an outage. An interrupted index import can resume from stored rows. | Safe error categories, no automatic paid answer retries, bounded retries of reads/immutable inserts, full read-back and conditional Postgres revision activation. |

The two retrieval lanes now use `asyncio.TaskGroup`: when one fails, its sibling
is cancelled and joined before the client closes. Two regression probes failed
with the former gather behavior and pass with this small change.

Verification: eight real cloud questions overlap with separate source IDs; all
eight old answers are withheld after a revision change. Deadlines, cancellation,
RPC/model failure recovery, partial inserts, lost activation replies and a real
two-publisher race pass. **33 cloud checks + 7 local socket/admission checks** and
**40/40 offline LangSmith SDK scores** pass, alongside **612 tests**. The 24-request
socket burst returned 10 busy responses and then recovered. Probe answers/vectors
were scripted; these are controlled checks, not a paid-model capacity/SLA estimate.

The Uvicorn limit is per worker and counts connections/tasks, not users or requests
per minute. It is active when the documented launch flag is used; external process
launchers must carry that setting. Persistent per-client/day limits are implemented;
hosting and provider spending caps await release configuration. Timeouts cancel cooperative async work; synchronous
CPU work and provider-side processing after submission are not preempted.

LangChain remains the model/retrieval platform, LangSmith the evaluation/tracing
platform, and LangGraph the planned workflow/state/routing platform for additional
sources. The PDF path stays linear. No new graph service, queue, dependency or
schema was added. Q&A and approved citations remain public; the original PDF and
its location remain private. The original 2,451-chunk payload/revision is unchanged,
all fixture rows are removed and the temporary socket server is stopped.

Reports: `data/evaluations/phase4-resilience-http-v1.json`,
`phase4-admission-http-v1.json`, `phase4-resilience-langsmith-offline-v1.json` and
`phase4-resilience-integrity-v1.json` in the same directory.

## Phase 4 release preparation

Selected hosting: **Python 3.12.14 in Docker on Cloudflare Containers**, with one
TypeScript Worker and SQLite-backed Durable Object. The adapter and durable request
allowances are implemented and locally verified. The [release guide](docs/PHASE4_RELEASE.md#cloudflare-containers-stack-and-implementation-plan)
records completed work and the Docker → payment → deployment → hosted acceptance
sequence. LangChain, LangGraph and LangSmith remain the main AI platforms;
LangGraph orchestration remains planned. Render is retained as an alternative.

Docker installs serving dependencies only; ordinary `uv sync --locked` retains
local ingestion/development packages. A fresh serving environment has 54 packages
and passes API startup/cloud-retriever/private-admission checks without local PDF,
Chroma, OCR or image-ingestion libraries. The Linux/amd64 image is now built and inspected; private files and the test overlay are absent.

The Worker exposes public Q&A/documents/approved citations, exact-origin browser
access for `https://srahimov.site`, and quota-free preflight. The stable Durable
Object reserves **5 attempts/IP/fixed UTC minute** and **100/service/fixed UTC day**
atomically before forwarding. Failures retain their slot. Stored counters contain
no question text/raw IP. The Python cloud mode requires private edge admission;
local mode still uses a persistent SQLite disk. No visitor login or React secret.

The image context excludes `.env`, `data/`, the original PDF and ingestion secrets;
the public 146-asset/242-file registry matches the authoritative copy. Original
PDF access remains private. Local preparation made no cloud changes; the later
authorized deployment creates the Worker/DO/container and uploads only runtime
secrets/source image. No original upload or LangSmith export accompanies it.

**Verification:** 22 Worker and six chat-client checks pass; TypeScript and
Wrangler dry-run pass. Prior Python checkpoint: 639 passed, one skipped; Python
source unchanged during these container checks. Nine production-image checks and
25 native local Worker HTTP checks pass. Eight overlapping questions peak at
176 MiB under quarter CPU/1 GiB; the 45-second deadline cancels and recovers.
Atomic quotas survive idle shutdown and full Worker restart. These tests use
synthetic providers, with no paid calls. See
`data/evaluations/phase4-linux-container-checks-v1.json`.

**Production API deployed:** [https://qozon-api.qozontech.workers.dev](https://qozon-api.qozontech.workers.dev).
Workers Paid is active. Five runtime secrets are stored privately, including the
subsequently added LangSmith key; one Basic
container is pinned by image digest. Hosted anonymous reads, approved citation
redirects/bytes, exact-origin CORS and private-route checks pass. The user manages
the OpenAI monthly cap; it was not configured or verified here. The approved live preface answer passes in 7.282 seconds with verified page-4
citation/current source; one embedding/one answer, no judge/LangSmith export.
The [public React chat](https://srahimov.site/multimodal-rag) is now published and
connected. Its build/seven client checks/local saved-answer UI checks and actual
browser/API input-gate verification pass, with no new paid calls. Full hosted
lifecycle/rollback operations acceptance remains.

API handoff: [OpenAPI contract](release/openapi.json),
[React chat client](release/qozon-api.mjs) and [release guide](docs/PHASE4_RELEASE.md).
The actual site client posts only JSON questions to the API, without credentials,
files or conversation history. It displays source names/pages and approved links.
Frontend source: `/Users/sardoravaz/ReactNativeProjects/srahimov_site`, commit
`1150664`. Exact build deployed to the existing Pages project; Git auto-build
delivery was not observed. See `data/evaluations/phase4-react-publication-v1.json`.
`wrangler.json` pins the uploaded image: Python/dependency changes require a new
Linux build, image push and pinned digest before deploying. Worker-only updates
can use `--containers-rollout none`.

## Tests and evaluation

```sh
# Offline tests, including fake-model API and ingestion cases:
uv run --locked pytest -q

# Dependency-free React handoff client checks; no network calls:
node --test tests/api/test_chat_client.mjs

# Local synthetic Phase 3 behavior report; no paid calls or uploads:
uv run --locked python scripts/evaluate_phase3_local.py --cases evals/phase3_synthetic_cases_v2.json --baseline --output data/evaluations/phase3-acceptance-v2.json

# Validate the current LangSmith case definitions locally:
uv run --locked python scripts/evaluate_langsmith.py
```

The two scripts are ongoing evaluation tools. The Phase 3 script's `--cloud`
uploads fictional fixtures and scripted scores to LangSmith without model calls.
The PDF script's `--run` / `--sync` are explicit remote operations; `--run` can
make paid calls and upload checked book content. Use `--output` for a versioned
report. Missing or failing required scores fail acceptance. Ordinary tests disable
LangSmith tracing and use synthetic data.
Metadata-only tracing is the application default; checked-content uploads require
separate approval. The output gate cannot sanitize data already sent upstream.

Phase 3 training acceptance is complete: 50/50 local and LangSmith synthetic cases,
9/9 live PDF cases across a full run and focused reruns. The historical Phase 3
checkpoint passed 516 offline tests.
See `data/evaluations/phase3-completion-v1.json` for results, experiment links and
approved call accounting. This sample does not establish whole-book or production
security accuracy. The
extractive policy deliberately withholds even valid paraphrases and equivalent
number formatting; it accepts complete supported source sentences. SQL, web,
shell and write tools are unavailable to the QA model, and tool-call replies are
rejected. LangGraph orchestration remains in Phase 7. Phase 4 document tables
and public-read RLS are applied. The reviewed cloud index and LangChain adapter
pass 22 real HTTP integration checks using fixed cached vectors and a scripted
answer. The retained Python suite checkpoint passes 639 tests; 22 Worker checks and six JavaScript client checks also pass. Cloud acceptance is 9/9; Supabase is the configured API backend.

The one-off connectivity checks, hardcoded two-source repair script, duplicate
single-picture pipeline and unused future-feature modules were retired. Their
results and original data are retained. See [execution history](docs/EXECUTION_HISTORY.md)
for old checkpoints; its old commands are historical, not current entry points.

[Current phase plan](PLAN.md) · [Local phase tracker](http://127.0.0.1:8894/index.html)

[Phase 4 cloud index and access design](docs/PHASE4_DESIGN.md) ·
[Applied document migration](supabase/migrations/20261012195706_qozon_document_access.sql)
