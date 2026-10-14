# Phase 4 release checklist and hosting

Updated October 13, 2026. **Workers Paid is active and the production API is
deployed at https://qozon-api.qozontech.workers.dev. Hosted anonymous document,
approved-citation, exact-origin CORS and private-route checks pass. The approved live answer
smoke also passes. The existing React chat is published and connected at
https://srahimov.site/multimodal-rag; remaining operations acceptance is tracked separately.**
The user will manage the OpenAI monthly spend cap. No cap was selected or verified
here. No LangSmith export, Supabase write or source Storage upload accompanied deployment.

Q&A and approved citations stay public, with no visitor login. The original PDF
stays in private Supabase Storage, outside the image, with no download endpoint.
Ingestion credentials remain on the trusted ingestion machine.

## Cloudflare Containers stack and implementation plan

One TypeScript Worker receives public HTTPS requests. One SQLite-backed Durable
Object reserves question allowances and manages one container. Python/FastAPI
keeps the existing LangChain retrieval, model and buffered evidence/privacy checks.
LangGraph remains the main planned workflow platform; LangSmith Developer remains
our evaluation platform. No second AI workflow framework or queue was added.

| Component | Implementation |
| --- | --- |
| React website | Existing Cloudflare website at `https://srahimov.site`; supplied chat client awaits the hosted API URL. |
| Python API | Standard CPython 3.12.14, FastAPI/Uvicorn, one worker and concurrency limit 16. |
| AI platforms | Existing LangChain retrieval/model path; LangGraph planned orchestration; LangSmith accepted evaluations and permitted tracing. |
| Reviewed index/files | Existing Supabase pgvector/RLS and approved public citations; private original PDF. |
| Packaging | `Dockerfile`, existing uv lock, serving-only dependencies. Local ingestion packages remain in the default `ingestion` group. |
| HTTPS adapter | `cloudflare/src/index.ts`; strict public routes/methods, exact-origin CORS and bounded question shape. |
| Request persistence | SQLite-backed `QozonBackend` Durable Object; one stable `public-api-v1` identity across hostnames, updates and rollbacks. |
| Deployment | Pinned Wrangler 4.150.0 / TypeScript 7.0.2 / workers-types 5.20261013.1; `cloudflare/wrangler.json`. |

The native Durable Object Container API is used with **default scheduling**:
Wrangler owns the image/instance rollout and enforces `max_instances=1`.
The prepared `basic` size passes the local quarter-CPU/1-GiB synthetic workload;
retain it for the first hosted test. Hosted capacity is not established. The beta
`durable_object` scheduling policy is unnecessary here and does not support
`max_instances` or the runtime `basic` size.
[Scheduling policies](https://developers.cloudflare.com/containers/configuration/scheduling-policy/),
[container API](https://developers.cloudflare.com/containers/api/durable-object-container/).

### Completed local work

1. **Serving dependencies separated.** Docker installs with
   `uv sync --locked --no-default-groups --no-editable`. Chroma/BM25 and Pillow
   ingestion imports are lazy. Existing direct pins remain. Local `uv sync --locked`
   still includes development and ingestion packages.
2. **Worker/DO adapter implemented.** Public routes: question POST; health,
   document and approved-citation GETs. Other routes, including original-PDF and
   interactive question docs, are not exposed by the Worker. Preflight allows
   only the confirmed website/method/Content-Type and consumes no quota.
   Client identity comes from Cloudflare ingress. Visitor admission, forwarding,
   authentication and cookie headers do not cross the internal binding.
3. **Durable allowance implemented.** Five attempts/IP/fixed UTC minute and
   100/service/fixed UTC day. Atomic SQLite reservation completes before paid
   forwarding. Failures/timeouts keep their slot. Store counts/expiry/daily HMAC
   identities, without question text or raw IP. Counter failure returns safe 503.
4. **Private Python admission implemented.** Cloudflare mode requires enabled
   limits and the internal secret header; missing/forged admission cannot call the
   model. Local mode retains its disk counters. The secret is inserted only after
   DO reservation and never supplied by React. Original/ingestion credentials are
   absent from the explicit container startup environment.
5. **Readiness/deadlines/recovery implemented.** Concurrent requests share startup;
   readiness is checked before forwarding. Startup allowance is 15 seconds,
   outer request budget 55 seconds, Python/model/browser deadlines remain
   45/30/60 seconds. Cold-start time consumes the outer budget. Completed deadline
   timers are cleared; object restart restores inactivity policy. The 300-second
   production idle policy begins after the object becomes inactive and needs hosted
   measurement, including runtime/shutdown overhead.
   No automatic question POST retry. Approved citation redirects remain 307.

### Completed process: Linux image and native container verification

Docker Desktop engine 29.8.2 is running. Built the actual **Linux/amd64,
CPython 3.12.14** image `qozon-api:phase4` with 54 serving packages. Docker reports
365,322,261 image bytes; streamed filesystem export counts 267,138,958 regular-file
bytes. These are different measurements, not a compressed upload estimate.
Actual image inspection found no original PDF, `.env`, private `data/`, ingestion
libraries or synthetic test overlay. The 146-asset/242-file release registry matches.

| Executed check | Result |
| --- | --- |
| Production image health/admission/private routes | Nine passed, with no model credentials. |
| Native local Worker → SQLite DO → Docker HTTP path | 25 passed: public reads, manual 307 citations, exact CORS, input/identity/quotas, provider/retrieval outage and source withdrawal/recovery. |
| Eight overlapping synthetic questions | All completed; eight concurrent model fixtures, 1.392-second maximum batch time. |
| Actual question deadline/recovery | Safe 504 after 45.085 seconds, cancellation observed, next request succeeds. |
| Quarter CPU / 1 GiB resource check | Peak 184,569,856 bytes (176 MiB); measured production cold start 9.526 seconds. |
| Native daily quota race | Exactly three of 12 attempts admitted when three slots remained; nine returned 429. Production quotas unchanged. |
| Idle shutdown/new container | Quota persisted; five-second test policy stopped in 10.54 seconds after completed timers were cleared. |
| Full local Worker runtime restart | Daily count stayed at 54; excess question returned 429 without starting the container; health recovered. |
| Worker / client / TypeScript | 22 Worker tests, six client tests and type checks passed. |
| Wrangler bundle dry-run | Passed; container rollout disabled, no image or Worker uploaded. |

The Python source did not change during container checks. Its October 13 checkpoint
remains **639 passed, one skipped, 27 existing warnings**; it was not rerun for the
TypeScript-only fixes. Local native probes use a separate temporary overlay with
synthetic provider answers/embeddings and mocked database HTTP; no real source,
model call, export, cloud write or account action. The overlay and its test routes
are absent from the release image. Temporary runtime/containers were stopped;
`qozon-api:phase4` is retained. Local Apple Silicon emulation and synthetic providers
do not establish hosted latency, production capacity or live provider connectivity.
Local Wrangler does not enforce production `max_instances`; the checks used one
stable object and explicitly applied Docker CPU/memory caps.

Testing found and fixed three issues: measured cold start exceeded the former
eight-second allowance; the outer binding followed citation redirects; completed
deadline timers delayed inactivity. The allowance is now 15 seconds, both bindings
preserve manual redirects, and timers are cleared with inactivity policy restored
on object construction. The idle test improved from 61.28 to 10.54 seconds.
Evidence: `data/evaluations/phase4-linux-container-checks-v1.json`.

Rebuild command, from `project_Qozon`:

```sh
docker build --platform linux/amd64 -t qozon-api:phase4 .
```

Changes to source/dependencies require rebuilding and redeploying. Provider data
remains outside the image. Worker checks need no account/payment:

```sh
cd cloudflare
npm ci --ignore-scripts --no-audit --no-fund
npm run check
npm test
npx wrangler deploy --dry-run --containers-rollout none --autoconfig false
```

### Completed process: Production secrets and deployment

The user activated Workers Paid and authorized production deployment. Wrangler's
signed-in account had no `qozon-api` Worker or container application before this
work. The original PDF and privileged ingestion keys were excluded throughout.

**Production API:** [https://qozon-api.qozontech.workers.dev](https://qozon-api.qozontech.workers.dev).
One `basic` container: quarter vCPU, 1 GiB memory, 4 GB disk and `max_instances=1`.
The stable SQLite Durable Object is `public-api-v1`. The published image is pinned
in `cloudflare/wrangler.json` to:

```text
registry.cloudflare.com/b0668461560fc6ead1ad55345b3437c4/qozon-api-qozonbackend@sha256:77292e288afc8981a08b7408e1d9fbbf1e3234c2238aa57c08c989b6496aba0d
```

Cloudflare stores exactly four secret bindings: `OPENAI_API_KEY`, `SUPABASE_URL`,
`SUPABASE_PUBLISHABLE_KEY` and `QOZON_QUESTION_LIMIT_KEY`. Only these values were
prepared in ignored `cloudflare/.env.deploy` (mode 0600). The OpenAI/Supabase values
came from the existing local configuration; the admission key was generated once
and retained. No Supabase secret/service-role key, original-PDF locator or
LangSmith key was deployed. Keep this admission key stable across updates/rollbacks;
never regenerate or reset quota storage just to redeploy.

Two Docker registry uploads failed with TLS/broken-pipe errors. An official,
checksum-verified temporary Google `crane` v0.22.1 uploader completed the transfer
using HTTP/1.1; TLS verification stayed enabled. No uploader dependency was added
to the Python project. Deployment then used the immutable uploaded image reference.

Hosted checks passed: HTTPS health; anonymous document list/summary; approved
PNG/JSON citation redirects and bytes matching the registry; exact website
preflight; invalid method/body/origin; unknown document/citation; original PDF,
`.env`, private data and interactive-docs routes denied. Supabase separately
rejected private `storage_bucket`/`storage_object` columns with `42501` using the
production publishable key. The question gate and live 429/Retry-After path were
checked without calling models. The same server UTC minute/fixed IPv4 connection
probe confirmed 429 survives an unchanged Worker redeploy. Active Worker version:
`e8780247-4fac-4dd4-8d76-242834829912`. See
`data/evaluations/phase4-production-deployment-v1.json` for full results and
live-answer-test status.

The website needs only this public URL, with no key:

```js
import { askQuestion } from './qozon-api.mjs';
const result = await askQuestion('https://qozon-api.qozontech.workers.dev', question);
```

The existing React site now uses its own small `src/lib/rag.js` JSON client with
this contract. Its live chat renders answer/source results as plain text and
approved links, preserving the existing panels. Published source is
`/Users/sardoravaz/ReactNativeProjects/srahimov_site`, commit `1150664`. Seven
client checks/build and local saved-answer UI replay pass. The actual website
browser/API input-gate path is verified without new paid calls. Attachments were
removed because no public upload endpoint is implemented. Git-triggered build
delivery was not observed; the exact approved build was published through Wrangler
to the existing Pages project, with Git settings untouched.
The prepared browser origin remains exactly `https://srahimov.site`; no custom
API domain or DNS change was made. LangSmith/raw request tracing remains disabled.

### Completed process: One approved hosted answer

A single approved preface-purpose question returned HTTP 200 in **7.282 seconds**,
with both purposes and a page-4 citation. Response schema, source sentences,
public chunk hash and current document revision pass. The fixed serving path uses
one query embedding and one answer, no retries, judge or LangSmith export. No
original PDF bytes were read and no database/source writes were made. This one
case does not establish wider quality or capacity. Evidence:
`data/evaluations/phase4-hosted-answer-smoke-v1.json`.

### Next process: Remaining operations acceptance

The user will choose/configure the monthly cap in OpenAI; its setting is not
verified here. The approved one-question allowance is used. Any further paid evaluation requires
a fresh bounded allowance. React connection is live; complete full
hosted idle/recovery and distinct image rollback acceptance for final operations review.

Update deployment command, from `cloudflare` (already executed):

```sh
npx wrangler deploy --secrets-file .env.deploy --autoconfig false
```

`wrangler.json` now uses the published immutable image. This command updates the
Worker/configuration; it does **not** rebuild Python code. For Python/dependency
changes, build the Linux/amd64 Dockerfile, push the new image, replace the pinned
image digest, then deploy. For a Worker-only change use `--containers-rollout none`.
After changing startup secrets, stop the existing container before admitting
questions so the next startup receives the new values.

Rollback: retain accepted source/uv/npm lockfiles and the pinned image reference.
Deploy the intended Worker **and** image through the same application/DO identity;
verify both versions. Never restore older quota data. Current initial deployment
is not evidence that a distinct older container image rollback has been tested.
Document revisions use the separately verified trusted activation/rollback path.

## Existing application technology and checkpoints

| Technology | Plain explanation | Use in this release |
| --- | --- | --- |
| LangChain | Connects the AI model and the document retriever through standard interfaces. | Existing cloud retriever, query embedding and checked sentence selection. |
| LangGraph | Keeps workflow state and routes work between steps/specialists. | Main planned orchestration platform; the current single-PDF path stays linear. No graph deployment is needed yet. |
| LangSmith | Measures answer quality and records permitted execution details. | Existing accepted evaluation datasets and nine-case cloud comparison. No automatic paid judge per visitor question. Release tracing starts off; metadata-only spans can be enabled after checking trace costs. |
| Supabase Postgres + pgvector | Stores reviewed text and vectors together so related text can be found. | Existing 2,451-chunk index. RLS allows anonymous reads only for public, active, undeleted revisions. |
| Supabase Storage | Holds files separately from database rows. | Private original PDF; approved PNG/Markdown/JSON citations in the existing public bucket. |
| OpenAI | Supplies the answer model and query embeddings. | Current GPT-6 Luna, 512 output tokens; text-embedding-3-small, 1,536 dimensions. Corpus vectors are reused. Reviewed image context can affect input cost. |
| Python + FastAPI + Uvicorn | Runs the HTTP API and manages requests. | One worker, connection/task limit 16, existing 45-second question deadline, fixed safe errors and buffered answers. |
| SQLite | Saves question counters. | Durable Object storage for Cloudflare; local disk mode for other hosts. Supabase remains the document/vector database. |
| Docker + uv | Packages the existing app with its locked dependencies. | Allowlisted build context; no credentials, original PDF, local vector index, extraction files or evaluations. Ingestion/Chroma packages are excluded by the serving install; Linux image built, inspected and measured; published by immutable digest. |
| Hosting provider | Runs the API and exposes HTTPS. | Selected Cloudflare Worker/DO plus one Python container; existing Supabase remains the database/file host. |

## Hosting alternatives and earlier account checks

Cloudflare Containers is now selected. The following comparisons are retained as
historical alternatives; current deployment steps are above.

The user is building the React frontend on **Cloudflare at
`https://srahimov.site`**. The options below are for the **Python API backend**;
the frontend hosting decision is already made. The chat calls the API over HTTPS.
The prepared release allows browser requests from this exact origin via CORS,
with GET/POST, Content-Type, no credentials and browser-readable Retry-After.
`www`, preview and development origins are separate and are not included.

```text
React website on Cloudflare: https://srahimov.site
    → HTTPS POST /questions on the separately hosted Python API
    → LangChain retrieval/model + existing Supabase
    → checked answer and approved citations back to React
```

Cloudflare also supports FastAPI on Python Workers, but that is a different runtime.
The current locked app uses Python 3.12, native dependencies and a persistent
SQLite counter file. Its Workers compatibility/storage have not been tested.
Keeping the current Python backend is the recommended first integration; a Workers
proxy or backend migration can be assessed later if it serves a specific need.
[Cloudflare React hosting](https://developers.cloudflare.com/pages/framework-guides/deploy-a-react-site/),
[Python Workers packages](https://developers.cloudflare.com/workers/languages/python/packages/).

### LangSmith hosting preference and plan eligibility

The user prefers LangSmith as the API host on its free Developer plan. The current
published pricing lists Developer at **$0/seat/month with 5,000 base traces/month**,
with hosted Deployment marked **N/A**. Plus is **$39/seat/month** and includes one
small serverless deployment; other usage and model calls retain separate costs.
The deployment quickstart requires Plus or above and a project exporting a graph.
[Published pricing](https://www.langchain.com/pricing),
[Cloud deployment prerequisites](https://docs.langchain.com/langsmith/deployment-quickstart).

The signed-in account was checked read-only on October 12: **Current plan:
Developer — Free; Deployment: Requires upgrade**. Plus shows $39/seat/month and
one Serverless Small deployment included. No free hosting entitlement is shown on
the current plan. The user's cost preference is now pending clarification; no
subscription or hosted service has been changed. Existing LangSmith evaluation use
and the prepared API/client remain intact. Before a hosting migration, prepare a
small graph adapter and verify the public question interface, durable request
quotas and data/tracing boundaries. Do not expose a LangSmith API key in React.

| Option | Why choose it | Tradeoff and needed setup |
| --- | --- | --- |
| Render — retained alternative | Managed HTTPS, Docker builds, health checks and a simple service dashboard. | Prepared `render.yaml`: one 1 CPU/2 GB instance and 1 GB persistent disk in Ohio, near the existing database. Verify current price before creation. A disk prevents horizontal scaling and zero-downtime deploys; brief deployment downtime is acceptable for this first release. |
| Railway | Managed Docker deployment, persistent volumes and infrastructure usage controls. | Attach one volume at `/var/qozon` and use the same image/settings. Resource billing varies with use; set the compute hard limit. A reached limit takes workloads offline. |
| Your own VPS | Direct control of the machine and disk. | You manage HTTPS/reverse proxy, OS updates, process restart and backups. More operational work; no need for it at this stage unless you already run one. |

The Render file is an option, not a purchased service. Use `project_Qozon` as the
repository/build root. The workspace currently has no Git repository or hosting
connection. Create a reviewed code repository excluding `.env` and `data/` before
connecting a host. `.dockerignore` is an additional build boundary; it does not
protect files already committed to a repository.

The 2 GB option is a conservative starting configuration, not a measured capacity
claim. Measure startup and request memory after the image builds before downsizing.
Keep one instance; moving to multiple replicas requires a shared quota store first.
LangSmith Deployment is now the user's preferred hosting option, subject to an eligible
plan or trial. Its graph/runtime integration is not implemented; the existing
FastAPI container option remains available while eligibility is clarified.

[Render Docker](https://render.com/docs/docker),
[compute plan IDs](https://render.com/docs/compute-plans),
[persistent disk limitations](https://render.com/docs/disks),
[Render pricing](https://render.com/pricing),
[Railway pricing](https://docs.railway.com/pricing/plans),
[Railway compute cost controls](https://docs.railway.com/pricing/cost-control).

## Request and cost limits

| Control | Starting setting | Effect |
| --- | --- | --- |
| Visitor question rate | 5 attempts per client IP per fixed UTC minute | Extra requests receive 429 and Retry-After before retrieval/generation. People sharing an IP share this allowance. Adjacent minute boundaries can admit 10 requests close together. |
| Whole-service daily allowance | 100 attempts per fixed UTC day | Limits paid work to at most 100 query-embedding invocations and 100 answer invocations daily on the public API path. Invalid request bodies do not count; input holds, failures and cancellations after reservation do count and are not refunded. |
| Question/context/output size | 200 original characters; 4 retrieved chunks within 16,000 characters; 512 generated tokens | Existing prompt/output controls stay in effect. Character count is not token count; image inputs have separate cost. |
| Automatic retries | Zero for answer and query embedding calls | A provider error does not silently repeat paid work. Existing bounded retries remain for database reads/immutable import inserts. |
| Concurrent connections/tasks | 16 on one Uvicorn worker | Busy connections receive 503. This is server admission, separate from the minute/day allowance. |
| OpenAI monthly spending | User-managed in OpenAI; unverified | Set a dedicated production project's **enforced hard spend limit** and an earlier alert. Enforcement is not instantaneous; tracked usage can slightly exceed the amount. This controls model/embedding dollars, separately from hosting/storage/tracing. |
| Supabase spending | Existing plan; verify Cost Control | Pro Spend Cap covers specified usage such as egress/storage, but excludes compute and some add-ons. Direct public asset/Data API traffic bypasses the API question counter. |
| LangSmith spending | Tracing off in prepared release; no visitor-time judges | Use existing quality evaluations. Enable only permitted metadata spans with an explicit trace budget; tracing and model evaluations have separate costs. |

The daily allowance is a call-volume limit, **not a dollar estimate**. Actual cost
depends on model pricing and input/output/image tokens. Dedicated production API
keys keep evaluation/ingestion usage separate. Existing paid evaluation budgets
are consumed; any new paid release comparison needs its own bounded scope.

The user will configure the provider cap. In OpenAI Project settings → Limits → Spend, enter the
selected monthly amount and enable **Enforce a hard limit**. An alert alone does
not stop requests. Keep the current safe provider-error behavior and no retries.
[OpenAI spend limits](https://developers.openai.com/api/docs/guides/spend-limits).
[Supabase cost controls](https://supabase.com/docs/guides/platform/cost-control).
[LangSmith pricing](https://www.langchain.com/pricing).

Counters use SQLite transactions on a persistent disk. A missing key, corrupt or
unavailable database fails closed: startup stops or a question receives safe 503,
without paid work. Counters contain counts, expiry times and daily rotating HMAC
client identifiers, never question text or raw IP addresses. The stable secret
must remain unchanged through restarts; rotating it resets per-IP buckets but
preserves the global day counter. Do not delete/restore an older counter file to
recover a failed deployment; that can reopen the daily allowance.

Uvicorn must trust only the host's verified proxy IPs/CIDRs via
`FORWARDED_ALLOW_IPS`. Application code ignores raw X-Forwarded-For headers. If the
proxy is not configured, visitors can share the proxy's bucket; trusting arbitrary
proxies permits spoofing. Verify real client separation and forged-header behavior
on the chosen host before release. [Uvicorn proxy settings](https://uvicorn.dev/settings/#http).

## React chat connection

## API handoff and release plan

The existing API is prepared for frontend integration. Deliverables:

- `release/openapi.json`: exported directly from the application without loading credentials or calling a provider. The live API exposes the current schema at `/openapi.json` and interactive documentation at `/docs`.
- `release/qozon-api.mjs`: dependency-free browser client for the React chat. Copy it into the frontend source and import `askQuestion`.
- `Dockerfile` / `render.yaml`: existing optional backend packaging/hosting configuration. No public API hostname is active yet.

| Endpoint | What React receives |
| --- | --- |
| `POST /questions` | One buffered, checked answer and its approved `sources` when available. Submit only `{"question":"..."}`. |
| `GET /documents` | Public document summaries, with bounded pagination. |
| `GET /documents/{document_id}` | One public document's summary/current revision. |
| `GET /documents/{document_id}/citations/{chunk_id}/{kind}` | 307 redirect to an approved image/structured/text file; unavailable sources return a safe error. |
| `GET /health` | Configuration/liveness information; no provider connection verification. |

`question` is a required nonblank string, at most 200 Unicode characters. Extra
body fields, including conversation history, are rejected. Successful answers use
`{"answer":"...","sources":[...]}`; `sources` may be omitted when empty and the
client normalizes it to `[]`. Source entries provide canonical IDs, physical pages,
content type and optional approved links. Do not invent an original-PDF URL.

Errors use `{"detail":{"code":"...","message":"..."}}`. The exported contract
now describes this safe envelope rather than the framework's default validation
error list, and correctly describes citation redirects instead of a JSON 200.
On 400/409/422 let the visitor revise the question; on 429 show the returned wait;
on 502/503/504 offer a manual retry. No visitor authentication or API key is required.

Release steps:

1. **Prepared:** API contract/client, exact website CORS, public citation/private-original boundary and durable request limits.
2. **Backend deployed:** Workers Paid active; four secrets and pinned container deployed. The user manages the OpenAI cap. Hosted reads/privacy/CORS/limits checked; complete the answer and remaining release acceptance.
3. **Website connection:** set React's public HTTPS API base URL, import the client and display answer/source results as plain text/approved links. A hostname such as `api.srahimov.site` remains optional and unconfigured.
4. **Hosted acceptance:** verify actual browser preflight, error/retry behavior, cloud reads, private-original denial and restart persistence. Use a new bounded paid quality run only if required. Record the real API URL and rollback procedure before launch.

LangChain is the current retrieval/model platform, LangSmith the evaluation/trace
platform, and LangGraph the planned workflow/state platform. No new graph, queue,
backend service or dependency is introduced by this handoff.

The API base URL is `https://qozon-api.qozontech.workers.dev`. An optional custom
hostname such as `api.srahimov.site` is a proposal, not an existing endpoint or DNS
change. Put only this public URL in the React build configuration, for example
`VITE_QOZON_API_URL` if the website uses Vite. OpenAI/LangSmith/ingestion keys stay
on the backend. No API key, cookie or visitor login is needed in the chat request.

```javascript
// Copy release/qozon-api.mjs into your React source directory.
import { askQuestion } from "./qozon-api.mjs";

// Example for a Vite frontend: this is a public URL, not a secret key.
const API_BASE_URL = import.meta.env.VITE_QOZON_API_URL;
const { answer, sources } = await askQuestion(API_BASE_URL, question);
// Render answer as plain text; display sources using their approved links/pages.
```

The delivered client uses a 60-second browser deadline, accepts a caller cancellation
signal and makes one fetch with no credentials or automatic retries. On HTTP errors
it exposes `status`, `code` and a positive `retryAfter` when supplied.

Use the confirmed HTTPS API base URL without a trailing slash. The UI submits only
the current question (up to 200 characters); conversation display can remain in
React, because the current API does not accept a history field. Disable duplicate
submissions while awaiting an answer. Render the answer as plain React text and
use returned approved source links/pages; never create a link to the original PDF.
On 429, show the safe message and use exposed Retry-After; on 503/504 show a retry
option without automatic resubmission. If the website has a Content Security
Policy, permit the selected API origin in connect-src.

The release CORS setting is:

```text
QOZON_CORS_ORIGINS=["https://srahimov.site"]
```

The middleware reads settings when the ASGI stack starts, preserving import-time
configuration laziness. JSON preflight does not use a question slot or call a
model. Browser access is limited to the configured origins; CORS is not visitor
authentication and does not stop non-browser callers. Existing public request
limits remain responsible for admitted question work. No wildcard origin or
credentials are enabled. Local defaults allow no browser origins until configured.
[FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/).

## Backend environment for the retained Render/VPS alternative

`render.yaml` enables limits, uses a generated stable secret, and sets the counter
path to `/var/qozon/request-limits.sqlite3`. It requests the OpenAI key, Supabase URL
and publishable key privately; **no Supabase secret/service-role key or original
Storage bucket/object locator belongs in this public service.**

The image includes `release/publication.json`: 146 approved assets/242 public file
entries, checked against the current authoritative registry. It contains public
identifiers, object keys, sizes and hashes only. After a new approved publication,
refresh and recheck this release copy against the authoritative local registry
before rebuilding; never copy the entire data directory.

For a Render/VPS host using local disk counters, use these settings:

```text
QOZON_RAG_ENABLED=true
QOZON_CORS_ORIGINS=["https://srahimov.site"]
QOZON_RAG_BACKEND=supabase
QOZON_OUTPUT_MAX_TOKENS=512
QOZON_QUESTION_LIMITS_ENABLED=true
QOZON_QUESTION_LIMITS_DATABASE=/var/qozon/request-limits.sqlite3
QOZON_QUESTIONS_PER_MINUTE=5
QOZON_QUESTIONS_PER_DAY=100
LANGSMITH_TRACING=false
QOZON_LANGSMITH_TRACE_CONTENT=false
```

Provide the keys privately and use a random `QOZON_QUESTION_LIMIT_KEY` of at least
32 characters. Mount a persistent disk at `/var/qozon`. Set `PORT` as required by
the host and configure verified proxy trust. The container starts one Uvicorn
worker with concurrency 16 and no access logs. The current `/health` checks local
configuration only; it does not prove OpenAI or Supabase is reachable.

## Release checklist

- [x] Retain LangChain/LangGraph/LangSmith as the main AI platforms.
- [x] Preserve public Q&A/approved citations and the private original-PDF boundary.
- [x] Separate locked serving dependencies and make local ingestion imports lazy.
- [x] Implement one TypeScript Worker and SQLite-backed Durable Object with atomic allowances.
- [x] Require private edge admission in Python; strip visitor forwarding/admission headers.
- [x] Verify startup, quotas, concurrency, persistence/reset, deadlines/recovery, safe errors and exact CORS locally.
- [x] Match the public registry and inspect the build-context allowlist/configuration for private values.
- [x] Retain 639 Python checkpoint; pass 22 Worker/six client tests, TypeScript and Worker dry-run.
- [x] Build/inspect actual Linux image; measure memory/startup and verify native local Worker/container HTTP, concurrency, deadline, quota, idle and full-runtime restart.
- [x] User activated Workers Paid; four runtime secrets and pinned container deployed.
- [ ] User-managed OpenAI hard spend cap configured/verified separately.
- [x] Deploy and verify actual anonymous cloud reads/citations, exact-origin preflight and private-route denial.
- [x] Complete approved one-question live answer and source/citation verification.
- [x] Publish existing React chat and verify actual browser/API connection with model-blocked input.
- [ ] Complete full hosted lifecycle/recovery and distinct image rollback acceptance.
- [ ] Record actual URL, image/version, tested rollback and release ownership before public launch.

Verification records: `data/evaluations/phase4-release-preparation-v1.json`,
`phase4-cloudflare-browser-v1.json`, `phase4-api-handoff-v1.json` and
`phase4-linux-container-checks-v1.json`, `phase4-production-deployment-v1.json` and
`phase4-react-publication-v1.json`
in the same directory.
