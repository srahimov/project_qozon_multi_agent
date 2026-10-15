# Phase 4: public Q&A, approved citations, private original PDF

The user selected **public Q&A and approved citations, with the original PDF kept
private**. Visitors need no Supabase Auth account or document ownership setup.
LangChain, LangGraph and LangSmith remain the main build/workflow/test platforms.
The reviewed cloud index and LangChain retriever are implemented. Supabase is now
the configured API backend after accepted LangSmith comparison; Chroma remains
available locally.

## Technology roles

| Component | Role |
| --- | --- |
| LangChain | Existing model/embedding interfaces and sentence selection; one implemented cloud retriever over bounded Supabase RPCs |
| LangGraph | Main workflow/state platform as sources expand; specialist orchestration remains Phase 7 |
| LangSmith | Cloud/local quality and citation comparisons before switching retrieval; metadata-only tracing remains the default |
| Supabase Postgres + pgvector | Checked text, provenance, revisions and 1,536-dimensional cached vectors |
| Database RLS + publishable key | Anonymous reads of explicitly public active documents/chunks; restricted writes |
| Supabase Storage | Private original in `pdf_rag`; only reviewed citation crops/tables in the existing public asset bucket |
| Existing FastAPI, HTTPX, Python and uv | One small public reader, the existing gates/deadline and trusted ingestion; no added packages |

The configured project is **ai_projects**, Postgres **17.11**, pgvector **0.8.2**
in `extensions`. Four pre-existing checkpoint tables remain separate. Their
presence does not establish that the Qozon LangGraph workflow is implemented.

## Schema and publication

The [initial document migration](../supabase/migrations/20261012195706_qozon_document_access.sql)
created three tables. The current [public-read migration](../supabase/migrations/20261012214522_qozon_public_qa_reads.sql)
adds `public_read`, makes ownership optional and permits bounded anonymous RPCs.

| Table | Current role |
| --- | --- |
| `qozon_documents` | Logical document, private ingestion location, active revision, deletion state and `public_read` (default false) |
| `qozon_chunks` | Checked text/evidence, provenance, cached `vector(1536)` and revision identity |
| `qozon_document_access` | Historical named-reader sharing compatibility; not required by the public MVP |

Only a trusted ingestion/admin job may publish or change the index. Public RLS
requires `public_read=true`, an undeleted document and a non-null active revision.
Chunks must belong to that active revision. Private, pending, staged, withdrawn
and deleted content stays outside anonymous retrieval; filters never grant access.
Anonymous readers cannot select owner IDs/private PDF locations or sharing rows,
and cannot write either index table. Reader RPCs remain `SECURITY INVOKER`, with
at most 12 results. Existing private owner/share rules are retained for schema
compatibility; the public application always uses the anonymous read-only client.

Setting `public_read` publishes the checked index text as readable data, including
through the Data API. Import only reviewed text and allowlisted public metadata:
original PDF hash, display source name, physical pages, chunk/type/asset IDs,
source fingerprints and review flags. Exclude raw extraction files, local paths,
private Storage references, credentials, signed URLs and arbitrary URL fields.
The original PDF bytes and its locator are not published.

Keep text-embedding-3-small / 1,536 dimensions and reuse matching cached vectors.
Stage a complete new revision with immutable source references, verify counts and
hashes, then activate it against the expected previous revision in one transaction.
Keep the previous revision for rollback; soft deletion hides the document before
cleanup. Start with exact search for 2,451 chunks. Postgres full-text ranking
changes the BM25 keyword lane, so measure parity before changing the API default.

## Public request routes

| Route | Behavior |
| --- | --- |
| `POST /questions` | Anonymous question path and gates; selects Chroma or the LangChain cloud retriever |
| `GET /documents` | Reviewed public active document summaries, pagination capped at 100 |
| `GET /documents/{uuid}` | Public summary only; hidden and absent documents return 404 |
| `GET /documents/{uuid}/citations/{chunk_hash}/{kind}` | Canonical approved PNG/JSON/Markdown redirect; kind is image, structured or text |

The document client sends only the backend publishable key. It never forwards
visitor tokens/cookies or uses the ingestion secret. The API has **no original-PDF
download route**, no private download proxy and no visitor Auth validation.
The `pdf_rag` bucket stays private with Storage RLS enabled and no user policies.
The existing secret remains confined to trusted ingestion/publication operations.

Citations reuse the [existing publication resolver](../src/qozon_multi_agent/knowledge_base/pdf/publication.py).
The chunk's original-document hash, asset ID and source fingerprint must match the
verified registry. URLs are constructed for the configured public bucket and
content-addressed PNG/MD/JSON keys. PDF keys, invented URLs, changed fingerprints,
unverified assets and mismatched projects/buckets are rejected. Already approved
public assets remain downloadable if a document is later withdrawn; RLS cannot
recall public files. No new asset publication occurred in this checkpoint.

## Pre-import public-access verification and history

- **37 public API boundary cases** pass; these replace 52 cases for the superseded private API contract.
- **31/31 local database assertions** pass for opt-in publication, anonymous/signed-in reads, hidden revisions, locator/write denial, withdrawal and activation.
- **26/26 real Data API/RPC/API checks** pass, including anonymous approved asset byte hashes. Four fictional document rows and their chunks were deleted. No accounts or files were created.
- **553 offline tests pass**, one live test skipped, 27 existing warnings; 11.95 seconds. No model/embedding calls, LangSmith exports or dependency changes occurred.
- Final catalog checks show empty document/chunk/grant tables, zero Auth users, one unchanged private PDF object and no Storage user policies. Security findings concern only pre-existing checkpoint/trigger objects.

The previous owner/share schema and private proxy were implemented and verified,
then superseded by the user's public-access clarification. The private proxy was
introduced after a direct Storage cache diagnostic; it is now removed because
only already approved public assets are citations. Historical reports and applied
migrations remain available; they do not describe the current visitor flow.

Sources: [public reader](../src/qozon_multi_agent/knowledge_base/documents.py),
[routes](../src/qozon_multi_agent/api/documents.py),
[database checks](../tests/database/phase4_public_access.sql),
[verification report](../data/evaluations/phase4-public-access-v1.json).

## Reviewed index and cloud retriever execution

- `cloud_import --check` verifies original source-file hashes, reviewed parent
  fingerprints, corpus/index identity and every cached embedding before writes.
  Explicit public metadata construction excludes all local/private locators and URLs.
- `cloud_import --import-reviewed` imported **2,451 chunks**: 2,249 text, 128 image
  descriptions and 74 table summaries. All **146 approved assets** are linked.
  Existing 1,536-dimensional vectors were reused: **zero embedding/model calls**.
- Revision `e1853c208ac12305af73e6f2a122bed37850c02f2570799bcabbf97d42744550`
  includes the full evidence/public contract/vector payload. Duplicate-ignoring
  immutable staging survived connection interruptions. Every stored text, metadata
  object and float32 vector matched read-back before one conditional document
  update set the active revision and `public_read=true`. No new DDL was needed.
- `CloudPDFRetriever` implements LangChain `BaseRetriever`. Two anonymous bounded
  RPCs provide vector/full-text results; existing fusion combines them. Reviewed
  complete table context and image captions use the same resolver as local reads.
  Only a registry-approved PNG is fetched, with a streamed size bound and byte hash.
- The input gate precedes query embedding. Conflicting RPC revisions are withheld.
  Anonymous document/chunk reads recheck evidence after generation and before
  response release. Errors expose fixed messages without upstream content.
- **35 new offline boundary cases** and **589 total tests** pass (one live skipped,
  27 existing warnings, 12.24 seconds). **22 real HTTP checks** pass for all public
  rows, metadata/text equality, locator/share denial, text/table/image integration,
  approved links, original-route absence and a scripted anonymous Q&A response.
  Those integration checks used fixed corpus vectors and a scripted answer. The
  subsequent explicitly approved live comparison below used real query embeddings.
- Final catalog: one public active document, 2,451 active chunks, zero Auth users,
  one original private PDF object and zero Storage user policies. Security advisors
  have no new Qozon findings; previously recorded checkpoint/trigger findings remain.

Reports: [import](../data/evaluations/phase4-cloud-index-v1.json),
[HTTP integration](../data/evaluations/phase4-cloud-http-v1.json),
[bounded quality comparison plan](../data/evaluations/phase4-langsmith-plan-v1.json).

## Accepted LangSmith cloud comparison and API configuration

The approved live nine-case comparison used **seven answer, seven query-embedding
and seven judge calls**. All seven answer cases passed correctness, groundedness,
retrieval, evidence/citation and privacy outcomes; both blocked-input cases passed.
Four public-source checks initially failed because the evaluator assumed a Chroma
record map. The evaluator now uses recorded Evidence and source fingerprints for
both backends. A regression test verifies changed fingerprints fail before fetching.

The same saved cloud answers were replayed through LangSmith, with new anonymous
asset-byte/hash checks and the original seven quality judgments reused. All
**61/61 required scores pass**, **9/9 cases accepted**. Replay made zero new model,
embedding or judge calls. This is a source-check correction of saved live results,
not a second paid generation/judge run. Both experiments/reports are preserved.

`QOZON_RAG_BACKEND=supabase` is now the configured API default; all other existing
configuration was preserved. Startup dependency inspection and real anonymous
`GET /documents` verify the cloud adapter. Health reports configuration only,
and the original-PDF route remains absent. Chroma is available with `chroma`.

Reports: [initial live comparison](../data/evaluations/phase4-pdf-langsmith-v1.json),
[accepted source recheck](../data/evaluations/phase4-pdf-langsmith-v2-sources.json),
[configured API verification](../data/evaluations/phase4-cloud-default-v1.json).

## Verified document lifecycle

The existing importer/retriever/API pass **59 real HTTP lifecycle checks** using
one isolated temporary document, fixed vectors and scripted answers. Two unchanged
reviewed table assets test actual approved citation redirects. No source processing,
paid embeddings/models or new Storage publication was needed.

| Scenario | Verified result |
| --- | --- |
| Partial update | Current revision stays visible; staged new chunks stay hidden |
| Complete/resumed update | Full payload read-back precedes activation; only the new revision is visible |
| Repeated import | Stored text/metadata/vectors remain identical; no duplicate rows |
| Rollback | Exact previous payload/citation restored after verification; both revisions retained |
| Competing activation | Expected-revision check rejects the losing publisher |
| Withdrawal/deletion during import | Publication fails without undoing withdrawal/deletion |
| New reads after withdrawal/deletion | Document/citation API returns 404; both RPCs and retriever return no fixture evidence; no answer-model call |
| Update/withdrawal/deletion during generation | Valid old answer is buffered and withheld with `source_access_changed` |
| Corrupted staged/prior payload | Read-back fails; current revision remains active; resume does not overwrite corruption |
| Management access | Anonymous database writes denied; public API has no write routes |

**59/59 offline LangSmith SDK scores** confirm the saved boundary outcomes with
uploads disabled and run writes stubbed. **12 new lifecycle regressions** pass;
final offline suite: **601 passed, 1 skipped, 27 existing warnings**, 12.63 seconds.
The earlier nine-case live cloud quality acceptance remains valid and was not rerun.

All temporary document/chunk rows were removed. SHA-256 fingerprints over every
original chunk's identity, revision, text, evidence, metadata and vector match
before/after. The actual document stays public at the same revision with 2,451
chunks; zero Auth users/grants, one private original PDF object and zero Storage
user policies. No runtime-code change, migration, dependency or management service
was required.

Previously approved public asset files remain downloadable after withdrawal. The
final access check is a point-in-time check; it cannot recall an already delivered
response. Tests cover controlled interleavings, not arbitrary concurrent load.

Reports: [HTTP lifecycle checks](../data/evaluations/phase4-lifecycle-http-v1.json),
[original payload integrity](../data/evaluations/phase4-lifecycle-integrity-v1.json),
[offline regression cases](../tests/knowledge_base/test_cloud_lifecycle.py).

## Concurrency, deadlines and failure recovery

| Concept | What the user experiences | Needed tech stack and current behavior |
| --- | --- | --- |
| Concurrency | Several people can ask questions at once; each receives its own evidence/citations. Busy service returns 503. | FastAPI/Uvicorn handles requests; asyncio overlaps I/O; LangChain uses independent per-call evidence. Documented Uvicorn launch uses a 16-connection/task limit per worker. |
| Deadlines | A slow request returns a safe 504 and withholds the buffered answer. | asyncio.timeout enforces the cooperative 45-second question budget; LangChain model request timeout is 30 seconds; HTTPX read/connect timeouts are 10/5 seconds. |
| Failure recovery | Later questions work after a transient failure; imports resume without duplicate vectors or unchecked publication. | HTTPX + fixed safe errors, three attempts for reads/immutable inserts, Postgres revisions/RLS, complete payload read-back and conditional activation. Paid answers are not automatically retried. |

LangSmith scores/traces the checked workflows. LangGraph remains the main planned
state/routing platform when additional source workflows require orchestration;
this single-PDF application has one linear request path. Existing installed
versions remain LangChain 1.4.4, LangGraph 1.2.14 (transitive dependency), LangSmith
0.14.7, FastAPI 0.143.0, Uvicorn 0.54.0 and HTTPX 0.28.1. No package changed.

A confirmed cleanup bug was fixed in `CloudPDFRetriever`: `asyncio.gather` could
return on one RPC's failure while the sibling kept waiting. `TaskGroup` now cancels
and joins sibling work before closing the client. Both lane-failure regressions
failed before and pass after the change. The normal retrieval/ranking contract is
unchanged. [Python task-group behavior](https://docs.python.org/3.12/library/asyncio-task.html#task-groups).

Verified outcomes:

- **Eight real cloud questions** overlap with separate answers/chunk IDs. After
  activation changes, all eight buffered old answers are withheld.
- The **scaled three-second whole-request deadline** returns 504, cleans up the
  waiting scripted model and permits the next request. Production remains 45
  seconds. Simulated provider timeout returns 504 without an answer retry.
- One failed RPC cancels/joins its sibling, withholds upstream error details and
  permits the same shared retriever's next request to use real anonymous reads.
- Partial-insert response loss resumes safely with no duplicate rows. A lost
  activation reply returns a fixed error; a new invocation verifies the committed
  revision and recovers idempotently. Two real publishers reading the same previous
  revision produce exactly one winner and one rejected activation.
- A **local Uvicorn server** accepts eight scripted socket questions; a 24-request
  overload burst returns ten 503s, then a normal question/health request succeeds.
  Peak scripted generation is 14, below the configured limit of 16.

**33 real-cloud checks + seven local socket checks**, **40/40 offline LangSmith SDK
scores** (uploads disabled and run writes stubbed) and **11 new regressions** pass.
Final suite: **612 passed, one skipped, 27 existing warnings**, 13.16 seconds.
No paid answer/embedding/judge call or LangSmith/Storage upload occurred. Original
full-payload SHA-256 and active revision match before/after; one public document,
2,451 chunks, zero Auth users, one private PDF object and no Storage user policies.
All temporary rows were deleted and the loopback server was stopped.

The launch flag is required to enforce Uvicorn admission; each worker has its own
limit. Connection/task count is not user rate limiting or a cost quota. The probes
are controlled failure/interleaving checks, not a production capacity or SLA claim.
Async cancellation does not preempt synchronous CPU work or guarantee that a
remote provider stops processing a request already sent.

Reports: [cloud probes](../data/evaluations/phase4-resilience-http-v1.json),
[socket admission](../data/evaluations/phase4-admission-http-v1.json),
[offline SDK scores](../data/evaluations/phase4-resilience-langsmith-offline-v1.json),
[original payload integrity](../data/evaluations/phase4-resilience-integrity-v1.json).

## Release checklist, hosting and request/cost controls

The [Phase 4 release checklist](PHASE4_RELEASE.md) explains each stack component,
compares Render/Railway/VPS and records completed checks separately from deployment.
One small SQLite admission counter now reserves before paid work: five attempts per
IP per fixed UTC minute and 100 per UTC day across the service. Counters persist on
one host's disk; startup/runtime counter failures fail closed. No new queue,
dependency or Supabase table. The nine new regressions pass; current suite:
**621 passed, one skipped, 27 existing warnings**, 15.41 seconds.

A Dockerfile with an allowlisted context and an optional Render Blueprint prepare
one worker/instance, concurrency 16 and a 1 GB counter disk. The image includes
only code/lockfiles and a public registry with 146 approved assets/242 file entries;
all public URLs match the authoritative registry. No original PDF, local extraction,
Chroma index, credentials or evaluation payloads enter the context. No public
service has been created. At this earlier checkpoint Docker was unavailable;
the October 13 Linux/container checks below now pass.

Monthly OpenAI dollar cap awaits the user's preference. Cloudflare Containers
is now selected; the earlier local-disk plan is retained for alternative hosts.
Configure a dedicated project's enforced hard spend limit separately from request
counts; provider enforcement can lag slightly. Existing paid evaluation budgets
remain consumed. No paid calls, LangSmith uploads, database writes, Storage uploads,
package changes or Supabase migrations were performed in release preparation.
Evidence: `data/evaluations/phase4-release-preparation-v1.json`.

The confirmed frontend is React on Cloudflare at `https://srahimov.site`. Prepared
release CORS allows that exact HTTPS origin, GET/POST and Content-Type, without
credentials, and exposes Retry-After. Preflight consumes no question slot.
Nine new browser regressions pass; **630 passed, one skipped, 27 existing warnings**,
13.88 seconds. Backend hosting is still undecided; no frontend/Cloudflare account
configuration or live website connection was changed. The React contract and
Workers runtime distinction are documented in [the release guide](PHASE4_RELEASE.md).
Evidence: `data/evaluations/phase4-cloudflare-browser-v1.json`.

API integration handoff is now prepared: `release/openapi.json` and a small
`release/qozon-api.mjs` chat client. The schema describes fixed public errors,
Retry-After and the actual 307 citation redirect. The client posts one question,
normalizes empty sources, supports cancellation/60-second browser timeout and
never automatically retries. Two contract regressions and six offline JavaScript
checks pass; **632 Python tests passed**, one skipped, 27 existing warnings, 13.28
seconds. The existing request workflow/permissions/dependencies remain unchanged.
No paid calls, cloud writes/uploads or deployment. The [release plan](PHASE4_RELEASE.md#api-handoff-and-release-plan)
separates prepared API work, backend deployment, React connection and hosted acceptance.
Evidence: `data/evaluations/phase4-api-handoff-v1.json`.

## Cloudflare Containers implementation — October 13

User-selected TypeScript Worker/SQLite Durable Object and the serving-only Python
setup are implemented. Native container API with default scheduling and one
instance; no beta scheduling requirement. Durable counters retain local semantics
and commit before paid forwarding; private edge admission is required by Python.
LangChain remains the active cloud retriever/model platform, LangGraph the planned
workflow platform and LangSmith the evaluation platform. Supabase index/RLS/Storage
remain unchanged; Q&A/approved citations public and the original PDF private.

**Linux image and native local runtime checks pass.** Python 3.12.14/amd64 with
54 serving packages; private files/ingestion/test overlay absent. Nine image and
25 native HTTP checks, eight concurrent questions, actual 45-second timeout/recovery,
atomic daily cap, sleep and full Worker restart pass. Peak measured memory 176 MiB
under quarter CPU/1 GiB; cold start 9.526 seconds. Startup allowance is now 15 seconds;
manual redirects and idle timer cleanup are verified. 22 Worker/six client checks,
TypeScript/dry-run pass; prior 639 Python checkpoint retained, Python unchanged.
Synthetic providers only; hosted acceptance remains. No paid calls/exports/uploads/
database/account changes. User can activate Workers Paid now.

See [the completed work and release sequence](PHASE4_RELEASE.md#cloudflare-containers-stack-and-implementation-plan)
and `data/evaluations/phase4-linux-container-checks-v1.json`.

## Production API and public React chat — October 13

October 13: public React chat at https://srahimov.site/multimodal-rag is connected to the deployed Qozon API. Approved frontend commit 1150664 pushed and exact build published to existing Pages project; public JS bytes match. Seven client tests/build/local saved-answer-citation UI checks pass; actual browser JSON/CORS and model-blocked input error verified, no new paid calls. Prior 21 hosted reads/privacy/citation checks, durable quota retention and one live page-4 answer remain accepted. Q&A/approved citations public; original PDF private. User manages OpenAI cap; full hosted lifecycle/image rollback acceptance remains.

Evidence: `data/evaluations/phase4-production-deployment-v1.json`, `data/evaluations/phase4-hosted-answer-smoke-v1.json` and `data/evaluations/phase4-react-publication-v1.json`. Existing public/private access model and backend source are unchanged by the frontend publication.

## Remaining steps

1. User configures/chooses the monthly OpenAI hard cap; maintain private runtime secrets and stable admission key.
2. Complete full hosted idle/container recovery and distinct image rollback acceptance; preserve durable quota data and record final release ownership.
3. Review Git-to-Pages automatic build delivery separately: settings are enabled but this publication needed direct upload of the approved build.

## Current references

- [Supabase RLS and anonymous roles](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Supabase vector columns](https://supabase.com/docs/guides/ai/vector-columns)
- [Supabase API privileges](https://supabase.com/docs/guides/api/securing-your-api)
- [Supabase private/public Storage](https://supabase.com/docs/guides/storage/serving/downloads)
- [LangGraph platform](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangSmith evaluation](https://docs.langchain.com/langsmith/evaluation-types)

- [Uvicorn admission settings](https://uvicorn.dev/settings/#resource-limits)
- [HTTPX timeout types](https://www.python-httpx.org/advanced/timeouts/)
