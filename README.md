# Qozon Multi Agent

This fork contains execution code only. **LangSmith is the sole external platform
for LLM evaluations, observability and monitoring.** No local test suites,
fake-model runners, quality judges, evaluation scripts or custom monitoring
modules are retained here. Application privacy, citation/schema, source-access,
request-limit and deadline controls remain part of execution.

The application uses real LangChain agents: a user-facing supervisor and a PDF
subagent exposed as a tool. LangGraph is LangChain's internal runtime; this fork
has no custom graph. The live code path is now:

`POST /questions → single input boundary → supervisor PII hooks → PDF tool → supervisor PII hooks → answer/citations`

The input boundary sanitizes once, screens the request and blocks credentials
before constructing or invoking the supervisor. The PDF delegation wrapper uses
the PII-checked question unchanged. No agent repeats input sanitization.

The PDF tool retrieves up to four keyword and four semantic matches from Supabase
PostgreSQL, deduplicates them, synthesizes a cited answer in one model call and
validates citation structure and source access. The supervisor copies that result
through its output PII hooks without another model rewrite. The normal successful
path uses one routing call, one PDF synthesis call and one query embedding.
No support-review judge or extractive answer adapter remains.

The API returns the same answer-and-sources contract with the total request
deadline, admission limits and safe error responses retained. The configured
factory loads the real Luna client and cloud retriever lazily after input approval.
This integration was reviewed statically. No local tests or model calls were run
for the current version. Historical live-run reports predate this version and
are not acceptance evidence for it.

The original Qozon project and public deployment are separate. This fork targets
its own `qozon-multi-agent-api` Worker, container application and Durable Object
namespace. Publishing GitHub changes does not automatically deploy it.

## Blueprint

[Main blueprint](PLAN.md) · [Agent file plan](docs/MULTI_AGENT_PLAN.md) ·
[API contract](release/openapi.json)

- `agents/`: supervisor, PDF agent and delegation tool.
- `middleware/`: standalone custom PII middleware.
- `api/` and `services/`: HTTP interfaces and buffered request execution.
- `knowledge_base/`: PDF extraction, reviewed indexing, retrieval and publication.
- `llm/model.py`: configured LangChain client construction.
- `llm/adapters.py`: approved offline table/image ingestion adapters.
- `security/`: request privacy, credential, display and citation/access controls.
- `core/`: application settings; no custom observability implementation.
- `cloudflare/`: Worker, container routing and persistent request allowances.
- `supabase/`: database access rules and migrations.
- `release/`: public API contract and approved citation registry.

The removed testing/evaluation/monitoring code and datasets are preserved outside
this project in a local reference folder. Historical execution records remain in
PLAN.md and supporting documents; old test/evaluation commands are superseded.
Credentials, the original PDF, extracted corpus, vectors and local reports remain
private and excluded from Git.

## Local execution

```sh
git clone https://github.com/srahimov/project_qozon_multi_agent.git qozon_multi_agent
cd qozon_multi_agent
cp -n .env.example .env
uv sync --locked
uv run --locked uvicorn qozon_multi_agent.api.app:app --host 127.0.0.1 --port 8000 --limit-concurrency 16 --no-access-log
```

Configure provider/database secrets privately using .env.example. Normal serving
requires the OpenAI key, output budget and reviewed Supabase index configuration.
The original PDF remains private; public Q&A uses approved evidence and citations.

Native LangSmith integration traces model calls to `qozon-multi-agent-production`
with 100% sampling. Client factories load local `.env` settings for the SDK while
preserving Cloudflare's injected environment. Inputs and outputs remain hidden.
Do not add a separate evaluator, trace collector, metric exporter or monitoring
service to the application. Manage evaluation and monitoring through LangSmith.

## Deployment

Standard Python 3.12.14 runs in the Docker image with FastAPI and Uvicorn. The
Cloudflare TypeScript Worker and Durable Object handle ingress, routing and
persistent quotas. Supabase hosts PostgreSQL with pgvector and full-text search.
The React website is maintained separately; deploying this API does not switch
the website away from the original API.

`cloudflare/wrangler.json` selects the separate Worker and pins its published
Linux/amd64 image by immutable digest. The image is built from the root
`Dockerfile` and stored in Cloudflare's registry. `.dockerignore` excludes
credentials, private corpus and local environments. Runtime credentials are supplied separately as Worker
secrets through the ignored, private `cloudflare/.env.deploy` file:

```sh
cd cloudflare
npm ci
npm run deploy -- --secrets-file .env.deploy
```

For a future code release, first build and upload a new image using
`npx wrangler containers build .. --tag qozon-multi-agent-api:YOUR_RELEASE --push`
from `cloudflare/`, then update `containers[0].image` in `wrangler.json` to the
published image digest before deploying. A deploy alone reuses the pinned image.

Current image contains application revision `ce016cb` and is published at
`registry.cloudflare.com/b0668461560fc6ead1ad55345b3437c4/qozon-multi-agent-api:ce016cb`.
Its digest is `sha256:beb84196cb0799fd88037f50ed4730efb84d326efd62d18afd5354b6db198e0d`.
The separate Worker is deployed at
https://qozon-multi-agent-api.qozontech.workers.dev using version
`e6f363d5-e887-48e2-bb0f-d26cc70ef23c`. All five approved runtime secrets are
installed. After initial provisioning, `/health` returned HTTP 200 and Cloudflare
reported one healthy Basic container. The endpoint confirms configuration and
startup; provider connectivity and generation quality were not checked. No local
tests, paid model calls or LLM evaluations were run for this release.

Required secret names: `OPENAI_API_KEY`, `SUPABASE_URL`,
`SUPABASE_PUBLISHABLE_KEY`, `LANGSMITH_API_KEY`, `QOZON_QUESTION_LIMIT_KEY`.
Use a separate randomly generated admission key of at least 32 characters.
The Supabase reader uses existing approved public evidence; no database migration
or privileged ingestion key is needed for serving.

The configured limits are one Basic container (quarter vCPU, 1 GiB memory),
300-second inactivity timeout, five attempts per IP per minute and 200 attempts
per UTC day across this Worker. Its counters are separate from the original API.
Both applications share the Cloudflare account's paid-plan allowances.

Native LangSmith tracing targets `qozon-multi-agent-production` with inputs and
outputs hidden and `LANGSMITH_TRACING_SAMPLING_RATE=1.0`. Supervisor and nested PDF
model calls use LangChain's built-in tracing. The embedding client's sync and
async provider requests use LangSmith's native `traceable` SDK with the embedding
run type. This also covers actual indexing requests; cache hits make no paid call.
Table/image ingestion calls inherit native LangChain tracing as well. No path
disables nested tracing or clears callbacks. A normal answer produces one routing
LLM call, one embedding request and one PDF synthesis LLM call. Generation-quality
acceptance remains in LangSmith. No separate monitoring module or evaluator is
included.
