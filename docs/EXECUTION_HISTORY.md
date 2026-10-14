# Historical execution checkpoints

This preserves the pre-simplification training history. Old commands and module names may be retired; use the current README for supported entry points.

# Qozon LangChain project foundation

> Current reconciled phase plan and execution ledger: [PLAN.md](PLAN.md). The sections below preserve incremental checkpoint history; use the current plan for status and next steps.

## Integration preference

For this training project, prefer current LangChain documentation, examples,
libraries, and documented third-party integrations whenever they meet the need.
Explain any gap before introducing custom implementation code.

For each action, explain the inputs, library/stack, function or command executed,
outputs, verification, local versus remote processing, and what is implemented
versus planned. Show technical execution details throughout the training work. A listed
integration is supported by LangChain's ecosystem; it is not necessarily a
recommendation for every use case.

For Phase 2, use the documented `langchain-docling` loader for PDF extraction,
`langchain-text-splitters` for recursive splitting, `langchain-openai` for
embeddings, and `langchain-chroma` for the vector store as those steps are built.
These integrations are now installed and the local chunking, embedding, indexing,
and retrieval workflow is implemented.
The existing custom PDF downloader handles private Supabase authentication,
streaming size limits, and local-file checks before document extraction.

## Phase 2: PDF download and extraction

`knowledge_base/pdf/downloader.py` downloads an existing private PDF from
Supabase Storage into a local directory. Configuration reads `SUPABASE_URL`,
`SUPABASE_SECRET_KEY`, and `SUPABASE_STORAGE_BUCKET` from the local environment.
The secret is backend-only and excluded from settings representations.

`knowledge_base/pdf/loader.py` uses LangChain's `DoclingLoader` through the pinned
`langchain-docling[local]==3.0.0` integration. It defaults to physical PDF pages
1–3 for the first review and enables local OCR for scanned text. Initial use may
download Docling's local model weights; it makes no OpenAI calls. OCR reads text
in images, not descriptions of image content.

The loader uses Docling's hierarchical block export to retain provenance without
the default tokenizer-based hybrid splitting. Documents keep `page_numbers`,
`source`, and `document_sha256` metadata for the upcoming recursive splitter.
Partial conversions, empty text, and missing page references are withheld.
Extracted text is still raw source data: document privacy/content checks must
precede embeddings and model prompts. Downloads and local indexes belong under
the ignored `data/` directory.

The extraction tests exercise the real LangChain/Docling export with synthetic
offline conversion results; the full offline suite is supplemented with corpus, persistence, retrieval, and
citation tests. The question endpoint supports both Phase 1 Q&A and the optional
PDF RAG workflow documented below.

The selected `Canon-of-Medicine.pdf` was downloaded from the configured private
bucket (86,588,927 bytes). Real local Docling conversion of physical pages 1–3
completed successfully with OCR enabled: 19 retained text blocks, 1,936 characters,
and provenance on pages 2 and 3. No retained text block referenced page 1. This
checks the sample only, not whole-book extraction quality.

The loader now explicitly enables OCR, table structure, picture images, and
full-page images at scale 2.0. Pass `assets_dir=Path("data/pdf-assets")` to
`load_pdf_documents` to export sources before hierarchical text chunking.
`knowledge_base/pdf/assets.py` uses Docling's public export methods to save
full-page PNGs, detected picture/table crops, complete table Markdown and JSON,
and a rich Docling JSON document with referenced images. A manifest links each
asset to captions, element references, provenance, pages, and the original file
hash. Text blocks carry `asset_manifest` and `element_refs` metadata. Each run
uses a separate private directory; failed exports or downstream extraction
failures remove only that run's output. Assets remain raw, unreviewed source data.

A fresh real conversion of physical pages 1–3 preserved three page images and
one picture, alongside 19 text blocks. No table was detected in this sample;
table export was initially tested on synthetic structured tables. Full-book
extraction has since saved 49 real table assets. The saved sample page images and picture were inspected visually. The
original PDF and full pages remain available if detected crops are incomplete.
Docling picture descriptions remain disabled; no OpenAI calls happened during extraction.
A separate checked description step is implemented below.

References: [LangChain Docling integration](https://docs.langchain.com/oss/python/integrations/document_loaders/docling),
[Docling converter](https://docling-project.github.io/docling/reference/document_converter/).

## Phase 2: independent ingestion models

`llm/model.py` now has `build_openai_table_summarizer` and
`build_openai_image_visualizer`. Both use LangChain `ChatOpenAI` and default to
GPT-5.6 Terra, independently of the existing GPT-6 Luna question-answer adapter.
Constructing an adapter makes no API request. Calling its async method does.

The table adapter's `summarize_table(table_markdown, context=...)` accepts the
complete approved table and context. The image adapter's
`describe_image(image_bytes, mime_type="image/png", context=...)` sends image
pixels together with the caption/context and returns text, not a generated image.
PNG, JPEG, and WebP are accepted with basic header checks and a 10 MiB byte limit;
this is not a full image decoder. Context is limited to 8,000 characters, tables
to 100,000 characters. Oversized inputs are rejected without silently truncating
tables or calling a model. These document limits are separate from the API's
200-character user-question limit.

Choose models and output budgets independently through settings:

```dotenv
QOZON_TABLE_MODEL_NAME=gpt-5.6-terra
QOZON_IMAGE_MODEL_NAME=gpt-5.6-terra
QOZON_TABLE_OUTPUT_MAX_TOKENS=512
QOZON_IMAGE_OUTPUT_MAX_TOKENS=512
```

Each builder reads its model setting directly: `settings.table_model_name` or
`settings.image_model_name`. To select `gpt-6-luna` for one task, change that
task's setting without changing the other tasks. Either builder also accepts an
explicit `max_output_tokens` override. The local `.env` is not modified; default ingestion choices work
without adding these optional overrides. All three adapters buffer output and
disable automatic raw payload tracing, streaming, provider storage, and automatic retries. Provider
errors are replaced with fixed safe codes.

The picture adapter is connected through `knowledge_base/pdf/descriptions.py`.
It requires approval of the exact picture bytes, checks source text locally,
redacts configured PII, blocks secrets, and checks generated text before saving
one description linked to its picture and page. Text detectors do not sanitize
image pixels. Visual review covers only the selected training crop; generated
descriptions are not automatically verified for factual accuracy.

One live GPT-5.6 Terra call succeeded with the reviewed picture and its attached
caption. Docling had attached a reproduction credit rather than the descriptive
caption. The exporter now preserves nearby text on the same page. Offline tests
confirm that context reaches the adapter with PII redaction. Automatic approval
review stopped a second live call containing these additional private-source
text blocks. The user subsequently explicitly approved processing 98 pictures
and 48 tables, including captions and nearby text, in the full-book plan.
That approval is recorded in `data/pdf-summaries/processing-plan.json`.
The original successful sample description remains available.

The agreed processing order is to finish local OCR and export text, tables,
pictures, captions, and full-page references for the whole PDF before generating
any additional Terra descriptions. Review the extraction coverage and preserved
assets first, then apply privacy checks and describe the approved tables and
pictures. Full-book local CPU extraction is complete: all 641 physical pages,
98 pictures, and 49 tables. Its checkpoint is `data/pdf-assets/full-book/progress.json`;
only fully exported page ranges count as complete. The checkpoint records
counts, the active page range, measured throughput, and an evolving estimate.
Completed batches are retained for resumption, including blank pages with no
OCR text. One converter reuses the cached models across batches. All 49 structured
tables were checked for empty text; the table on physical page 6 needs repair and
is excluded from the approved description run. Whole-book OCR and layout accuracy
remain unverified; original pages and assets are preserved.

The table and picture adapters are connected to the ingestion processor.
The question API reads the persisted index; ingestion is a separate explicit job.
It never downloads, extracts or reindexes the book per question. Offline tests cover independent
model selection, complete table transfer, image-plus-context messages, invalid
input/no-call behavior, output withholding, and LangChain Responses API
serialization through mocked HTTP. The normal suite makes no paid calls.

`knowledge_base/pdf/processing.py` checks approved source fingerprints, performs
local source and generated-text checks, and saves one JSON summary with original
asset and page references in `data/pdf-summaries/`. Cached results are reused
when source, model, privacy policy, and processing version are unchanged.
`processing_job.py` runs the explicitly approved plan and checkpoints every item
in `data/pdf-summaries/progress.json`. There are no automatic provider retries.
A connection failure can be followed by processing untouched assets with
`--continue-pending-after-failure`; previously failed calls are not repeated.
The job makes no uploads, embeddings, or indexing calls. Source approval does
not establish visual privacy or factual accuracy of generated descriptions.

```bash
uv run --locked python -m qozon_langchain.knowledge_base.pdf.processing_job --plan data/pdf-summaries/processing-plan.json
```

The approved full-book run finished 146 attempts, saving 90 picture descriptions
and 48 table summaries. Eight picture descriptions remain unsaved: four
connection failures and four incomplete outputs, on physical pages 148, 150,
152, 154, 156, 158, 238, and 407. Saved outputs were checked again through the
local text gate, and original asset/page links were verified. The report is
`data/pdf-summaries/verification.json`. The table on physical page 6 remains
excluded because its structured text is empty.

The user approved `data/pdf-summaries/retry-plan.json` for those eight pictures
with a 1,024-token image output limit. All eight retry calls succeeded and saved
their results in `data/pdf-summaries/retry-1/`, retaining all 138 earlier results.
The temporary process environment supplied the retry budget; `.env` was not edited.
The combined set contains 98 picture descriptions and 48 table summaries.
`data/pdf-summaries/summary-index.json` lists the 146 selected successful results
across both runs, and `completion.json` / `verification.json` report final checks.
The initial and retry progress files retain their separate attempt histories.
The page-6 table remains excluded pending extraction repair. Generated descriptions and whole-book extraction accuracy remain only partially
reviewed. The training index records factually_verified=false; indexing does not
certify source accuracy. Integrity checks cover all selected assets, while visual
comparison sampled the page-2 picture and page-5 contents table.

References: [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra),
[LangChain multimodal inputs](https://docs.langchain.com/oss/python/integrations/chat/openai#multimodal-inputs-images-pdfs-audio).

This is the first setup checkpoint for progressively richer, start-to-end builds.
The Python package, isolated environment, locked dependencies, local configuration,
installation report, and a foundation health endpoint are implemented. The
local gated question service is also implemented and tested with fake models.
The live LangChain OpenAI adapter is implemented and one gated synthetic request
has passed with GPT-6 Luna. The API is wired to the service and a real HTTP
question has passed with the user's configured 512-token budget. PDF retrieval is now implemented; multi-agent orchestration remains a later phase.

One explicitly enabled OpenAI service test and one live HTTP question have
succeeded; private Supabase PDF download is also connected. Asset publication
and SQL retrieval remain separate future steps.
Normal tests and installation checks remain offline. Git was not initialized.

## Local setup

The distribution is `qozon-langchain`; the import package is `qozon_langchain`.
This checkpoint uses **CPython 3.12.14** and the existing **uv 0.12.9** installation.
Python 3.12 was already installed, is supported by the selected LangChain packages,
and keeps this learning environment on one tested Python minor version. The exact
interpreter is recorded in `.python-version`; `requires-python` currently limits
the project to the 3.12 series, starting at this installed patch. Broader Python
support should be validated before relaxing that constraint.

From this directory:

```sh
uv sync --locked
uv run --locked qozon-langchain
uv run --locked pytest -q
```

`uv sync` installs this package in editable mode in the dedicated `.venv`. The
report command prints Python/package versions and implemented capabilities;
it does not load configuration, contact providers, or print credentials. Runtime and development direct
versions are pinned in `pyproject.toml`, with resolved transitive versions and
artifacts recorded in `uv.lock`. Use `--locked` to catch dependency/lock drift.
The resolver uses `prerelease = "explicit"` because the installed FastAPI and
Chroma telemetry dependencies require the explicitly pinned
`opentelemetry-semantic-conventions==0.65b0`. Other direct packages remain pinned
to stable releases. `uv.lock` records the resolved versions.

Verified direct package versions at this setup checkpoint:

| Package | Installed version |
| --- | --- |
| FastAPI | 0.143.0 |
| Uvicorn | 0.54.0 |
| LangChain | 1.4.4 |
| langchain-openai | 1.7.0 |
| pydantic-settings | 2.15.0 |
| python-dotenv (direct) | 1.2.4 |
| pytest (development) | 9.1.1 |
| httpx (development) | 0.28.1 |

Four foundation tests passed, and `uv pip check` confirmed compatibility of the
57 installed packages. The first locked sync stopped on a prerelease-policy
mismatch; recording the policy above fixed the retry without discarding the lock.

If the terminal cannot find uv, this machine's existing executable is
`/Users/sardoravaz/.local/bin/uv`.

## Foundation health endpoint

```sh
uv run --locked uvicorn qozon_langchain.api.app:app --host 127.0.0.1 --port 8000
```

`GET http://127.0.0.1:8000/health` reports `stage: foundation` when RAG is disabled,
or `stage: pdf_rag` when enabled, plus local index readiness and record count.
It reports `question_api: wired`. `model_calls_enabled` reports whether a local key and
output-token budget are configured; `provider_connection: not_checked` makes
clear that health does not contact OpenAI or verify access.
`POST /questions` validates the request and calls the gated service. A missing
key or output budget returns HTTP 503 with `model_not_configured` after input
checks. Blocked input returns HTTP 400, a review hold HTTP 409, withheld unsafe
output HTTP 502, and a provider timeout HTTP 504. Other unavailable provider/check
conditions return safe HTTP 503 errors.
Invalid requests return HTTP 422 without echoing submitted values.
This health check proves local app/package
installation, not provider connectivity, security enforcement, or production readiness.

The separate setup viewer is served only from the sibling `phase-tracker` folder:

- Phase plan: `http://127.0.0.1:8894/index.html`
- Live setup events: `http://127.0.0.1:8894/setup-progress.html`

These URLs depend on the retained local preview server. Its stage log is a setup
record, not application telemetry. The phase tracker and browser notes remain
separate from this package.

## Local dotenv configuration

`python-dotenv==1.2.4` is now a direct dependency managed by uv. It was already
installed transitively through `pydantic-settings`; the uv update records our
explicit requirement in `pyproject.toml` and `uv.lock` without a redundant package.

The local credential file belongs at
`/Users/sardoravaz/udemy-lc/langchain-enterprise/project_Qozon/.env`.
Use the setting name `OPENAI_API_KEY` and enter its value only in your local editor.
The provided local template has a blank key; do not print it or paste it into chat.
For another checkout, create the file from the safe example without overwriting
an existing configuration:

```sh
cp -n .env.example .env
chmod 600 .env
```

Run commands from `project_Qozon`. `Settings()`/`get_settings()` load the working
directory's `.env` through pydantic-settings/python-dotenv only when requested;
importing configuration does not read credentials or create a model client.
There is no extra global `load_dotenv()` call. Process environment values override
`.env` values; tests or callers may pass `_env_file` explicitly. A blank
`OPENAI_API_KEY` means unconfigured. Restart the process after editing cached
settings, or deliberately clear `get_settings.cache_clear()` during development.

`.gitignore` excludes `.env` and its variants while allowing the safe
`.env.example`. The key field is excluded from settings representations, uses
`SecretStr` for normal serialization, and settings error text hides input values.
Do not log `get_secret_value()`, dump credentials, or assume structured error
objects are safe to publish. Model connectivity and the PDF RAG API are now
implemented; this installation/configuration report does not test live access.

The dotenv update passed three isolated synthetic configuration tests plus the
four foundation tests (seven total). They verify local-file loading, environment
precedence, hidden key representations/serialization, and sanitized error text.
The checks do not read the project's credential file or make any model calls.

## Package layout

```text
project_Qozon/
├── .python-version
├── .venv/                         # Dedicated, ignored environment
├── .env.example                  # Blank credential placeholder
├── .gitignore
├── pyproject.toml
├── uv.lock
├── README.md
├── src/qozon_langchain/
│   ├── __init__.py
│   ├── __main__.py               # Implemented installation report
│   ├── api/
│   │   ├── app.py                # Implemented foundation health app
│   │   ├── questions.py          # Wired endpoint with safe HTTP errors
│   │   ├── dependencies.py       # Lazy provider construction and health readiness
│   │   └── schemas.py            # Implemented strict request/response shape contracts
│   ├── core/
│   │   ├── config.py             # Implemented local settings
│   │   └── logging.py            # Planned safe logging/tracing
│   ├── services/
│   │   └── question_service.py   # Gated workflow tested with a fake model
│   ├── llm/
│   │   ├── model.py              # Implemented LangChain OpenAI adapter
│   │   └── prompts.py            # Initial English Q&A prompt
│   ├── security/
│   │   ├── input_gate.py         # Implemented local pre-model checks
│   │   ├── output_gate.py        # Implemented buffered output checks
│   │   ├── sanitization.py       # Implemented local text helper
│   │   ├── screening.py          # Implemented local screening signals
│   │   ├── pii.py                # Built-in/custom middleware and local checks
│   │   ├── custom_pii.py         # Selected local English/U.S. regex detectors
│   │   ├── secrets.py            # Implemented selected credential signals
│   │   └── policies.py           # Implemented configurable training profiles
│   └── knowledge_base/
│       ├── evidence.py           # Planned shared citation contracts
│       ├── pdf/                  # Future source package
│       ├── web/                  # Future approved Wikipedia package
│       └── sql/                  # Future directory package
└── tests/
    ├── api/
    │   ├── test_app.py
    │   ├── test_dependencies.py
    │   ├── test_questions.py
    │   └── test_schemas.py
    ├── core/
    │   ├── test_config.py
    │   ├── test_dependencies.py
    │   └── test_dotenv.py
    ├── services/
    │   └── test_question_service.py # Fake tests + opt-in live test
    ├── llm/
    │   └── test_model.py
    └── security/
        ├── test_custom_pii.py
        ├── test_input_gate.py
        ├── test_output_gate.py
        ├── test_privacy.py
        ├── test_sanitization.py
        └── test_screening.py
```

Every package directory has an `__init__.py`. Planned files contain documentation
only, with no fake implementation or placeholder answers. Source-specific
packages belong inside `src/qozon_langchain`, not beside the application root.

## Implemented local sanitization

`security.sanitization.sanitize_question()` validates the original 1–200-character
input before cleanup, applies canonical Unicode NFC normalization, and collapses
whitespace to single spaces. It preserves punctuation, case, and legitimate
joiners. Unwanted controls, surrogate code points, and the explicitly listed
invisible separators/direction overrides are rejected with fixed error codes
that do not echo the submitted question. This is a conservative input policy;
it does not identify every hidden character or obfuscation technique.

This helper is used by the local input gate. The service and model connection
still remain to build.
The question route continues to return service-not-ready. All 64 tests passed
after the sanitization update, without reading the credential file or making model calls.

## Implemented local screening

`security.screening.screen_question()` returns a frozen decision containing only
`allow`, `review`, or `reject`, fixed rule identifiers, and matched training-group
names. It uses the sanitization checks, preserves the original 200-character
budget, and uses a compatibility-normalized scanning copy for selected variants.
It performs no logging, model calls, network operations, or credential reads.

Invalid input is rejected. Stronger signals hold a request for review; weak
references, role-play wording, and dashes alone do not block it. Selected patterns
cover the eight training groups (authority spoofing, internal-info extraction,
private-data disclosure, conversation spoofing, obfuscated instructions, tool
misuse, persistent manipulation, and indirect source instructions), plus the
earlier general instruction-manipulation examples. This is selected heuristic
coverage, not a comprehensive detector. Educational quotations can still require
review, and unseen or paraphrased attacks can pass. An allow decision is only
permission to continue the remaining checks, not authorization to call tools.

All 100 tests passed after adding screening. The input gate and service must
still enforce its decisions and complete PII handling before any model call.
No automatic review mechanism or retrieved-document screening is implemented;
future sources require a separate content budget and policy. The question API
continues to return service-not-ready.

## Implemented PII, secrets, and training policies

`policies.training_policy()` explicitly builds one of three configurable profiles:

| Built-in type | Mixed profile | Block profile | Redact profile |
| --- | --- | --- | --- |
| email | redact | block | redact |
| credit_card | block | block | redact |
| ip | redact | block | redact |
| mac_address | redact | block | redact |
| url | allow | block | redact |

The user selected redaction for input/output PII. `training_policy()` therefore
defaults to the redact profile for all five built-ins and five custom types. Secrets
remain blocked separately. The mixed and block profiles are optional alternatives,
not the selected defaults. None is activated in the API until the gates are wired.
Public contacts/URLs can still be personal data; callers must supply a policy.
Different policies can be supplied to input and output checks. Explicit custom
rules may also use mask/hash; deterministic hashing is pseudonymization, not
guaranteed anonymity. Policy validation requires each built-in type exactly once,
allows each supported custom type at most once, and rejects unknown types.
Policy selection does not implement GDPR/HIPAA compliance or language enforcement.

`pii.check_pii()` uses the installed LangChain middleware's public local hooks
for input and buffered output. It checks blocking matches before transformations,
returns no text when blocked or a checker fails, and hides checked text from
result representations. Do not serialize result objects or unchecked payloads
into logs. `pii.build_pii_middleware()` returns explicitly enabled input/output
middleware for a future LangChain agent; no agent is created now, and tool-result
checks remain off until tools are introduced. `custom_pii.custom_pii()` supplies
local regex match spans to the same middleware for the following training types:

| Custom type | Current detection scope |
| --- | --- |
| `ssn` | Nine-digit or three-two-four hyphenated shapes; no issued-number verification |
| `address` | Numbered English street names with selected suffixes/abbreviations and optional units; city/state/ZIP and other formats are not covered |
| `medical_card` | Explicit medical-card label followed by a 4–40-character alphanumeric/hyphen identifier containing a digit |
| `date_of_birth` | DOB/birth-date labels followed by two-digit month/day and two- or four-digit year with consistent separators; basic ranges, not full calendar validation |
| `age` | One- to three-digit numbers in years-old/year-old phrases |

All custom types redact by default on both local gates, also in the mixed profile;
the block profile blocks them. Names are deliberately excluded at the user's
request. Phone numbers, other government/medical identifiers, image content,
unlabeled birth dates and unsupported address formats still need additional
detectors and context policy. Regex can miss sensitive data and can also match
ordinary numbers or public business addresses; these rules do not establish
GDPR/HIPAA compliance. Raw match objects contain sensitive values and must not be
logged or serialized.

`secrets.check_secrets()` blocks selected private-key headers, credential-shaped
keys/tokens, bearer tokens, credential assignments and credential-bearing URLs.
It returns only fixed rule identifiers, performs no remote credential verification,
and does not promise exhaustive detection. Gates must check secrets separately
before applying PII policy, including when ordinary URLs are allowed. Review
signals hold; checker failures withhold text; secret matches block.

All 132 tests passed offline, including the selected redaction default, both PII directions, configurable policies,
overlapping matches, checker failures, representation privacy, and selected secret
examples. No real credential file was read and no model calls were made.
The API continues to return
service-not-ready rather than call a model.

## Implemented local gates

`input_gate.check_input(question, policy=...)` validates original length and
characters, normalizes text, obtains screening signals, blocks secrets, holds
review signals, and applies the selected input PII policy. Secret matches block
even when screening also requires review. Only an allow result carries the
checked text to use for a future model call. Fixed blocked/review messages do not
echo submitted text. Checker errors withhold the question.

`output_gate.check_output(answer, policy=...)` checks the complete buffered answer
against the response schema, character policy, secrets, PII handling, and a basic
display policy. It rejects raw HTML tags and selected active URI schemes, then
rechecks transformed text before releasing it. The client must also escape text
and constrain links. These checks are not a general content classifier or factual
or citation verifier. The API uses a separate 512-token generation budget;
the 200-character question cap does not apply to answers. A separate output
character ceiling is not configured.

Both gates require an explicit privacy policy. Use the selected
`training_policy()` redaction profile for input and output. Gate results hide text
from repr and forbid text on block/review; callers must not serialize unchecked
payloads or raw error details. No logging, model calls or credential reads occur
inside the gates. They do not enforce English language or tool permissions.

At the gate-only checkpoint, all 163 tests passed, including review holds before
PII checks, secret priority, fail-closed checker errors, input redaction, buffered
output filtering, and final revalidation. Gates are not yet connected to the
question service/API at that checkpoint. Service and adapter progress is recorded
below; the API still returns service-not-ready until wiring is completed.

After custom PII integration, all **227 tests passed** offline. They include
synthetic values, exclusions and number boundaries, exact spans, multiple values,
custom redaction on input/output middleware hooks, both gates, and the deliberate
preservation of names. The question API still returns service-not-ready; no live
model or credential-file checks were performed.

## Implemented service with fake-model verification

`services.question_service.answer_question()` accepts a question, an explicitly
supplied privacy policy, and a model implementing async `generate_answer()`.
It runs the input gate, calls that model once with approved text only, runs the
output gate on the complete answer, and returns a `QuestionResponse` containing
only approved output. Review/block decisions stop the workflow. Provider and
unexpected checker failures produce safe `QuestionServiceError` attributes;
raw exception details are not returned. Do not log exception contexts or locals.

The model protocol allows tests to supply a fixed fake without constructing a
provider client or reading credentials. No fake is used by the production API.
The live adapter is now implemented with a request timeout and no automatic
retries. The API uses the user's configured 512-token budget and safe HTTP error
mapping, as recorded in the API connection section below.

Run the fake-model tests from this project directory:

```sh
.venv/bin/python -m pytest tests/services/test_question_service.py -q
```

All **23 service tests** pass, and the full offline suite passes **250 tests**.
Coverage verifies zero calls for rejected/held input, redacted text before the
model, buffered/redacted output, blocked unsafe output, safe failures, and gate
execution order. OpenAI was not contacted and the local key file was not read.
Those results describe the offline service checkpoint. `POST /questions` still
returns service-not-ready until API/service wiring.

## Live model test (explicit opt-in)

The actual-model test lives in the same `tests/services/test_question_service.py`
file as the fake-model tests. It is marked `live_model` and skipped unless
`QOZON_RUN_LIVE_TEST=1`. It loads the local configured key only when selected and
sends one synthetic arithmetic question through both gates. It uses a test-only
128-token output budget without changing `.env` or the lasting API output policy.

```sh
QOZON_RUN_LIVE_TEST=1 .venv/bin/python -m pytest tests/services/test_question_service.py::test_live_openai_question_flow -q
```

The adapter uses LangChain `ChatOpenAI`, the configured `gpt-6-luna` model, the
Responses API, buffered generation, reasoning effort `none`, a 30-second request
timeout, zero automatic retries, and `store=False`. LangSmith tracing is disabled
inside the adapter so unchecked generated text is not traced before output checks.
This does not establish a complete provider data-retention or logging policy.
Incomplete, empty, and tool-call responses are withheld; provider errors become
fixed safe categories. No history or retrieval tools are enabled.

Verified on October 9, 2026: **258 offline tests passed, 1 live test skipped** in
the default suite. The explicitly enabled **live test passed** and verified the
checked answer `4` to `2 + 2`. The initial sandbox attempt could not connect; the
network-enabled retry succeeded. The API key was loaded locally and never printed.
This proves the service/provider connection; it does not prove comprehensive PII
detection. API wiring and its separate verification are recorded below.

## Implemented API/service connection

`api.questions.ask_question()` now awaits the existing `answer_question()` service
with the user's redact policy. `api.dependencies.get_answer_model()` supplies a
lazy model wrapper; blocked or held input never reaches provider construction or
generation. A successfully constructed client is cached. Configuration and
provider details are never returned in HTTP errors. Restart after config changes.

Default API tests use isolated configuration and dependency overrides with fake
models, never the project's `.env` or OpenAI. Tests verify HTTP redaction, block
and review decisions, provider/answer error mapping, lazy construction, and health
without provider calls. Pytest uses importlib mode so mirrored test folders can
reuse filenames. **275 tests passed, 1 opt-in live test skipped.**

The endpoint wiring is complete. The user set `QOZON_OUTPUT_MAX_TOKENS=512` in the
local `.env`; loading settings verified 512 without printing the key. The safe
`.env.example` records that selected budget. The code default remains unset, so
other checkouts must deliberately configure a positive budget.

Verified live HTTP flow on October 9, 2026: the local Uvicorn app on
`http://127.0.0.1:8000` returned HTTP 200 for `/health`, reporting the question API
wired and model configuration present. A synthetic arithmetic `POST /questions`
returned HTTP 200 and `{"answer":"4"}` through the service, both gates, and GPT-6
Luna with the configured 512-token budget. Health remains a configuration-only
check; it does not perform or guarantee provider authentication. This run adds
one live model request to the earlier service smoke test. The development server
is bound to loopback and runs without access logging; its lifetime depends on the
retained execution session.

## Phase 1 contract and remaining integration

Framework: **LangChain**. Selected provider/model: **OpenAI GPT-6 Luna**,
API identifier **`gpt-6-luna`**. The configured key and adapter have passed one
synthetic live test. Store
credentials locally in an ignored `.env` or an appropriate secret store when
integration is authorized; do not paste them into chat or print/log them.
The `.env.example` key value is intentionally blank.

The planned workflow is:

```text
New English question → INPUT GATE → LangChain / GPT-6 Luna
                     → buffered OUTPUT GATE → approved answer
```

**Input gate, before any paid invocation:** accept text/nonempty questions of at
most **200 original Unicode characters**, counting spaces and punctuation per new
question. History, system prompts, and retrieval are outside that cap and use a
separate aggregate token budget. Preserve original length validation; safely
normalize Unicode/whitespace without changing meaning, silently truncating,
deleting all dashes, or banning slang. Reject unsupported controls. Selected local
regex/context signals follow explicit allow/review/reject policy; review holds
without a model call by default. The eight training categories are not a claim
of complete regex coverage. Apply the selected local PII/scope policy before
handoff, and withhold input on required checker errors/unavailability/timeouts.

**Output gate, after generation and before delivery:** buffer the full answer,
check structure/nonempty output, selected PII/secrets/content policy and safe
display, then release only the approved transformed response. A required failure,
error, or timeout withholds raw output and yields a safe fallback. Phase 1 must not
stream unchecked output. The API generation budget is **512 tokens**, separate
from the 200-character input cap. An additional output character ceiling is
not configured. Local checks do not
prove factual accuracy; RAG evidence/citation checks arrive in Phases 2 and 3.

Local PII detection needs no extra paid call. LangChain's built-ins are `email`,
`credit_card`, `ip`, `mac_address`, and `url`; input checks default on, output checks
must explicitly use `apply_to_output=True`, and tool-result checks must be enabled
when tools are added. The selected custom regex detectors above are implemented;
phone, broader government-ID/bank and contextual detection remain to choose.
Names are excluded by the current training choice. Apply allow/mask/redact/block according to context:
public data can still be personal, and approved business contacts need deliberate
handling. Secrets detection is separate. The tracker’s Common PII, GDPR, and HIPAA
tables are training reference profiles, not implemented detector coverage or
compliance claims.

Configure safe logging/tracing at every boundary. An output gate cannot protect
earlier provider/middleware traces; a model necessarily generates before that
gate. `SecretStr` and the excluded settings representation reduce accidental
configuration exposure but do not provide full payload redaction or trace policy.

## Original roadmap and inputs (historical; current status is in PLAN.md)

2. One local text PDF with two-step retrieval/generation and page citations.
3. Layered guards, grounded evidence verification and bounded permissions/cost.
4. Supabase Storage PDFs and pgvector; separate ingestion, authorization,
   versions, page provenance, OCR/vision for scans/images.
5. English U.S. directory SQL with the actual supplied schema and restricted
   read-only roles, validated allowlisted queries, limits and timeouts.
6. User-approved English Wikipedia links with section/revision citations.
7. LangGraph specialist routing, shared evidence, synthesis, and temporary
   isolated session/checkpoint memory behind one question API.
8. Redacted LangSmith evaluations/traces and operations/deployment review.

Russian, Uzbek, Kyrgyz, Kazakh, and Tajik come later. No Supabase, PDF, or Wikipedia
integration package was intentionally added at this checkpoint. LangGraph and
LangSmith libraries may appear transitively through LangChain; installing a
dependency is not implementation or activation of those workflows.

Next inputs: review the Phase 1 contract and choose local privacy/content/failure
policies, then provide OpenAI access through local configuration. Supabase schema,
restricted access, PDF samples, embedding/OCR choices, and Wikipedia links arrive
incrementally. Do not mark Phase 1 complete until its question workflow and gates
are built and exercised.

## Validation and documentation

Foundation checks cover installed-package imports, configuration defaults and
key-safe representation, and the real health endpoint/absence of a question
route. They do not test or claim working detectors, model answers, RAG, or
enterprise security. No test calls a model or a remote data source.

Primary references consulted for this checkpoint:

- [uv project guide](https://docs.astral.sh/uv/guides/projects/)
- [LangChain installation](https://docs.langchain.com/oss/python/langchain/install)
- [LangChain OpenAI integration](https://docs.langchain.com/oss/python/integrations/chat/openai)
- [OpenAI GPT-6 Luna model reference](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [LangChain PII middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
- [Pydantic settings and dotenv support](https://docs.pydantic.dev/latest/concepts/pydantic_settings/#dotenv-env-support)
- [python-dotenv documentation](https://bbc2.github.io/python-dotenv/)

Recheck stable APIs when implementing each phase; validate compatibility and
update pins/lock deliberately rather than installing every product automatically.

## Resume full-book local extraction

Run from the project directory. A file lock prevents duplicate concurrent jobs.
The runner verifies the PDF fingerprint and previous page coverage before resuming.

```bash
HF_HOME="$PWD/data/model-cache" HF_HUB_OFFLINE=1 uv run --locked python -m qozon_langchain.knowledge_base.pdf.extraction_job --batch-size 10 --threads 6 --device cpu
```

This local job makes no description, embedding, or cloud API calls. Its progress
file reports completion only after all physical pages have been exported.
CPU processing is the default. `--device cpu` forces CPU use for Docling layout
and table models and disables MPS/CUDA in RapidOCR. Six CPU threads are used.
The previous Apple GPU run stopped after page 53 with a native PyTorch MPS
convolution crash; the CPU run resumes from the saved page-54 checkpoint.
Changing devices resets the time estimate so GPU throughput is not used to
predict CPU completion. The optional `--device auto` mode retains accelerator
auto-selection, but is not used for this resume.
OpenCV is pinned to 4.13.0.92 after two native KleidiCV resize crashes in 5.0.0.93.
OpenCV resize workers are limited to one to avoid nested oversubscription.

Page-range batches can separate a table that continues onto another page.
Preserved tables and their page references must be reviewed and continuation
parts joined where appropriate before summaries are generated. Full pages and
the original PDF are retained; extraction completion does not mean OCR accuracy
or table continuity has been verified for every page.

References: [Docling accelerator configuration](https://docling-project.github.io/docling/_generated/examples/run_with_accelerator/),
[Docling RapidOCR options](https://docling-project.github.io/docling/reference/pipeline_options/#docling.datamodel.pipeline_options.RapidOcrOptions),
[OpenCV pinned release](https://pypi.org/project/opencv-python-headless/4.13.0.92/).

## Phase 2: executed corpus and local RAG

All commands below run from the project directory. Ordinary tests are offline.
The embedding command and explicitly enabled smoke script make paid OpenAI calls.

1. `knowledge_base/pdf/chunking.py` walks body elements in saved rich Docling JSON
   in reading order. It skips furniture, picture/table subtrees and captions,
   reconstructs text groups with element/page spans, and checks source text using
   the document-specific screening budget, secret detection and selected PII
   redaction. It checks the final assembled chunks again.
2. LangChain `RecursiveCharacterTextSplitter` uses 1,000 characters, target
   overlap 150 and exact start offsets. Short descriptions remain whole; long
   descriptions split with their shared parent asset reference. A redaction after
   splitting records the original source window; its new offsets are explicitly
   scoped to that redacted parent chunk.
3. The saved corpus has **2,450 chunks**: 2,249 ordinary text, 127 image-description
   chunks from 98 pictures, and 74 table-summary chunks from 48 tables. Coverage
   checks find no missing nonwhitespace accepted text. All 641 physical page
   exports exist; some pages may naturally have no searchable ordinary text.
   There are no privacy holds. One original item and one assembled chunk were
   redacted. The empty table on physical page 6 stays excluded.
4. JSONL records, source hashes, settings, exclusions and review notes are saved in
   `data/pdf-chunks/`. The original pages, pictures and full table files are not
   modified. The contents table on page 5 has uneven exported column alignment;
   its original crop is retained. Whole-book factual/OCR review is not complete.
5. `knowledge_base/pdf/indexing.py` uses LangChain `OpenAIEmbeddings`,
   `text-embedding-3-small`, 1,536 dimensions, batches of 32, no automatic
   provider retries, and a persistent cosine-distance Chroma collection under
   `data/chroma/`. All **2,450 records** were saved and verified across reopen.
   A failed batch after 768 saved records was resumed successfully.
6. A narrow LangChain Embeddings adapter caches successful corpus vectors in
   private SQLite before Chroma insertion, indexed by model, dimensions and text
   hash. The cache does not store source strings or query text. It allows a local
   insertion failure to resume without repeating completed embedding requests.
   A lost provider response can still require repeating that failed request;
   exactly-once billing is not guaranteed.
7. `knowledge_base/pdf/retrieval.py` combines Chroma semantic candidates with
   LangChain BM25 lexical candidates using weighted reciprocal-rank fusion and
   explicit source-phrase matching. The live contents question initially found
   index pages; lexical/phrase matching recovered the actual contents table on
   physical page 5. Retrieval quality settings are initial training choices, not
   a calibrated confidence guarantee. Chroma distance filtering applies to the
   semantic branch, and lexical candidates require matching query terms.
8. Canonical chunk records resolve physical pages and full parent summaries.
   The resolver verifies asset fingerprints, includes complete checked tables
   when they fit the per-evidence context budget (without cutting rows), and
   sends at most one original PNG per answer. Prompt table formatting removes
   redundant padding only; saved originals remain unchanged. Oversized tables
   fall back to their summary/reference, so detailed row questions may need a
   later row-aware retrieval step.
9. `/questions` runs the input gate before retrieval, sends the approved question
   separately from untrusted evidence to the configured answer adapter, applies
   the output gate, validates `[S1]`-style source identifiers, and returns resolved
   citations in `sources`. Unknown or missing citations withhold the answer.
   Empty retrieval returns an insufficient-evidence answer without generation.
   Citation checks verify references, not factual entailment of every claim.

```bash
uv run --locked python -m qozon_langchain.knowledge_base.pdf.chunking
uv run --locked python -m qozon_langchain.knowledge_base.pdf.indexing --batch-size 32
uv run --locked pytest -q
QOZON_RAG_ENABLED=true uv run --locked python scripts/verify_pdf_rag.py --live
```

The first command is local. The second makes embedding calls only for missing
records/cache entries. The last command is opt-in and makes real query embedding
and answer calls. `--kind table` limits the smoke script to that case.

```dotenv
QOZON_RAG_ENABLED=true
QOZON_EMBEDDING_MODEL_NAME=text-embedding-3-small
QOZON_EMBEDDING_DIMENSIONS=1536
QOZON_RAG_TOP_K=4
QOZON_RAG_MAX_DISTANCE=0.65
QOZON_RAG_CONTEXT_CHARACTERS=16000
```

The first three settings were saved locally; keys were preserved. Model or
embedding-dimension changes require a matching index. Restart the server after
settings changes. Embedding queries run per request, while corpus vectors persist.
`/health` checks local readiness without calling a provider.

The local server runs at http://127.0.0.1:8000/docs. Live checks exercised ordinary
text, tables and picture evidence through the API path, and a synthetic secret
was blocked. Reports are in `data/chroma/live-api-verification.json` and the
index checkpoint is `data/chroma/index-progress.json`.

Final offline verification: **394 passed, 2 opt-in live tests skipped**. A real
HTTP request with a synthetic SSN returned a cited contents answer without
exposing that SSN. This verifies the exercised flow, not every possible PII
format or factual claim. The HTTP result is saved in
`data/chroma/http-verification.json`.
The final HTTP check also added a narrow credential-disclosure rule for phrases
such as "my password is ..." and "our API key is ...". Regression tests verify
those requests stop before retrieval. Secret detection remains format-specific.

The reviewed page 2 picture and page 5 table now have public source links in
`canon-of-medicine-chunks`. The API returns IDs, physical pages and verified URLs,
never local filesystem paths. Other assets remain local until separately reviewed
and published. The original private PDF is retained.

`langchain-community==0.4.2` provides the currently documented BM25 integration;
its package emits a sunset warning. The retriever dependency is isolated so a
maintained standalone integration can replace it when selected. Chroma analytics
remains disabled. The explicit LangSmith integration below replaces the earlier
no-tracing configuration for the question workflow.

References: [recursive splitting](https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter),
[Chroma integration](https://docs.langchain.com/oss/python/integrations/vectorstores/chroma),
[OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings),
[BM25 integration reference](https://reference.langchain.com/python/langchain-community/retrievers/bm25/BM25Retriever).

## LangSmith observability and evaluation

`langsmith==0.14.7` is a direct, pinned dependency. Pydantic Settings reads these
unprefixed environment variables from the local `.env`; they do not need `QOZON_`:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your-local-key
LANGSMITH_PROJECT=project_qozon
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
# Default: IDs/pages, decisions, timings and tokens; no question/book/answer text.
QOZON_LANGSMITH_TRACE_CONTENT=false
# Optional for keys that can access multiple workspaces:
# LANGSMITH_WORKSPACE_ID=your-workspace-id
QOZON_EVALUATION_MODEL_NAME=gpt-5.6-terra
```

Restart Uvicorn after configuration or code changes. `core/observability.py`
uses the SDK's `trace` context manager for an explicit `question_workflow` span
with child spans for `input_gate`, `retrieve_evidence`, `generate_answer`, and
`output_gate`. Retrieval logs checked text, chunk IDs, physical pages, content
types, and whether an original picture was attached. Model spans record token
counts and model name; the workflow records the checked answer and citations.
By default, `QOZON_LANGSMITH_TRACE_CONTENT=false` strips all question, answer,
passage and judge-explanation text at the SDK upload boundary. The spans retain
IDs/pages, decisions, timings and token counts. Set it to `true` only after
authorizing checked content uploads, including the dataset and evaluation run.
Raw gate input, unchecked model replies, image bytes, local paths, API keys,
and exception tracebacks are excluded. Block/review decisions are visible without
the submitted text. Automatic LangChain/model tracing remains disabled underneath
these spans. Trace failures do not replace successful answers; traces flush at
server shutdown. This is heuristic privacy filtering, not a comprehensive
sensitive-data guarantee.

The six current cases are in `evals/pdf_rag_cases_v4.json`: ordinary text, a table,
a picture, a synthetic secret, a review hold, and synthetic SSN redaction. The
versioned dataset is `project_qozon-pdf-rag-v4`. The original v1 cases remain in
`evals/pdf_rag_cases.json`, and the preface-only wording revision remains in
`evals/pdf_rag_cases_v2.json`. V3 also aligns the SSN-redaction question with the
translator's two purposes, records visual review of pages 2, 4 and 5, and revises
the picture reference to use its printed caption and visible features. Table
extraction alignment remained a review note rather than an expected answer claim.
V4 records the repaired table columns and explicitly linked picture caption;
the expected answers are unchanged from v3.
`evaluation/langsmith_rag.py`
syncs examples with stable IDs, rejecting changed references under the same version
name. The evaluation target calls the same `answer_question` service as the API;
recording wrappers expose selected evidence and model-call counts only to the
evaluation, without changing the public response schema.

```sh
# Validate all cases locally; no network calls:
.venv/bin/python scripts/evaluate_langsmith.py
# Upload examples to the authorized LangSmith workspace:
.venv/bin/python scripts/evaluate_langsmith.py --sync
# Run six cases, with paid query embeddings, answers, and a model judge:
.venv/bin/python scripts/evaluate_langsmith.py --run
# Run the same cases with deterministic scores only:
.venv/bin/python scripts/evaluate_langsmith.py --run --no-judge
# Rerun only the corrected preface case; the complete dataset is still synced:
.venv/bin/python scripts/evaluate_langsmith.py --run --case-id preface-purpose
```

Book-derived references, selected passages and checked answers are sent to
LangSmith when syncing/running or when enabled API traces are recorded. Obtain
the source owner's approval for those uploads before running these commands or
restarting a tracing-enabled API. PDF files and image attachments are not uploaded
to LangSmith. The text/vision judge receives the original retrieved picture
through OpenAI and checks its answer, not just the stored image description.

`Client.aevaluate` runs one case at a time in a named experiment, with corpus
fingerprint, model, prompt version, and retrieval settings. Deterministic feedback
scores workflow outcome, privacy at the model/release boundary, retrieval of an
expected physical page/content type, citation integrity, and citation of a
reference page. A separate Terra judge scores correctness and groundedness; failed
judge calls appear as `judge_available=0`, never a passing score. Token counts and
latency are available from explicit spans; cost estimates depend on LangSmith's
recognition of the model and pricing. Results are saved locally at
`data/evaluations/langsmith-latest.json` and in LangSmith's Datasets & Experiments.

For table/picture citations, `PublicSourceEvaluator` also scores
`source_url_integrity` against the canonical chunk metadata/publication registry,
and `public_source_access` by fetching the canonical URLs with an anonymous HTTPX
client and comparing sizes and SHA-256 hashes. It never follows model-invented URLs
or sends secret headers. These checks do not establish source factual accuracy.

References have their review status stored per example. The v3 review compared
the preface and contents topics with the full-page originals, and the picture
with its original page and crop. The table's extracted columns remain misaligned;
the empty structured table on page 6 remains excluded. The picture's faint scan
still limits fine-detail claims. These checks cover the evaluation sources only,
not the complete book. Judge feedback cannot establish
that OCR, extracted tables, or every factual claim are correct. Keep the offline
pytest safety/HTTP tests alongside these evaluations. Ordinary pytest runs force
LangSmith tracing off and make no LangSmith uploads.

References: [LangSmith RAG evaluation](https://docs.langchain.com/langsmith/evaluate-rag-tutorial),
[custom spans](https://docs.langchain.com/langsmith/annotate-code),
[prevent sensitive trace logging](https://docs.langchain.com/langsmith/mask-inputs-outputs).

Verified October 11, 2026: **408 offline tests passed, 2 live tests skipped**.
The saved key accesses `project_qozon`; a synthetic workflow trace was read back
from LangSmith. `scripts/verify_langsmith.py` created the separate
`project_qozon-integration-smoke-v1` dataset and ran three invented/fake-model
cases, with all deterministic scores passing. It makes no OpenAI calls or PDF
reads. This verifies cloud connectivity and scoring, not book retrieval quality.
The report is `data/evaluations/langsmith-smoke.json`. The six-case book dataset
and its evaluation require explicit approval of book-derived text and
`QOZON_LANGSMITH_TRACE_CONTENT=true`.

After that approval, experiment `project_qozon-pdf-rag-1189bf15` ran all six
book cases. All six cloud runs and 32 feedback records were read back and
verified. Workflow outcome and privacy scored 6/6; expected-page retrieval and
citation integrity scored 4/4 on answering cases. Citing the expected page,
Terra correctness, and Terra groundedness each scored 3/4. These are small-sample
baseline measurements, not a general quality guarantee.

The flagged case is `preface-purpose`. Retrieval found the preface on physical
page 4 as S4, but the answer cited the contents table on page 5 as S1. There is
also a question/reference ambiguity: the question names Avicenna's original
Canon, while the reference describes the translator's purposes for this edition.
The candidate explicitly distinguished Avicenna's own purpose. Keep the original
failing feedback and review the reference alignment before treating this as a
confirmed generation failure; revised cases need a new dataset version.

The original experiment and detailed checked outputs are preserved in
`data/evaluations/langsmith-baseline-v1.json` and
`data/evaluations/langsmith-baseline-v1-details.json`. Checked content uploads were
enabled for the approved evaluation process only. The running API retains its
metadata-only observability setting.

The corrected preface question is: "According to the translator's preface, what
are the two purposes of this treatise?" Experiment
`project_qozon-pdf-rag-cb79a469` reran this case alone against
`project_qozon-pdf-rag-v2`. All seven scores passed, including Terra correctness
and groundedness. The answer gave both purposes and cited physical page 4.
The saved cloud run and all seven feedback records were read back and verified.
The archived v2 result is in `data/evaluations/langsmith-preface-v2.json`, with checked outputs in
`data/evaluations/langsmith-preface-v2-details.json`. The original v1 experiment
and its failing feedback remain available; the other five cases were not rerun.

The subsequent six-case v3 experiment, `project_qozon-pdf-rag-09fe9ad7`, completed
on October 11, 2026. All six runs and 32 feedback records were read back from
LangSmith. Workflow and privacy passed 6/6; retrieval, citation integrity,
reference-page citation, Terra correctness and groundedness passed 4/4 on the
answering cases. The secret and review-hold cases made zero model calls. The
reworded SSN case used redacted input and cited physical page 4.

Versioned reports are `data/evaluations/langsmith-six-cases-v3.json` and
`data/evaluations/langsmith-six-cases-v3-details.json`; the source review is
`data/evaluations/reference-review-v3.json`. The original v1/v2 experiments remain
unchanged. Page 5 table-column extraction and the faint page 2 scan remain quality
limitations despite passing evaluation scores. The image answer still hedges
the scene's roles because its retrieved description does not state the printed
caption as confidently as the original page does; caption-context linkage is a
remaining ingestion improvement. No chunk, summary or vector index was changed
for this evaluation run.

Supabase source-asset destination: `canon-of-medicine-chunks` was verified as a
public bucket in the configured project on October 11, 2026. The separate
`SUPABASE_ASSETS_BUCKET` setting is loaded as `Settings.supabase_assets_bucket`.
`SUPABASE_STORAGE_BUCKET=pdf_rag` continues to identify the private original-PDF
bucket. Reviewed source files are published and resolved through the API's sources.
Public asset URLs
allow anyone with the URL to retrieve a file; the backend secret key stays local.
See [Supabase bucket access models](https://supabase.com/docs/guides/storage/buckets/fundamentals).

### Reviewed source repairs and public citation links

`knowledge_base/pdf/repairs.py` applies the explicit local plan in
`data/source-repairs/reviewed-plan-v1.json`. It reconstructs page 5's 27 contents
entries as Topic/Printed page cells using Docling `TableData` and `TableCell`.
The JSON preserves `$ref` aliases and the original crop/provenance; reconstructed
cells do not fabricate bounding boxes. Page 2's picture links the descriptive
caption, manuscript note and credit through Docling caption refs. Extracted files,
the old corpus and old index manifest are backed up under
`data/source-repairs/backup-v1`; the original PDF and crop bytes are unchanged.

Automatic approval review initially rejected sending these repaired payloads to
Terra for new summaries. `scripts/refresh_reviewed_sources.py` first saved manually
reviewed, privacy-checked summaries with `model=manual-source-review`, without
mislabeling them as Terra output. After the user explicitly approved the repaired
table and picture/caption transfer, the script's `--terra` mode regenerated both
with their independent `gpt-5.6-terra` adapters. The manual and original records
remain available; the active summary index points to the new Terra records in
`data/pdf-summaries/source-repairs-terra-v1`. Source fingerprints are validated
before either call, and successful results are cached for safe resumption.
Retrieval also appends the linked printed caption directly to picture evidence.

LangChain's recursive splitter rebuilt the corpus at 1,000 characters with 150
overlap in `data/pdf-chunks-source-links-v1`. It contains 2,449 chunks with all
641 physical pages covered. `indexing.py` created a new persisted Chroma collection
using the existing SQLite vector cache: three changed texts required new
`text-embedding-3-small` vectors across two API batches. Other vectors were reused.
That corpus remains as the manual-review baseline. The active local `.env` now
points `QOZON_RAG_CHUNKS_DIRECTORY` at `data/pdf-chunks-terra-source-links-v1`:
2,451 chunks (2,249 text, 128 image-description, 74 table-summary), with all 641
physical pages covered. Four changed summary texts required new embeddings in
one API batch; the remaining vectors were reused from SQLite. The new persisted
collection is `qozon_pdf_4bc4557d847bb2dfbb95d905`. The API was restarted and its
health endpoint confirms 2,451 indexed chunks. The four published source URLs
are unchanged because the source assets and their fingerprints are unchanged.

`publication.py` uses the existing HTTPX library with the Supabase Storage API.
The explicit fingerprint-approved selection contains four files: picture PNG,
table PNG, corrected table Markdown and structured JSON. Upload keys include
document, asset and file hashes; uploads never overwrite existing objects.
Each object is downloaded anonymously and compared byte-for-byte before its
entry is saved in `data/pdf-assets/publication.json`. Secret headers are used only
for bucket verification and upload. Queries resolve links from the local registry,
requiring matching document/source fingerprints; stale or unpublished entries
produce no URL. This does not add Storage network calls to ordinary retrieval.

`Evidence` carries the resolved URLs into `question_service.py`, which attaches
them only to citations actually used in the checked answer. `SourceCitation`
adds optional `url`, `image_url` and `structured_url`: picture `url` opens its PNG;
table `url` opens Markdown, with PNG and JSON alternatives. Other citations have
null URL fields. These application-resolved URLs are not generated by the LLM.

```sh
# Paid summary refresh: only after explicit approval of the repaired sources.
.venv/bin/python scripts/refresh_reviewed_sources.py --terra
# Only the fingerprint-approved sources in the reviewed publication plan:
.venv/bin/python scripts/publish_reviewed_assets.py --publish
# Repeat --case-id to evaluate both affected cases:
QOZON_LANGSMITH_TRACE_CONTENT=true .venv/bin/python scripts/evaluate_langsmith.py --run --case-id contents-table --case-id physician-picture
```

Verification: 412 offline tests passed, two live tests skipped. Both real HTTP
question requests returned 200 with the expected citations and all four public
URLs verified without credentials; the picture answer now identifies the scene
from its printed caption. Report: `data/source-repairs/live-api-source-links.json`.
The v4 LangSmith experiment `project_qozon-pdf-rag-b4260c9c` reran the table and
picture cases with all 14 feedback scores passing. Reports are saved in
`data/evaluations/langsmith-source-links-v4.json` and the corresponding details
file. The faint picture scan and unrepaired/excluded page 6 structured table
remain limitations; this is not a whole-book accuracy review.

The subsequent Terra refresh reran those same two v4 cases without changing their
questions or reference answers. Experiment `project_qozon-pdf-rag-404d263b`
passed all 14 feedback scores; the cloud runs and public source links were read
back and verified. Reports: `data/evaluations/langsmith-terra-source-refresh.json`
and `data/evaluations/langsmith-terra-source-refresh-details.json`. Local review,
approval and index reports are under `data/source-repairs/terra-refresh-v1`.

The dataset version check now ignores LangSmith's service-managed `dataset_split`
metadata while continuing to reject changed questions, gold answers and review
metadata. Its regression tests passed (8 evaluation tests); the processing,
indexing, retrieval and publication checks also passed (21 tests).

### Incremental source and Chroma updates

`knowledge_base/pdf/incremental.py` updates corrected extracted text and approved
summaries inside the existing Chroma collection. It does not run OCR, regenerate
Terra summaries, publish Supabase files or start LangSmith evaluations. The source
preparation in `chunking.py` is separated from splitting: `collect_source_units()`
assembles the existing reading-order groups and individual summaries, while
`split_source_unit()` calls LangChain's recursive splitter only on changed groups.
Overlap stays within each group; structural edits may change several neighboring
groups, and all affected groups are compared rather than assuming one edit means
one chunk. Scanning source JSON and checking fingerprints still reads the saved
sources; it does not re-split or re-extract the book.

`source-units.json` beside the active chunk corpus records a stable group identity,
its version fingerprint, its chunk IDs and any post-split holds/redactions. A
group identity uses document ID, manifest location, content type and first Docling
element reference. Its fingerprint covers cleaned text, spans, citation metadata,
splitter configuration and privacy policy. Unchanged groups reuse their exact
chunk records. Changed/new groups are split and privacy-checked; removed or held
source content loses its old chunks. New chunk IDs are added and obsolete IDs are
deleted through LangChain Chroma; the collection is not recreated. Only text/model/
dimension cache misses call OpenAI embeddings. Metadata changes reuse cached
vectors, and source-file-only changes need no Chroma record writes.

Run these commands from `project_Qozon` after saving the source corrections or
updating the approved summary index:

```sh
# Existing legacy corpora: one-time adoption, no splitting or embedding calls.
# Already completed for the current 1,184 units / 2,451 chunks.
.venv/bin/python -m qozon_langchain.knowledge_base.pdf.incremental --initialize

# Local preview: reports split units, added/deleted chunks and embedding misses.
.venv/bin/python -m qozon_langchain.knowledge_base.pdf.incremental

# Apply: may make paid embedding calls for changed texts only.
.venv/bin/python -m qozon_langchain.knowledge_base.pdf.incremental --apply

# If a previous apply was interrupted: use its saved target, without re-splitting.
.venv/bin/python -m qozon_langchain.knowledge_base.pdf.incremental --resume
```

The updater holds an exclusive filesystem lock and checks existing stored IDs,
texts and citation metadata. It saves staged target files and
`data/chroma/incremental-journal.json` before mutation, then caches embeddings
before writing Chroma. It verifies the persisted target collection before
committing corpus/index manifests and removing the journal. An interrupted commit
leaves retrieval unavailable until `--resume` completes; it cannot serve a mixture
of old and new records. Keep sources unchanged while resuming the frozen target.
Original corpus and index headers are retained in `data/chroma/incremental-stage`.
The latest count report is `data/chroma/incremental-last-update.json`.

`LocalPDFRetriever` holds a shared lock while retrieving and checks the committed
revision before every query. On a revision change it reloads canonical chunks and
rebuilds its local BM25 keyword index; it keeps the same Chroma collection. Summary
file hashes are checked against the committed corpus before returning their full
text. After this code deployment, ordinary incremental updates need no API restart.
Requests during an exclusive update receive the existing safe retrieval-unavailable
error response. A new PDF/document ID, embedding configuration or chunking version
requires an explicit new baseline; this updater does not automatically align pages
between two different PDFs. Changed original picture/table assets must still have
their new fingerprint approved and their summaries regenerated before indexing.

The current book's unchanged apply retained all 2,451 chunks and collection
`qozon_pdf_4bc4557d847bb2dfbb95d905`, with zero split units, embedding calls or
Chroma record writes. Synthetic tests exercise a changed text group, a summary,
metadata-only changes, deletion/secret holds, keyword refresh, reader locking and
recovery after interruptions during insertion, deletion and corpus writes.
Final validation: 428 tests passed and two opt-in live tests were skipped. The
restarted API returned HTTP 200 for health and reported the existing index ready.

### Publishing the remaining source assets

`scripts/prepare_publication.py` creates `data/source-publication/inventory.json`
from completed extraction manifests, approved summary references, the publication
registry and `data/source-publication/review/visual-review.json`. Checks cover file
integrity/PNG decoding, matching reviewed fingerprints, caption refs on the same
physical pages, nonempty structured table text and unchanged privacy-checked table
Markdown/JSON. All 147 extracted crops were inspected in 14 contact sheets. This
is a coarse crop/layout review, not full transcription or factual verification.
Missing captions, faint scans, tiny extraction fragments and questionable OCR
caption context remain recorded quality notes; captions were not invented.

The remaining selection contains 144 assets (97 pictures and 47 tables), comprising
238 files / 24,139,319 bytes. The two previously published assets contribute four
more files. The empty structured table on physical page 6 remains excluded. After
automatic review requested a more specific authorization, the user explicitly
approved making this whole selection public in `canon-of-medicine-chunks`.

```sh
# Local inventory only; no network calls or model calls.
.venv/bin/python scripts/prepare_publication.py
# Prepare a plan; preserves prior approval only for the same approved fingerprints/bucket.
.venv/bin/python scripts/prepare_publication.py --write-plan
# After explicit public-upload approval is recorded in the plan:
.venv/bin/python scripts/publish_reviewed_assets.py --publish --plan data/source-publication/publication-plan.json
```

The publication plan is `data/source-publication/publication-plan.json`. The
uploader checkpoints each fully verified asset in `data/pdf-assets/publication.json`
and reports progress in `data/source-publication/upload.log`. Connection failures
are retried at most three times per request, using fresh connections, with fixed
safe error codes. Hash-addressed upload keys and `x-upsert=false` make a retry after
a lost response safe: the existing object is reused and its public bytes checked.
Publication does not alter the active 2,451 chunks, cached corpus vectors or Chroma
collection. Queries resolve newly published source links from the registry without
restarting the API. Live checks of the newly published page-15 table and page-56
picture are saved in `data/source-publication/live-api-verification.json`.

Completion verification: all 146 summarized assets (98 pictures and 48 tables)
now have verified public links, totaling 242 files / 25,164,548 bytes including the
four previously published files. The final inventory has 146 already-published
assets and one excluded table. `data/source-publication/publication-verification.json`
confirms every indexed parent asset resolves its expected links and that the active
corpus fingerprint/Chroma collection stayed unchanged. Both real API requests
returned HTTP 200, cited their expected physical pages and passed anonymous URL
byte checks. 438 offline tests passed; two opt-in live tests were skipped.

The v4 table/picture rerun, experiment `project_qozon-pdf-rag-7a3806ff`, passed all
18 feedback scores, including the two new public-source checks per case. The cloud
runs and feedback were read back and verified. Reports:
`data/evaluations/langsmith-public-source-links.json` and
`data/evaluations/langsmith-public-source-links-details.json`. This checks the two
evaluation cases and publication integrity, not full-book factual accuracy.

## Phase 3: local synthetic evaluation preparation

`evals/phase3_synthetic_cases_v1.json` contains 25 fictional cases: four grounding,
two conflict, four citation, nine retrieved-instruction, two benign-control, two
privacy and two availability probes. These use invented box/marble passages,
synthetic identifiers and fixed replies; they do not include book content. The
existing six-case book dataset and LangSmith experiments remain unchanged.

`evaluation/phase3_local.py` uses Pydantic to validate the versioned dataset,
unique case IDs, fixture sizes and the distinction between two test layers.
Source-gate cases pass raw synthetic passages through `checked_document_text`,
including all eight local screening categories. Service cases provide already
checked fictional `Evidence` through a fake retriever and a scripted answer
model, then call the existing `answer_question` service and output gate.
`evals/phase3_synthetic_cases_v1.schema.json` exposes the Pydantic JSON Schema for
inspection and editor validation. No new library is required.

The runner uses Python's `asyncio` for the async service, `re` for fixture-specific
phrase checks, and `unittest.mock.patch.dict` to disable tracing in its own process
and restore the caller's environment afterward. It neither opens Chroma nor
constructs a provider client. Tests block socket connections even when the
caller's tracing setting was enabled.

```sh
# Validate the authored cases without executing their probes:
.venv/bin/python scripts/evaluate_phase3_local.py
# Run the local gates/service with fake retrieval and scripted replies:
.venv/bin/python scripts/evaluate_phase3_local.py --baseline
# Verify the harness itself, including its no-network regression check:
.venv/bin/python -m pytest tests/evaluation/test_phase3_local.py -q
```

The baseline is saved to `data/evaluations/phase3-local-baseline.json`, with every
case's expected result, observed result and individual checks. Initial baseline:
18 cases pass and seven expose gaps. Five concern answer verification: irrelevant
evidence, unsupported claims with valid citation IDs, silently selected conflicting
evidence, citation to the wrong passage, and a fabricated page claim. A spaced
instruction evades local screening; an educational quotation of an attack is held
for review, a usability tradeoff rather than an unsafe release.

These results probe guard behavior with scripted replies, not live-model accuracy.
Phrase checks are specific to these fixtures; the simulated timeout does not
establish a real deadline or cost budget. No classifier or tool authorization is
implemented by this preparation. A successful runner exit means the baseline was
recorded; inspect `status` and the failed cases before treating a guard as passing.
Phase 3 guard implementation and later live evaluations remain separate work.

## Phase 3: conservative evidence verification v1

The shared question service now calls `security/evidence_verification.py` after
the output privacy gate and before resolving public source citations. Its
`extractive-v1` policy uses Python standard-library `re` for citation groups,
sentence boundaries and bounded conflict patterns; `unicodedata` for NFC
normalization; and a frozen `dataclass` for the verification result. No new
package, classifier download or provider call is needed. The existing LangChain
`OpenAIAnswerModel` prompt now requests complete source sentences and immediate
citations to match this policy.

Each claim must match a complete sentence in the passages cited immediately
after it. Case and whitespace normalization are allowed; internal punctuation,
negation, numbers and word order remain meaningful. Word overlap, matching a
substring, or support found only in a different uncited passage is insufficient.
Uncited additional assertions are withheld. Explicit **physical** page claims
must match the associated canonical source pages; a verbatim printed-page cross
reference is not confused with physical PDF numbering. Fixed, pure uncertainty
statements may become a canonical abstention without claiming a book citation.

The verifier detects a bounded set of simple English count conflicts with the
same subject/predicate/object, and exact sentence pairs differing by `not`.
Selecting one side silently is withheld. When a reply acknowledges uncertainty
and cites all involved passages, the service replaces generated prose with the
actual source sentences and a fixed uncertainty message. This replacement passes
the output privacy gate again. Verification emits only policy/mode/count metadata
to its explicit observability span; unapproved generated text is not added there.

The API returns safe HTTP 502 errors for unsupported claims, detected conflicts
without disclosure, and invalid source/page references. A verifier execution
failure returns HTTP 503 (`evidence_check_unavailable`) and never releases the
buffered answer. Input limits bound verification to 16,000 answer characters,
100,000 aggregate evidence characters, 12 passages and 64 citation groups.

```sh
.venv/bin/python scripts/evaluate_phase3_local.py --baseline --output data/evaluations/phase3-evidence-verification-v1.json
```

The original 18/25 baseline is preserved. The new report passes **23/25**, including
all service-layer cases and all five prior evidence-verification gaps. The two
remaining failures are the unchanged source-screening probes: a spaced-out attack
instruction and a benign quotation held for review. 474 offline pytest tests
passed; two opt-in live tests were skipped. Existing citation-resolution fixtures
were corrected to contain the sentences their fake answers actually cite; the
25 authored Phase 3 cases and six book-reference cases were not changed.

This policy establishes conservative text/source alignment, not general semantic
entailment, exhaustive contradiction detection, query relevance or underlying
historical factual truth. Valid paraphrases may be withheld. Generated summaries
can themselves be inaccurate; verification cannot repair extraction/summary
errors. Image pixels are not verified, so unsupported visual interpretations are
withheld even if an image was attached. `factually_verified` source flags are not
promoted by this check. Live book/model evaluations and screening improvements
remain separate work. An already running API process needs a restart to load the
new service and prompt; this offline verification did not restart it or contact
OpenAI, LangSmith or Supabase.
