# Qozon Multi Agent File Change Plan

Project folder: `qozon_multi_agent/`. Application package: `src/qozon_multi_agent/`.

This fork will use one main LangChain agent as the orchestrator and user-facing gatekeeper. One PDF subagent will own book retrieval and answer synthesis. More RAG specialists can be added later as tools of the main agent. The API now invokes this supervisor/PDF workflow; its inherited extractive request path has been removed.

PII middleware is registered only on the supervisor. The single API input boundary sanitizes, screens and blocks credentials before client construction or supervisor invocation. The delegation wrapper forwards the supervisor's PII-checked visitor question unchanged to the PDF tool. Neither agent repeats input sanitization/credential checks. The PDF tool checks its generated structure, citations, pages, display and source access. The supervisor's final turn copies the tool result through registered output PII hooks without another provider call. The service returns that privacy-checked final text with the specialist's structured citation metadata.

LangChain `create_agent()` supplies both agents and executes their registered middleware. We will not build a custom LangGraph graph. LangGraph remains the internal runtime used by LangChain. LangSmith is the sole platform for evaluating LLM generation quality. No runtime support-review model or separate custom quality judge belongs in the agent request path. Citation/schema checks, privacy controls and source-access validation remain application responsibilities.

## Request flow

1. FastAPI validates and admits the request.
2. The API service sanitizes, screens and checks input credentials once. These checks precede supervisor construction and are not repeated in either agent.
3. Invoke the main agent with registered input PII hooks.
4. The supervisor selects the PDF tool; its delegation middleware replaces tool query arguments with the already PII-checked visitor question.
5. Inside the PDF specialist boundary, retrieve four valid keyword hits and four valid semantic hits independently. Both use Supabase PostgreSQL: full-text search for keywords, pgvector for semantic similarity. Deduplicate and retain lane provenance; fewer than eight unique passages is possible.
6. Validate sources and provide the passages, approved images when relevant and stable citation IDs to the PDF agent. The PDF agent synthesizes a cited answer.
7. Validate the generated response structure, source references and page claims. Do not run an additional generation-quality judge. Evaluate grounding, factual support and relevance in LangSmith outside this request path.
8. The supervisor returns the specialist text through its PII hooks using a local model-node reply, without another LLM rewrite. The one-delegation limit is retained; future multi-specialist aggregation needs its own contract.
9. Apply registered supervisor output PII hooks and final service credential/display checks. Source access/revisions are reread at the end of the PDF tool before it returns. Assess factual quality only in LangSmith.
10. Return the existing answer-and-citations JSON contract. Only the main agent communicates with the visitor.

## Source folder layout

Keep the conventional named-package layout: `src/qozon_multi_agent/` contains `agents/`, `middleware/`, `api/`, `core/`, `knowledge_base/`, `llm/`, `security/` and `services/`. The package uses the shorter name selected by the user, with Python-compatible underscores. The local package rename updates imports, build metadata, CLI/server entry points, tests and current documentation together.

The package has been renamed. The standalone custom PII middleware, LangChain supervisor, PDF subagent and its tool wrapper are implemented; earlier offline checks predate the current release. The configured supervisor loads the real Luna client and cloud retriever. The API invokes the new supervisor path. The single input gate, deterministic checked-question delegation and specialist-answer passthrough are connected. The separate Worker is deployed and its health endpoint is confirmed. Live/LangSmith generation-quality acceptance remains pending.

The first bounded real question used four Luna calls but failed at the runner's 30-step cap during middleware completion. Local reproduction needs 33 steps for two supervisor turns; the supervisor now defaults to 64 steps while model/tool call limits stay unchanged. The corrected rerun completed in 9.9 seconds with four Luna calls (3,638 model tokens) and returned a synthesized answer citing physical page 4 after support and source-access checks. Across both attempts, eight model calls were made. That historical supervisor added Markdown emphasis. The current implementation replaces that rewrite with a local passthrough reply; it has not been rerun live. This single question is a development smoke test, not broad quality acceptance. Raw content was not exported to LangSmith and nothing was deployed. The pre-cleanup checkpoint passed 694 tests with one live-model test excluded; that suite is now preserved outside this execution-only project.

## Current evaluation decision

At the user's request, the PDF subagent's `SupportReview` schema, review prompt, optional support-model argument and second review call have been removed. Its normal delegated path now uses one query embedding and one synthesis call; the supervisor adds one routing call and a local final-response turn, not another provider call. LangSmith alone assesses generated-answer quality. Existing programmatic privacy, citation-format/page and source-access checks remain. The project now contains execution code only: local tests, evaluation scripts/modules and the custom monitoring wrapper have been removed and preserved outside it. No tests, paid calls or deployment were run for this cleanup; earlier test counts and live-run records describe the previous implementation.

## Custom PII middleware

Register LangChain's prebuilt PII middleware for email, payment cards, IP addresses, MAC addresses and URLs on the supervisor. Add one custom `AgentMiddleware` implementation for the additional categories: Social Security numbers, selected street-address formats, labeled medical-card IDs, labeled birth dates and ages written as years old. Both use the existing redaction policy and run only on the supervisor.

The standalone custom middleware in `middleware/custom_pii_mw.py` contains its five regex detectors, default handling rules and node-style `before_model` and `after_model` hooks, with async equivalents. It imports no project policy or detector modules. `DEFAULT_RULES` redacts every custom category; optional dictionary overrides support allow and block. Mask and hash configurations are explicitly rejected. Hooks return supported agent state updates without manually invoking another middleware's hooks. Check inbound text before the first supervisor model call, returned tool messages before the next model call and outgoing answer text before release. The supervisor delegation wrapper supplies the existing PII-checked question instead of an LLM-rewritten task. Names remain excluded; additional categories require defined detectors and external LangSmith acceptance.

`middleware/` owns custom PII matching, its handling rules and integration with the agent lifecycle. `security/` retains built-in policy, sanitization, credential and evidence-check logic. The former `security/custom_pii.py` has been removed; its callers now use the detector in the standalone middleware module. Custom PII detection remains deterministic and adds no LLM call.

## New runtime files

All paths below are relative to the repository root.

| New file | Responsibility |
| --- | --- |
| `src/qozon_multi_agent/agents/__init__.py` | Mark the agent package; no provider calls or configuration work on import. Created as the package scaffold. |
| `src/qozon_multi_agent/agents/supervisor.py` | Implemented `build_supervisor()` using `create_agent()`, caller-supplied subagent tools and registered built-in/custom PII middleware. Includes supervisor-only model/tool call bounds and isolated invocation state. The routing prompt assigns synthesis to specialists; checked-question delegation and local answer passthrough are connected to the API. No custom factual-quality grader is added. |
| `src/qozon_multi_agent/agents/pdf_subagent.py` | Implemented `build_pdf_subagent()` and `build_pdf_tool()`. The wrapper retrieves checked four-per-lane evidence before one LangChain synthesis call, checks structured claims/citations/pages, does not make a support-review call and rechecks source access. Returns answer text plus a validated citation artifact as a supervisor tool message. Avicenna's Canon of Medicine is context; claims must use supplied evidence only. |
| `src/qozon_multi_agent/middleware/__init__.py` | Mark the custom middleware package; no runtime work on import. Created as the package scaffold. |
| `src/qozon_multi_agent/middleware/custom_pii_mw.py` | Implemented standalone custom PII middleware containing detectors, handling rules, registered node-style input/output hooks and async support. Covers the five additional categories without duplicating built-in PII checks. Verified outside the project with a fake LangChain model. Pending registration on the supervisor. |
| No extra `middleware/guards.py` | Existing input/output gate modules own request and display/credential checks; the supervisor file contains its small delegation/passthrough wrapper. No extra guard module is needed. |

## Existing runtime files to change

| Existing file | Planned change or replacement |
| --- | --- |
| `src/qozon_multi_agent/services/question_service.py` | Replace the linear retrieve/generate workflow and `AnswerModel` interface with the main-agent entry point. Keep the outer request deadline, safe errors, response assembly and mandatory final release checks. Remove duplicate manual PII enforcement once registered hooks are verified. |
| `src/qozon_multi_agent/api/dependencies.py` | Replace `ConfiguredAnswerModel` and the API-level retriever injection with lazy agent construction. Supply the PDF retriever to the PDF specialist. Cache safe clients/agent definitions, never request state or one visitor's evidence. |
| `src/qozon_multi_agent/api/questions.py` | Call the agent-backed service. Preserve the route, admission requirement and safe HTTP errors. |
| `src/qozon_multi_agent/security/pii.py` | Make the middleware factory the active integration. Compose the five built-in PII middleware instances with the custom PII middleware for the remaining five categories, preserving the ten-category redaction policy and tool-result checks. Register the stack only on the supervisor. Replace the serving path's manual `check_pii()` calls and remove unused manual hook plumbing after tests migrate. |
| `src/qozon_multi_agent/security/input_gate.py` | Retain sanitization, screening and credential checks. Remove its direct PII call; the main agent's registered hooks now own that step. Preserve the requirement that blocked inputs cause no model, embedding or tool calls. |
| `src/qozon_multi_agent/security/output_gate.py` | Retain credential and display checks, but remove its direct PII call. Main-agent registered hooks handle PII; final release checks still occur on the complete returned answer. |
| `src/qozon_multi_agent/security/policies.py` | Keep the ten types and redaction profile. Clarify main-agent policy ownership and update stale comments. Credentials still block; changing agent integration does not change the selected PII actions. |
| `src/qozon_multi_agent/security/evidence_verification.py` | Retains page checks and narrow retrieved-source conflict patterns. The unused exact-source-sentence answer matcher has been removed; no semantic output grading remains. Generation quality is assessed in LangSmith. |
| `src/qozon_multi_agent/knowledge_base/cloud.py` | Implemented `retrieve_balanced()` and four-per-lane selection for the PDF tool. Preserves independent searches, hashes, active revisions, image checks, provenance and final `validate_evidence()`. Deduplicates under the existing context budget. The inherited API retains its prior retrieval default. |
| `src/qozon_multi_agent/knowledge_base/pdf/retrieval.py` | Reuse the `Evidence` contract. Adjust lane selection/context helpers only where needed; keep existing local BM25/Chroma compatibility separate from the cloud full-text path. Ranking can order the selected union without eliminating a requested lane's contribution. |
| `src/qozon_multi_agent/llm/model.py`, `llm/adapters.py` | `model.py` now only builds the configured LangChain client (32 lines). Only offline table/image adapters remain in `adapters.py`. The unused extractive answer adapter/schema and its builder are removed. Agents import only the client factory. |
| `src/qozon_multi_agent/llm/prompts.py` | Define PDF-agent synthesis instructions. The implemented supervisor routing prompt lives in `agents/supervisor.py`; avoid duplicating it. Main handles orchestration; PDF owns factual synthesis and citations. |
| `src/qozon_multi_agent/core/config.py` | Add shared request limits for model calls, tool calls and repairs. Keep the existing total deadline initially and measure whether it fits the multi-agent flow. Avoid independently multiplying allowances for every subagent. |
| Removed `core/observability.py` | Custom span/usage-reporting wrapper and its runtime call sites are removed. Observability belongs exclusively to LangSmith through native integration; no separate monitoring module is planned. |
| Removed `evaluation/langsmith_rag.py` and its runner | No custom answer-quality judge, local scoring or evaluation runner is retained. Manage LLM quality evaluation in LangSmith. |
| Removed `evaluation/phase3_local.py` and its runner | No synthetic/fake-model evaluation harness is retained in this execution-only fork. |

## Files retained

The following remain in place; the agent rewrite does not require replacing them.

| Files or folders | Why they stay |
| --- | --- |
| `security/sanitization.py`, `security/secrets.py`, `security/screening.py` under `src/qozon_multi_agent/` | Reusable normalization, credential rules and screening. Custom PII detectors have moved into `middleware/custom_pii_mw.py`. |
| `src/qozon_multi_agent/knowledge_base/documents.py`, `knowledge_base/pdf/publication.py`, `release/publication.json` | Public source access, approved citation links and original-PDF privacy. |
| PDF extraction, processing, chunking, indexing and import modules | They prepare the corpus; changing answer orchestration does not require rebuilding that pipeline. |
| `supabase/migrations/` | Existing database access rules and search functions remain. Four-per-lane retrieval can use existing result limits; no schema migration is currently planned. |
| `src/qozon_multi_agent/api/schemas.py`, `api/documents.py`, `api/limits.py`, `api/app.py` | Preserve the public request/response and document APIs. Update only integration or readiness details if the new entry point requires them. |
| `release/openapi.json`, `release/qozon-api.mjs`, the separate React website | Keep the current JSON contract and chat integration. Change these only if the public contract actually changes. |
| `Dockerfile`, `.dockerignore` | Keep standard Python 3.12.14 and the serving-only image. Rebuild later to include verified agent code. |
| Existing evaluation datasets | Reuse reviewed cases; add synthesis-specific cases instead of discarding prior evidence. |

## Execution-only implementation order

1. Keep the implemented supervisor and PDF subagent as real LangChain agents. Sanitization is implemented once at API ingress before supervisor invocation, not inside either agent. PII middleware is main-only.
2. Keep four-per-lane cloud retrieval and one PDF synthesis call. Do not add a runtime quality judge or model-testing framework.
3. Completed API wiring: lazy supervisor factory, one input boundary, supervisor-only runtime PII, one PDF delegation and local specialist-answer passthrough. Request deadline, admission limits and citation/access controls remain.
4. Manage LLM quality evaluation, observability and monitoring solely in LangSmith. No test, evaluation, fake-model or monitoring source files belong in this project.
5. Prepare independent cloud resources and rebuild only when deployment is requested. Preserve the existing public Q&A/citation contract and private original PDF.

The local Python tests, Cloudflare tests, evaluation datasets/runners and custom observability wrapper are preserved in a separate reference folder outside this project. Test dependencies and commands have been removed from the active project. No tests, paid evaluations, tracing exports, GitHub push or deployment were performed during this cleanup.

## LangChain references

- [Subagents as tools of a main agent](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)
- [Registered PII middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in#pii-detection)
- [LangChain agents and their runtime](https://docs.langchain.com/oss/python/langchain/agents)

## Current API integration checkpoint

The API now uses the agent workflow. Static syntax/import/caller inspection only was performed. No local tests, application requests, provider calls, LangSmith evaluation/export, GitHub push or deployment were performed. The original production deployment remains unchanged.

## Separate Cloudflare deployment

The execution source was published to GitHub as `9ac5ccf`. A Linux/amd64 image
was built from that revision and uploaded to the separate Cloudflare registry
repository `qozon-multi-agent-api`; `cloudflare/wrangler.json` pins its immutable
digest. The new Worker has its own quota namespace and admission key. After the
user explicitly approved uploading the five runtime secrets, Wrangler deployed
version `86ab0eca-11b8-4e93-bfec-5194fbf0d284` at
https://qozon-multi-agent-api.qozontech.workers.dev.

Container application: `a0398398-bc68-44de-b9b8-3fc1b92193cb`.
Durable Object namespace: `0357ad4ca4ee4659b75cbb10044228cc`.
The pinned image is Linux/amd64 with one Basic instance maximum, quarter vCPU,
1 GiB memory and 300-second inactivity timeout. All five secret names are
confirmed installed without reading their values back. Initial provisioning
returned a temporary 503; a subsequent health request returned HTTP 200 and
Cloudflare reported one healthy container with no application health errors.

The health response confirms startup and Supabase configuration, not provider
connectivity or answer quality. No local tests, paid questions, embedding calls or
LLM evaluation runs were performed. The original `qozon-api` deployment ID was
verified unchanged; the React website still targets its existing API. No new
paid-plan subscription was purchased.

## Native LangSmith model-call observability

All configured model calls target `qozon-multi-agent-production` with 100%
sampling. Removed explicit tracing suppression around the PDF agent, cloud/local
retrieval, embeddings and table/image ingestion. Chat calls use native LangChain
tracing; synchronous/asynchronous embedding provider requests use LangSmith's
native `traceable` SDK in the existing embedding factory. Cache hits emit no
model-call trace because no provider is called. Client factories load local
`.env` variables for the SDK without overriding Cloudflare's injected values.
Inputs and outputs remain hidden. There is no custom monitoring module or local
evaluator, and no new paid call is required to configure observability.

Tracing release: application revision `ce016cb`, pinned in
`cloudflare/wrangler.json` at image digest
`sha256:beb84196cb0799fd88037f50ed4730efb84d326efd62d18afd5354b6db198e0d`.
Worker version `e6f363d5-e887-48e2-bb0f-d26cc70ef23c` is deployed; `/health`
returned HTTP 200 and Cloudflare reports the new image healthy. Existing secrets
were retained. LangSmith project access was confirmed using read-only metadata.
No local tests, synthetic traces or paid model calls were made for this change;
the first new real question will exercise the newly enabled nested tracing.
