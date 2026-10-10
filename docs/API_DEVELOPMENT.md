# Run and inspect the desk API

For a guided terminal walkthrough, start with [Getting started](GETTING_STARTED.md). This guide is the HTTP reference for manual requests and client development. The CLI uses these same session and approval endpoints. All shell commands run from the repository root.

Updated 2026-10-10. [ADR 017](ADR/017-drf-and-openapi-boundary.md) selects DRF and drf-spectacular through delegated implementation judgment. Start with [Django setup](DJANGO_DEVELOPMENT.md). This internal API persists exact drafts, model review cards, attributable refinement answers, explicit user approval, paper declarations and private history. [PAPER_POSITIONS.md](PAPER_POSITIONS.md) specifies attachment/revision/closure and synthetic publication context. Configure continuous monitoring separately through the [internal runner](CONTINUOUS_RUNNER.md).

## Session and authority

Create an account through Django's existing operator tools. There is no public registration endpoint. All thesis endpoints derive the actor from the authenticated session, including staff and superusers. Client-selected owner, actor, role, or timestamps are rejected. Missing and foreign thesis IDs return the same 404.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/v1/session/` | Return identity and masked CSRF token, and establish the CSRF cookie |
| POST | `/api/v1/session/login/` | Authenticate `{username, password}` with CSRF protection even before login |
| POST | `/api/v1/session/logout/` | Require an authenticated session, CSRF token, and empty JSON object |
| GET, POST | `/api/v1/theses/` | List private theses or create an unapproved draft |
| GET | `/api/v1/theses/{id}/` | Read current draft and separate current approval |
| POST | `/api/v1/theses/{id}/proposals/` | Save a new draft without changing the approval |
| POST | `/api/v1/theses/{id}/approvals/` | Approve the exact displayed draft and interpretation |
| GET | `/api/v1/theses/{id}/history/` | Read one consistent, bounded history snapshot |
| GET | `/api/v1/schema/` | Read the authenticated desk OpenAPI document |

Session operations use ordinary Django views with explicit CSRF protection. They are documented here and are outside the generated desk schema. The schema describes the implemented DRF serializers and routes; TypeScript client generation remains open. API responses are marked non-cacheable. Session errors and CSRF failures may use Django's ordinary responses, including HTML; a UI must handle HTTP status before assuming JSON.

For local HTTP testing, keep cookies and credentials in the ignored `.local/` directory. Fetch identity first:

```sh
curl --cookie-jar .local/cookies.txt http://127.0.0.1:8000/api/v1/session/
```

Set a task-local `macro_csrf_token` variable to the returned token. Put your operator credentials in `.local/login.json`. Login with the cookie and token:

```sh
curl --cookie .local/cookies.txt --cookie-jar .local/cookies.txt \
  -H 'Content-Type: application/json' -H "X-CSRFToken: ${macro_csrf_token}" \
  --data-binary @.local/login.json http://127.0.0.1:8000/api/v1/session/login/
```

Replace `macro_csrf_token` with the new token returned by login before the next write. Login and logout rotate the token. Use these same cookie and header options for draft, proposal, and approval requests. Local HTTP is loopback development only; deployed cookie, proxy, origin, rate limiting, and account provisioning configuration still need review.

## Exact draft and approval contracts

Creation accepts this shape. Replace the illustrative command UUID with a fresh canonical UUID for each new operation:

```json
{
  "command_id": "71782284-c6be-465e-8d0f-d4089b01b0bb",
  "text": "Gold may benefit if real yields fall.",
  "interpretation": {
    "drivers": ["Real yields", "USD"],
    "horizon": "Several weeks",
    "invalidation_signposts": ["A sustained rise in real yields"]
  }
}
```

The interpretation supplied on creation or proposal is manual and labeled `origin: user_supplied`. Empty driver/signpost arrays and a null horizon are permitted, so this storage boundary does not invent missing conviction. The separate internal compilation endpoint proposes `origin: model_compilation` meaning and keeps challenge questions and agent hypotheses separate, as described below.

A proposal uses the same shape plus `expected_revision`, copied from the current thesis. Approval requires a new command UUID and these values copied unchanged from the reviewed response:

| Request field | Source |
| --- | --- |
| `expected_revision` | `thesis.revision` |
| `thesis_version_id` | `thesis.draft.text_version.id` |
| `text_digest` | `thesis.draft.text_version.text_digest` |
| `interpretation_version_id` | `thesis.draft.interpretation.id` |
| `interpretation_digest` | `thesis.draft.interpretation.digest` |

Both draft versions, their exact digests, and the aggregate revision are compared under protection. A 409 requires fetching and reviewing the latest state. Do not automatically approve a replacement after a conflict. Leading/trailing whitespace, line endings, and Unicode remain exact; neither text nor interpretation strings are trimmed or normalized.

For current model proposals, the interpretation hash also binds the complete review card: exact original text and answers, extracted intent, labelled proposals, counter-case, questions and evidence limitations. Reviewing that card does not adopt its agent proposals as trader belief or verify them. Legacy interpretations without cards retain their original hashes and approvals.

Every successful command returns its immutable receipt plus the current thesis. An exact retry with the same command UUID returns `command.replayed: true`, the original result, and fresh current disposition. Reusing that UUID for a different request returns 409. An old approval retry can return `command.is_current_approval: false`; the original receipt does not reactivate it. Keep the command ID and exact payload together when retrying.

Only UTF-8 `application/json` is accepted. Requests are capped at 128 KiB; unknown or duplicate fields, nonfinite numbers, invalid Unicode, NUL, and type coercion are rejected. Text is capped at 20,000 characters; interpretation arrays at 32 strings and each string at 1,000 characters. `expected_revision` is a positive JSON integer, not a string or boolean. List pagination accepts only `limit` (1 to 100) and `offset` (0 to 1,000,000).

## History and audit limits

History reads use a PostgreSQL read-only repeatable-read transaction. Each category is capped at its oldest 100 records and `truncated` reports omitted records; current detail still shows the latest pointers. Complete cursor pagination is required before external use. This bounded endpoint is not a complete export when truncated.

`approved_at`, `accepted_at`, and the manual preview's provisional `known_at` record effective times sampled inside a protected transaction. They are not measured durable commit timestamps. `replay_scope: approval_effective_time_history` makes that distinction visible. The synthetic publication adapter separately observes committed inputs and atomically admits their context pins; exact admission commit time and full operational activation replay remain unproven.

Human commands lock the owner account first, then the existing thesis when present. Approval changes additionally protect every bound brief before sampling time; position commands also protect their existing position. Initial thesis creation samples time under the owner lock before inserting its new aggregate. The owner lock serializes command identity and bound publication within that account. It is a deliberate conservative tradeoff; model reasoning and network calls must remain outside these transactions. Different accounts can progress independently.

Read-only internal administration exposes the new records without a second write path. PostgreSQL constraints and triggers protect immutable history and scoped references. They do not authenticate raw database clients or replace the application lock protocol.

## Reproduce evidence

With the local environment loaded, run:

```sh
.venv/bin/python manage.py test macro_agent.persistence.tests macro_agent.theses.tests macro_agent.positions.tests macro_agent.api.tests --noinput --verbosity 2
.venv/bin/python manage.py spectacular --file artifacts/desk-openapi.yaml --validate --fail-on-warn
.venv/bin/python manage.py sqlmigrate macro_theses 0001
.venv/bin/python tools/thesis_demo.py --output artifacts/thesis-audit.json --report artifacts/thesis-audit.md
```

The demonstration requires the synthetic gate and a development/test database. It refuses existing demo records and creates a fictional account with an unusable password. It exercises service calls, not interactive login. To inspect the existing state without writes:

```sh
.venv/bin/python tools/thesis_demo.py --inspect-only --output .local/thesis-inspection.json
```

Inspect [the thesis trace](../artifacts/thesis-audit.md), [the full thesis records](../artifacts/thesis-audit.json), [the current desk schema](../artifacts/desk-openapi.yaml), [migration SQL](../artifacts/thesis-0001.sql), and [the paper desk trace](../artifacts/paper-desk-audit.md). The demos are sequential; PostgreSQL races, real session login, CSRF, and cross-account isolation are established by the integration tests. [IMPLEMENTATION.md](IMPLEMENTATION.md) records verified counts and remaining scope. The earlier thesis-only OpenAPI artifact is historical.

## Recorded-news walkthrough boundary

`POST /api/v1/lab/theses/{id}/recorded-news/` accepts only `{"expected_approval_id": "<current reviewed UUID>"}`. The CLI invokes it after your explicit approval and paper attachment. It requires the same session/CSRF authority as other writes, exact local settings, `MACRO_ALLOW_SYNTHETIC_SETUP=1` and a development/test database name. Disabled, missing and foreign contexts are unavailable through opaque responses; this is not production ingestion.

The response separates the fictional source fact, prescribed screening, current brief, declared positions and local notification state. No thesis-specific relevance or portfolio consequence is inferred. Repeating unchanged current context returns the existing notice. An intervening approval/exposure change blocks stale publication with 409; a subsequent reviewed request must observe current context. All twelve source/macro/runtime roles remain synthetic. The schema marks this operation as a development example.

## Internal model compilation

[THESIS_COMPILATION.md](THESIS_COMPILATION.md) explains credential setup, limits and terminal review. The endpoints require exact local settings, a development/test database and `MACRO_ENABLE_MODEL_COMPILATION=1`. Disabled endpoints return opaque 404 responses. Keys come from the backend environment and are never accepted in these requests.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/v1/models/` | Fetch the configured router's normalized catalogue and explicit model IDs |
| POST | `/api/v1/theses/{id}/compile/` | Admit one private model call and propose a text-grounded interpretation |
| GET | `/api/v1/theses/{id}/compilations/{attempt_id}/` | Read the saved result and current draft disposition without inference |
| GET | `/api/v1/theses/{id}/compilation-commands/{command_id}/` | Recover an admitted compilation by its saved command UUID without inference |
| POST | `/api/v1/theses/{id}/refinements/` | Save exact answers against a current proposal's questions without provider work |
| GET | `/api/v1/theses/{id}/refinements/{refinement_id}/` | Inspect saved answers and their current applicability |
| GET | `/api/v1/theses/{id}/refinement-commands/{command_id}/` | Recover a saved answer submission by its command UUID |

Initial compilation accepts this shape, with a new command UUID, the reviewed draft revision and provider/model copied from the fetched catalogue. A later request may additionally specify `refinement_id`:

```json
{
  "command_id": "4cfd4951-e00d-42df-b829-4ad0c762043c",
  "expected_revision": 1,
  "provider_id": "nanogpt",
  "model_id": "your/exact-catalogue-id"
}
```

All endpoints derive ownership from the session; POST requires CSRF. Strict JSON rejects duplicate keys, unknown fields and coercion. The model document combines extracted drivers, horizon and invalidation with structured claim, assets, causal path, assumptions, catalysts, scenarios and monitoring scope. Every section distinguishes extracted input, proposals and gaps. Grounding names the original thesis or exact answer that supplied each quotation; attribution does not prove semantic fidelity or causal correctness.

`thesis.draft.interpretation.review_card` preserves that document and its exact inputs, with backend-controlled evidence fixed to `status: unavailable` and `references: []`. Only the original text and saved answers inform this compiler. It has no external evidence, current regime or verified asset mapping. Approval uses the existing exact-version/hash endpoint, and a new proposal preserves the current approval.

HTTP 200 can contain `compiled`, `stale`, `failed`, `running` or `outcome_unknown`; inspect the state before offering approval. A changed provider or draft returns 409, admission exhaustion 429, and unavailable configuration/catalogue 503. Repeating the same admitted command returns its original result and current disposition without another provider call. GET never restarts an interrupted call. A late result or intervening draft/approval change cannot install stale meaning. The text-only compiler supplies no verified factual conflicts, current macro context or monitoring readiness.

### Save answers, then explicitly recompile

Copy the current `thesis.revision`, compilation attempt ID and question indexes from its `refinement_issues`. Send a new command UUID to the refinement endpoint:

```json
{
  "command_id": "23113e9b-0ad9-4cac-adf9-ea56bc84e216",
  "expected_revision": 2,
  "parent_attempt_id": "df466759-8faa-47a1-a538-30eb7b6366eb",
  "answers": [{"question_index": 0, "exact_answer": "Six weeks."}]
}
```

The service derives exact question wording and prior answer history from the owner-scoped parent. Clients cannot supply a replacement question or transcript. Saving answers makes no catalogue or model request and does not change the draft, approval or original prose. Answers are immutable, at most 2,000 characters each, with at most 16 cumulative answers and 16,000 cumulative answer characters. Overflow is rejected without truncation.

For a new explicitly initiated compilation, pass the returned `refinement.id` as `refinement_id`, together with a fresh command UUID and current revision. Model switching retains the saved answers already attached to the current proposal when this field is omitted. Newly saved answers require their ID to be selected explicitly. A stale parent or answer branch requires fresh review; it cannot replace a newer proposal. A revised model result still requires its own exact approval.

Persist each command UUID before transmission. After a lost response, use the corresponding compilation-command or refinement-command GET. Recovery reads the original record with current disposition, requires no model credentials and has no POST fallback. An unavailable record does not prove that the earlier request failed or was free.

## Internal retained-news analysis

The [terminal guide](NEWS_ANALYSIS.md) explains setup and one-report review. These endpoints require exact local settings, a development/test database and `MACRO_ENABLE_NEWS_ANALYSIS=1`. The existing model catalogue separately requires the compilation gate. Credentials remain in the backend environment. Sources are restricted to gated fictional fixtures and the reviewed narrow Fed feed.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/v1/news/sources/` | Inspect permitted retained sources and current report counts |
| GET | `/api/v1/theses/{id}/news-context/` | Review exact approved meaning, complete attached paper book and exposure digest |
| POST | `/api/v1/theses/{id}/analyse-next/` | Select the next report automatically and admit at most one inference |
| GET | `/api/v1/theses/{id}/news-analyses/{attempt_id}/` | Inspect original analysis and current dependency disposition |
| GET | `/api/v1/theses/{id}/news-commands/{command_id}/` | Recover a saved request, including a no-call empty receipt, without inference |

POST accepts exactly `command_id`, `expected_approval_id`, `expected_exposure_digest`, `source_id`, `provider_id` and `model_id`. Copy the approval/digest from the reviewed context and the explicit provider/model from the catalogue. Persist the command UUID before transmission. The actor comes from the session; writes require CSRF. Duplicate JSON keys, unknown fields and coercion are rejected.

The response separates retained `analysis.context`, attributed quotation claims, independent thesis/trade routes and hypotheses. HTTP 200 may contain `analysed`, `stale`, `failed`, `running`, `outcome_unknown` or `queue_empty`. Original status and current disposition are distinct. No source work is dismissed, no thesis or trade changes, and no notice is created. Compilation and news analysis share the configured admission allowance.

Where present, the exact reviewed card is included in approved news context with its proposal and evidence labels preserved. The entire news context is limited to 65,536 encoded bytes, while a compiler card permits up to 524,288 bytes. A valid card can therefore be too large for news analysis; preflight rejects it before paid admission rather than trimming inputs.

Admission commits before one inference outside database locks; protected completion compares current source, approval and exposure. Exact command replay cannot spend or advance the queue again, including after an empty response. Invalid or uncertain attempts are never automatically tried again for the same pinned inputs. Recovery GETs require no provider credentials and have no write fallback. Missing and foreign receipts are opaque 404 responses. Changed reviewed input or command identity returns 409, admission exhaustion 429, unavailable provider/catalogue 503, and malformed requests 400. This API does not supply continuous monitoring, verified macro context, broad coverage or sourced publication authority.

## Internal daily-review inspection

The [runner](CONTINUOUS_RUNNER.md) prepares deterministic private evidence reviews. These read routes require exact local settings, a development/test database, `MACRO_ENABLE_MONITORING_PROOF=1` and `MACRO_ENABLE_CONTINUOUS_DESK=1`. They use the authenticated session's owner scope, including for staff, and require no model credentials.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/v1/theses/{id}/daily-reviews/` | List retained review summaries, newest cutoff first |
| GET | `/api/v1/daily-reviews/{id}/` | Read one complete immutable review and its present disposition |

The list accepts only `limit` (1 to 100, default 20) and `offset` (0 to 1,000,000, default 0). It returns `total`, `has_more`, source manifests and counts for new, background and deferred reports/analyses, issues, unresolved analyses and unknown reported costs. These are retained-record counts, not a coverage or materiality score. Summary reads omit large content and approved-input documents. The saved digest is an identity reference; detail verifies the content digest.

Count, page and current dependency observations share one PostgreSQL read-only repeatable-read snapshot. A later request observes a new snapshot, so offset pagination is not a stable historical cursor. Every response separates immutable `original_outcome` from `current_disposition`, with its observation time and `publication_authority: false`. Detail preserves exact content and original inputs when permission, approval, exposure or an included report changes. Missing and foreign IDs return the same opaque 404.

These operations cannot fetch sources, call a model, prepare a missing review, retry work or publish a brief. An empty list means no retained reviews for that owned thesis. Current morning-brief publication and cumulative model reasoning remain outstanding. [Frontend exploration](FRONTEND_EXPLORATION.md) proposes how a test client could present these existing contracts; client tooling is still open.
