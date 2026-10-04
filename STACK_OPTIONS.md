# Implementation stack comparison

Status: language comparison reviewed 2026-10-02; runtime comparison reviewed and Django/PostgreSQL accepted 2026-10-04. User selected Python API/research workers with a TypeScript web UI in [ADR 014](ADR/014-python-backend-and-typescript-ui.md), then Django ORM/migrations, authentication, sessions, and internal admin in [ADR 016](ADR/016-django-postgresql-foundation.md). Target Django 5.2 LTS and Python 3.13 with the psycopg driver. API/wire tooling, frontend tooling, durable worker/queue, production hosting, and model providers remain open. The comparison below preserves alternatives and tradeoffs.

## What the choice must enable

The next product increment is a thin web desk with approved thesis interpretation, continuous capture, bounded research, morning/evolving briefs, and reliable notification. Research speed matters, but a research-only script cannot validate that complete pilot experience.

PostgreSQL through Django ORM and migrations is the accepted persistence foundation. Durable worker/queue implementation remains open. Provider and model choices are replaceable; internal BYOK uses fixed provider/model configurations per role before adaptive routing or customer credit billing exists.

## Two product options

| Dimension | A: TypeScript web/API and workers | B: Python API/research workers with TypeScript web UI |
| --- | --- | --- |
| Thin web pilot | One language across web, API, and background application code. | Same web experience, with a Python backend and a cross-language API boundary. |
| Operations | One application language/toolchain; web and durable workers can still be separate processes. | Python and frontend toolchains to maintain; a static frontend does not inherently require an additional TypeScript server runtime. |
| Contract sharing | Common domain types and validators can be shared directly. Runtime validation is still required. | Versioned wire contracts and compatible validators in both languages; choose one schema authority. |
| Research ergonomics | Fits a code-first workflow if the team is comfortable researching in TypeScript. | Fits Python-based analysis and numerical workflows if those are already useful to the team. |
| Data/evaluation | Deterministic fixtures, forward evaluation, and cost measurements fit either language. | Easier reuse of Python research tools when specific existing tools are demonstrated to help. |
| Later valuation | Deterministic calculations can stay behind an interface and be added in either language later. | Can host Python calculations later, but future equities alone do not justify a second runtime now. |
| Internal BYOK | Configured adapters and per-role model choices; no routing marketplace required. | Same configuration contract; Python workers must preserve identical budgets, secret scope, and usage records. |
| Reliability/replay | Depends on transactions, immutable versions, and temporal rules, not the language. | Same invariants; keep durable publication/acknowledgement ownership explicit rather than split across API and workers. |

These operational tradeoffs are engineering judgments, not measured performance results. Neither option inherently produces better financial analysis or lower model cost. A TypeScript API with separate Python workers is another variant, but introduces two backend runtimes and needs a specific benefit to justify it.

TypeScript annotations are erased and do not validate external payloads at runtime. Provider responses, jobs, and stored records still need validation. [TypeScript handbook](https://www.typescriptlang.org/docs/handbook/2/basic-types.html#erased-types)

Python has numerical tooling such as NumPy for arrays, statistics, and simulation; its relevance depends on the actual research task. [NumPy documentation](https://numpy.org/doc/stable/user/whatisnumpy.html)

A cross-language boundary can use generated schemas; Pydantic, for example, can produce JSON Schema. This illustrates a capability, not a library selection or a guarantee that two validators behave identically. [Pydantic documentation](https://pydantic.dev/docs/validation/latest/concepts/json_schema/)

## Requirements that do not change with the stack

- Freeze `ContextManifest` and `AssessmentContextSnapshot` inputs, including source revisions, approved interpretation, exposure, and known-at cutoff.
- Preserve public availability versus actual receipt. Replay must not gain access to late backfills, later approvals, or revised macro context.
- Commit publication and `NotificationIntent` together in one relational transaction. External model calls and delivery happen outside that transaction.
- Give one component ownership of assessment publication, supersession checks, and its outbox transaction. Two languages must not imply a distributed transaction for that invariant.
- Keep worker jobs versioned and retryable, with bounded budgets, explicit failures, and stale-result rejection.
- Store provider-neutral inputs/outputs and capability limits. Provider-specific adapters handle actual differences; an interchangeable interface does not mean identical model behavior.
- Keep secrets out of job payloads, snapshots, and logs. Record provider/model configuration and usage without recording credential values.
- Test approval, temporal eligibility, duplicate delivery attempts, and revision races through the real chosen persistence boundary before claiming reliability.

## Optional research-only spike

An initial Python CLI/research spike can answer a bounded uncertainty within the chosen language direction. It is not the web pilot or a choice of production framework/storage, and it does not bypass authority and time contracts.

Its bounded task could replay recorded events against approved sample theses, make internal BYOK calls under fixed role configurations, and compare assessment usefulness/cost. Portable inputs, lawful snapshots, and results should survive a later runtime choice.

Stop or replace the spike once it has answered its named research question. Do not gradually turn a notebook or script into the always-on desk without reviewing persistence, scheduling, credentials, and the thin web workflow.

## Recommendation considered during review

Choose the smallest runtime arrangement that matches the team's current strengths and the next proof. If that proof is the end-to-end web desk and research has no demonstrated Python dependency, option A has fewer cross-language contracts to operate.

If immediate research already depends on useful Python tools, a bounded Python spike can establish that value first. Choose option B when Python research/maintenance benefits justify its cross-language frontend contracts. Offline Python evaluation remains possible alongside an otherwise TypeScript product.

The conditional recommendation above preceded the user's option B selection. The stated Python maintenance preference supplied the deciding reason. The subsequent runtime review selected Django/PostgreSQL; hosting, queue, providers, and API/wire tooling remain separate choices.

## Questions used during selection

1. Which parts do you expect to maintain or investigate yourself, and where are you currently more comfortable: TypeScript web/services, Python research, or both?
2. Is the next uncertainty mainly analytical usefulness with recorded data, or how the continuous web desk behaves end to end? What would the first proof need to show?
3. Is there a specific existing Python tool or workflow that must run in live analysis now, and what benefit would justify maintaining two language toolchains and their contract boundary?

## Accepted decision and next review

Option B is accepted in ADR 014 and Django/PostgreSQL with ORM/migrations is accepted in ADR 016. Python owns domain validation and publication; the TypeScript UI uses versioned wire contracts. Next compare API adapters and schema tooling, frontend tooling, and durable worker arrangements. The eventual schema tooling must provide one wire-schema authority and compatible validation. Queue, hosting, and provider choices remain explicitly open.

## Runtime comparison and accepted foundation

The table preserves technical options reviewed on 2026-10-03. On 2026-10-04 the owner selected Django/PostgreSQL, then Django ORM and migrations. Small independent domain modules fit either framework. The deciding preference was established security/account mechanisms, documented conventions, and less custom operations infrastructure. The independent [Python core](IMPLEMENTATION.md) remains the rule boundary.

| Proposal | Benefit | Tradeoff |
| --- | --- | --- |
| FastAPI with Pydantic | Thin API boundary, OpenAPI inspection, request/response validation; fits the small independent domain modules | Authentication, migrations, and durable workers need deliberate integration. Pydantic coercion/strictness needs review. [FastAPI features](https://fastapi.tiangolo.com/features/), [Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/) |
| Django, selected | Built-in account/session/admin tooling, ORM, and migrations | Keep authority/publication in explicit services; protect immutable records from admin edits and verify private-row access separately. [Django components](https://docs.djangoproject.com/en/5.2/) |
| PostgreSQL, selected | Concurrent service/worker persistence with row-level ordering | Running service, migrations, backups, and actual adapter integration tests required. [Locking](https://www.postgresql.org/docs/current/explicit-locking.html) |
| Local SQLite first | Simple single-host setup; short protected transactions can prove local concurrency | One writer at a time; its tests cannot validate PostgreSQL behavior. [SQLite isolation](https://www.sqlite.org/isolation.html), [use cases](https://www.sqlite.org/whentouse.html) |

The earlier FastAPI/Pydantic recommendation is superseded by the accepted Django foundation. Built-in authentication, sessions, and internal admin reduce infrastructure to assemble; they do not prove trader isolation or immutable-thesis authority. PostgreSQL is selected, but real adapter tests are required before claiming its publication guarantees. Framework background-task helpers alone do not provide the required restart/delivery guarantees. Frontend tooling, API/wire tooling, deployed authentication configuration, hosting, durable queue implementation, and providers remain open.

DRF versus Ninja is a separate open API-adapter choice. Ninja can use Pydantic-backed contracts; Django selection does not adopt either Ninja or Pydantic. Compare the API libraries against the owner's preference for established conventions before selecting one.

Port the same authority and concurrency tests to Django/PostgreSQL transactions. Ordinary Django `TestCase` transaction wrapping can conceal mistakes; `select_for_update()` has no effect on SQLite. [Django locking notes](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update).

## Next API choice, reviewed options on 2026-10-04

Recommendation for discussion: DRF fits the owner's preference for established Django conventions. No API dependency has been selected or installed.

| Choice | Benefit for this desk | Additional responsibility |
| --- | --- | --- |
| Django REST Framework | Explicit serializers, views, authentication, and permission hooks that call the small domain services | Strict input policy and maintained OpenAPI tooling. Its built-in schema generator is deprecated; its docs recommend drf-spectacular. [Schema guidance](https://www.django-rest-framework.org/api-guide/schemas/) |
| Django Ninja | Short typed endpoints and integrated schema/OpenAPI generation | Pydantic becomes a wire-contract dependency; configure strict validation and rejection of extra fields. [Ninja request schemas](https://django-ninja.dev/guides/input/body/), [Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/), [extra fields](https://docs.pydantic.dev/latest/api/config/#pydantic.config.ConfigDict.extra) |

Neither choice establishes ownership isolation. DRF's object permissions do not automatically filter lists or govern creation; every entry point must derive the actor from authentication and enforce scope. [Permission limitations](https://www.django-rest-framework.org/api-guide/permissions/#limitations-of-object-level-permissions)

Exact thesis text needs special care: DRF `CharField` trims whitespace by default. Disable trimming and reject coercion or unexpected fields. Any selected library must pass the same exact-text, approval, and foreign-owner tests. [Field behavior](https://www.django-rest-framework.org/api-guide/fields/#charfield)

Review question: do conventional DRF serializers/views with explicit schema tooling suit the owner's audit preference, or do shorter typed Ninja endpoints justify adding Pydantic as the wire boundary? Keep the independent domain models authoritative for business rules in either case.
