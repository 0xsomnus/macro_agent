# Run and inspect the desk API

For a guided terminal walkthrough, start with [Getting started](GETTING_STARTED.md). This guide is the HTTP reference for manual requests and client development. The CLI uses these same session and approval endpoints. All shell commands run from the repository root.

Updated 2026-10-06. [ADR 017](ADR/017-drf-and-openapi-boundary.md) selects DRF and drf-spectacular through delegated implementation judgment. Start with [Django setup](DJANGO_DEVELOPMENT.md). This internal API persists exact drafts, manual or model-proposed interpretation previews, explicit user approval, paper declarations and private history. [PAPER_POSITIONS.md](PAPER_POSITIONS.md) specifies attachment/revision/closure and synthetic publication context. It does not configure monitoring.

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

Compilation accepts exactly this shape, with a new command UUID, the reviewed draft revision and provider/model copied from the fetched catalogue:

```json
{
  "command_id": "4cfd4951-e00d-42df-b829-4ad0c762043c",
  "expected_revision": 1,
  "provider_id": "nanogpt",
  "model_id": "your/exact-catalogue-id"
}
```

All endpoints derive ownership from the session; POST requires CSRF. Strict JSON rejects duplicate keys, unknown fields and coercion. The response separates `compilation.document` questions/hypotheses from `thesis.draft.interpretation`, labelled `model_compilation`. Approval still uses the existing exact-version/hash endpoint. A new proposal preserves the current approval.

HTTP 200 can contain `compiled`, `stale`, `failed`, `running` or `outcome_unknown`; inspect the state before offering approval. A changed provider or draft returns 409, admission exhaustion 429, and unavailable configuration/catalogue 503. Repeating the same admitted command returns its original result and current disposition without another provider call. GET never restarts an interrupted call. A late result or intervening draft/approval change cannot install stale meaning. The text-only compiler supplies no verified factual conflicts, current macro context or monitoring readiness.
