# Python core, Django persistence, and desk API

Updated 2026-10-06. Independent domain/application rules have a Django/PostgreSQL adapter. [ADR 016](ADR/016-django-postgresql-foundation.md) records the approved framework, ORM, migrations, authentication, sessions, and internal admin. [ADR 017](ADR/017-drf-and-openapi-boundary.md) records the delegated DRF/generated OpenAPI selection. Authenticated thesis approval, internal model compilation and manual paper-position APIs exist. Committed approval/exposure records enter protected synthetic publication context; live monitoring and the trader UI remain application work.

The [getting-started guide](GETTING_STARTED.md) is the human entry point. The internal [CLI](../tools/desk_cli.py) guides a trader through their own exact thesis, manual or model-proposed interpretation, explicit approval, paper attachment and a recorded fictional notice. [Thesis compilation](THESIS_COMPILATION.md) explains router setup, terminal model selection and the text-only analytical boundary. The CLI uses existing HTTP sessions and CSRF protection, with no database access or duplicated trading rules. Architecture references and ADRs are grouped in `docs/`.

## Inspectable modules

| Module | Responsibility |
| --- | --- |
| [models.py](../src/macro_agent/domain/models.py) | Immutable exact thesis text, meaning, events, context snapshots, runtime validation, and hashes |
| [thesis.py](../src/macro_agent/domain/thesis.py) | Owner approval binds exact text and interpretation; trusted actor and clock required |
| [exposure.py](../src/macro_agent/domain/exposure.py) | Immutable paper declarations, exact sizing strings, explicit gaps and terminal closure |
| [time.py](../src/macro_agent/domain/time.py) | Public availability, actual receipt, durable availability, UTC handling, and operational replay |
| [routing.py](../src/macro_agent/domain/routing.py) | Investigation and notice eligibility, uncertain screening, severe surprises, and fixture accumulation with offsets |
| [publication.py](../src/macro_agent/domain/publication.py) | Supported factual notice validation, dependency pins, currentness, and publication generation |
| [application/publication.py](../src/macro_agent/application/publication.py) | Protected read, decision, atomic save, and idempotent retry |
| [ports.py](../src/macro_agent/ports.py) | Persistence ordering contract independent of database libraries |
| [persistence/models.py](../src/macro_agent/persistence/models.py) | Owner-scoped versions, heads, assessments, current pointer, outbox intent, work, and audit records |
| [persistence/publication_store.py](../src/macro_agent/persistence/publication_store.py) | PostgreSQL brief lock, atomic publication, correction, retries, and local acknowledgement |
| [persistence/inspection.py](../src/macro_agent/persistence/inspection.py) | Fully materialized owner-scoped report from a read-only repeatable-read snapshot |
| [persistence/context_binding.py](../src/macro_agent/persistence/context_binding.py) | Committed approval/exposure admission, pending-context guards and atomic invalidation |
| [persistence/admin.py](../src/macro_agent/persistence/admin.py) | Read-only domain inspection, scoped to the current account |
| [web/models.py](../src/macro_agent/web/models.py) and [web/settings.py](../src/macro_agent/web/settings.py) | UUID Django accounts and explicit application settings |
| [theses/models.py](../src/macro_agent/theses/models.py) | Private thesis aggregates and immutable exact text, manual meaning, approvals, receipts, and audit |
| [theses/service.py](../src/macro_agent/theses/service.py) | Protected draft/proposal/approval commands, exact hashes, current disposition, and coherent history |
| [theses/admin.py](../src/macro_agent/theses/admin.py) | Read-only owner-scoped thesis inspection |
| [positions/service.py](../src/macro_agent/positions/service.py) and [positions/representation.py](../src/macro_agent/positions/representation.py) | Protected attachment/revision/closure, complete exposure book and consistent private history |
| [api/parsers.py](../src/macro_agent/api/parsers.py) and [api/serializers.py](../src/macro_agent/api/serializers.py) | Bounded strict JSON and explicit wire/schema definitions |
| [api/views.py](../src/macro_agent/api/views.py) and [web/session_views.py](../src/macro_agent/web/session_views.py) | Session-derived authority, CSRF-protected commands, and private thesis OpenAPI |
| [api/position_serializers.py](../src/macro_agent/api/position_serializers.py) and [api/position_views.py](../src/macro_agent/api/position_views.py) | Strict paper-position commands and generated schema |

Domain values remain independent Python contracts. The current HTTP contracts are the explicit DRF serializers/routes and generated [desk OpenAPI](../artifacts/desk-openapi.yaml), not every planned entity. The earlier [thesis-only schema](../artifacts/thesis-openapi.yaml) records the prior increment. The original disposable [spike](../tools/contract_spike.py) remains separate. Application modules do not import laboratory tools.

## Thesis approval evidence

The authenticated JSON journey saves an unapproved exact-text draft and a manual interpretation, then requires explicit approval of both displayed versions and hashes. A new proposal preserves the current approval. The application compares the aggregate revision under owner-then-thesis protection; immutable input reads and trusted clock sampling follow the locks. Command IDs are unique per owner across all three operations. Exact retries preserve the original receipt while returning current state, so an old approval cannot reactivate itself.

[The thesis migration](../src/macro_agent/theses/migrations/0001_initial.py) adds immutable history, scoped references, matched draft/interpretation pointers, and authority constraints. [Record tests](../src/macro_agent/theses/tests/test_records.py) exercise database guards, rollback, real lock waits, concurrent commands, coherent snapshot reads, and restricted administration. [API tests](../src/macro_agent/api/tests/test_thesis_api.py) exercise real Django sessions and CSRF, account isolation, exact Unicode/whitespace, rejected ambiguity/coercion, stale approval, retries, and generated schema contracts.

[API_DEVELOPMENT.md](API_DEVELOPMENT.md) explains routes, approval requests, and replay limits. The [readable thesis trace](../artifacts/thesis-audit.md), [complete synthetic records](../artifacts/thesis-audit.json), and [generated SQL](../artifacts/thesis-0001.sql) make this increment inspectable. The trace is sequential; separate-connection tests establish concurrency. The manual preview is labeled `user_supplied`; it does not establish compilation, factual challenge, or investment analysis.

Thesis history uses a read-only repeatable-read snapshot, caps each category at 100 records, and exposes truncation. `approved_at` and the preview's provisional `known_at` describe effective command/preparation time, not measured durable commit time. The synthetic admission described below separately observes committed user inputs and updates publication pins through ADR 015. The API explicitly reports `monitoring: not_configured`.

## Paper positions and committed context

[PAPER_POSITIONS.md](PAPER_POSITIONS.md) records the agreed declaration, routes, gaps and authority. Immutable versions preserve instrument, direction, optional quantity/unit and horizon; mapping remains user-declared and unverified. Closure is terminal and old retries return current disposition. SQL guards protect history, parent/version progression and scope. Owner-scoped history preserves accepted transition order when clocks tie. The internal limit is 200 lifetime position records per thesis, including closed records; history caps at 100 with visible truncation.

All bound publication operations protect owner, thesis and brief. Approval/exposure changes protect all affected brief rows in sorted order before sampling the trusted clock. They atomically mark context pending, clear current assessments, cancel pending notices and supersede obsolete pending reassessment work. Publication and local acknowledgement reject pending context; original decisions remain historical. A draft proposal preserves approved authority and its current brief.

Synthetic enrollment and refresh require an outermost transaction. They resolve already committed approved text, meaning, approval and the complete exposure book, verify hashes and persist full resolved inputs with four context pins. The twelve other governing roles remain fictional. First observations of immutable inputs remain pinned; original approved hashes/preparation times are preserved. `input_observed_at` witnesses committed input availability, while `admission_effective_at` does not measure exact admission commit time. Full operational activation replay remains unproven.

The [readable desk trace](../artifacts/paper-desk-audit.md), [complete records](../artifacts/paper-desk-audit.json), [position SQL](../artifacts/positions-0001.sql) and [binding SQL](../artifacts/postgresql-0003.sql) expose this increment. [Binding tests](../src/macro_agent/persistence/tests/test_binding.py) force both approval/publication and exposure/publication orderings, pending guards, admission rollback and owner scope. [Position tests](../src/macro_agent/positions/tests/test_records.py) verify closure/revision races, clock sampling after every protection, coherent read-only history and mutation guards. [API tests](../src/macro_agent/api/tests/test_positions_api.py) cover actual sessions/CSRF, strict declarations, authority, retries and generated contracts.

## Publication evidence

The [Django adapter](../src/macro_agent/persistence/publication_store.py) locks the brief row before reading any governing version. Bound briefs first protect owner and thesis and validate admitted context. Evidence changes use that same ordering and exact expected-version checks. Every transition atomically persists assessment history, publication state, notification intent, audit, and reassessment work. Separate owners can progress concurrently; the conservative owner lock serializes bound activity within an account. Trusted runtime clocks are sampled after the protected read.

Inputs come from [fictional recorded fixtures](../fixtures/pilot.json), translated by [domain_fixture.py](../tools/domain_fixture.py). Their source contract and every governing dependency are pinned; they establish mechanics, not permitted live source coverage.

[PostgreSQL migrations](../src/macro_agent/persistence/migrations/0001_initial.py) enforce immutable history, ownership, and foreign-key scope; [lifecycle guards](../src/macro_agent/persistence/migrations/0002_lifecycle_guards.py) protect stable mutable-record identities, terminal transitions, and monotonic brief progress. Equal timestamps cannot reactivate an old evidence version: previously activated versions are rejected; a correction restoring old content needs a fresh version.

The [PostgreSQL tests](../src/macro_agent/persistence/tests/test_postgresql.py) exercise separate connections, both correction orderings, atomic rollback, current retry disposition, scope enforcement, and direct forbidden database mutations. [DJANGO_DEVELOPMENT.md](DJANGO_DEVELOPMENT.md) contains setup and inspection commands. The [PostgreSQL audit](../artifacts/postgresql-audit.md) and [complete records](../artifacts/postgresql-audit.json) expose fictional input pins and transitions. Generated SQL is available for [0001](../artifacts/postgresql-0001.sql) and [0002](../artifacts/postgresql-0002.sql).

The [SQLite laboratory](../tools/lab_sqlite_store.py) implements the publication port for fictional inputs. It reserves the writer before reading state. Corrections follow the same protocol. Assessment/history, current pointer, brief version, notification intent, audit, and reassessment work commit or roll back together.

Analysis that loses a correction race remains historical, without a notification. Correction after publication clears the current pointer and cancels obsolete pending intents. A retry returns current disposition while preserving the original decision in history. A late run using identical inputs cannot replace a newer publication. Non-material updates preserve valid pending material notices.

[Separate-connection tests](../tests/test_publication_concurrency.py) force both correction orderings through a file-backed database. Publication-first pauses after the protected read and attempts a correction through another connection. Runtime publication samples its trusted clock inside the protected transaction; a timestamp captured before waiting may become obsolete.

The [readable report](../artifacts/publication-audit.md) and [complete records](../artifacts/publication-audit.json) show frozen inputs, observed versions, decisions, currentness, notices, and reassessment. Inspection is read-only and consistent. The report generator is sequential; concurrency evidence comes from the tests.

```sh
python3 -m unittest discover -s tests -v
python3 tools/domain_demo.py --output artifacts/publication-audit.json --report artifacts/publication-audit.md
```

## Boundaries and next work

- Django accounts, sessions, restricted admin, durable user approval and manual paper declarations exist. Both APIs derive identity from their authenticated session. Future worker and publication entry points must do the same through reviewed authority. Production entitlements, enrollment and trusted ingestion remain application work. Synthetic bootstrap and version registration are explicitly gated; bound user context cannot be overridden with fixture hashes.
- PostgreSQL stores publication payloads/pins, separate exact thesis text, manual interpretations, approvals, paper versions and resolved context admissions. Complete source content and canonical knowledge still need durable version records. Fictional source/macro inputs and conservative observation timing do not provide complete production replay.
- Heads are scoped to each brief. Shared correction fan-out across users/briefs, typed revision lineage, live receipt capture, and connector rights are not implemented. Known-at ordering and activation history do not validate source revision lineage. Before scaling head changes, replace audit-JSON history scans with reviewed typed activation/lineage records.
- Exact structured facts are checked against source fields. Source truth and natural-language entailment are separate. Portfolio effects remain unresolved; no model analysis or trade recommendation is generated.
- Accumulation weights are synthetic, not calibrated thresholds. Agent compilation and rough-thesis conversations, validated exposure mapping, morning briefs, counter-analysis, and the TypeScript UI remain required. Manual interpretation and paper declaration endpoints do not replace them.
- Local delivery acknowledgement does not establish worker leasing, external send/retry behavior, or recall. Real channels need separate tests and linked corrections after acceptance.
- There are zero model calls and spend. Internal BYOK, aggregate budgets, source health, and validated coverage remain required before a usable desk pilot.

Next add the thin web journey and a permitted continuous source slice, while preserving global macro context and useful thesis challenge. Worker/queue, frontend/client tooling, hosting, and providers remain open. Retain [ROADMAP.md](ROADMAP.md) gates.

## Verification, 2026-10-03

At this earlier increment, all 94 tests passed, including 12 file-backed publication tests. Controlled races used independent connections and writer-reservation checks. The trusted-clock test held a correction before commit, confirmed publication was waiting, then verified clock sampling after the protected read. The generated report had two reproducible scenarios and zero provider calls or spend. This established internal/local mechanics within the boundaries above.

## Verification, 2026-10-04

All 95 core/laboratory tests and 20 PostgreSQL integration tests pass. The added SQLite regression prevents equal-time restoration of old evidence; the previous audit remains reproducible. PostgreSQL race tests observe the actual guarded query waiting on its blocking backend before release. Concurrent inspection retains one coherent read-only snapshot while a correction commits. Tests also verify atomic rollback, retry state, foreign-owner denial, read-only admin, CSRF on a permitted admin route, and direct database mutation guards.

Migrations 0001 and 0002 applied to an isolated PostgreSQL 17 development database; migration-state comparison reports no changes. The sequential PostgreSQL audit matches subsequent read-only inspection and uses zero provider calls or spend. Django's ordinary system check passes. Its deployment check reports two unsilenced HSTS warnings for subdomain inclusion and browser preloading, which depend on the eventual hosting/domain setup. No production deployment or live desk coverage is claimed.

## Verification, 2026-10-05

All 160 distinct tests pass: 95 core/laboratory, 20 PostgreSQL publication, 22 PostgreSQL thesis record/service, and 23 PostgreSQL API tests. The first combined database run passed 63 tests; two additional approval-versus-proposal races then passed with the complete 22-test thesis suite. Each race observes the actual waiting PostgreSQL backend before releasing the winner. Both orderings reject the stale command without sampling its clock or adding history. Concurrent history inspection preserves its prior snapshot while a proposal and approval commit through another connection.

The new thesis migration applied to the isolated PostgreSQL 17 development database and fresh test databases. Django checks and migration-state comparison pass. Generated thesis-only OpenAPI validates without warnings, with portable digest patterns and strict input objects. The synthetic approval trace preserves exact text, rejects stale approval, reports the older retry as non-current, and matches later read-only inspection. Independent review recomputed all stored text, interpretation, and approval hashes. The increment makes zero model/provider calls and does not establish live monitoring, operational known-at replay, deployed security configuration, or external delivery.

## Paper-position verification, 2026-10-05

All 247 distinct tests pass: 111 independent core/laboratory tests and 136 PostgreSQL integration tests, comprising 20 publication, 23 context-binding, 22 thesis records, 25 position records and 46 API tests. Independent connections observe actual server lock waits before releasing winners, including an exposure writer waiting on the final bound brief before clock sampling. Equal-time position history follows immutable accepted order.

Docker Desktop became unresponsive during verification. An isolated PostgreSQL 17.11 instance now runs with no TCP listener and a private project-local Unix socket; existing Docker data was preserved. [DJANGO_DEVELOPMENT.md](DJANGO_DEVELOPMENT.md) documents the fallback. This local evidence does not establish deployed security, continuous coverage, exact admission commit time or external delivery.

Migrations applied successfully and migration-state comparison reports no changes. Django checks, dependency compatibility and generated desk OpenAPI validation pass without schema warnings. Local settings reject a remote host, arbitrary socket path and non-private socket mode. Read-only inspection matches all final desk records; exact text, interpretation, approval, exposure-book and position hashes were independently recomputed. Markdown links/fences/punctuation and whitespace checks pass. The sequential demonstration uses zero model/provider calls or spend; it does not substitute for the separate-connection race tests.

## User-input CLI verification, 2026-10-05

All 276 distinct tests pass: 125 core/laboratory/client tests and 151 PostgreSQL integration tests. The 14 CLI tests include actual loopback HTTP cookies and CSRF rotation, blocked credential redirects, exact UTF-8/CRLF file input, explicit approval/decline, conflict behavior, optional sizing, session cleanup and private traces. The 15 recorded-news API tests cover authenticated CSRF writes, production/flag/database gates, owner isolation, strict input, same-context deduplication, closed exposure history and governing changes between committed admission and publication. Loopback transport tests require local socket access.

A separate actual terminal walkthrough passed through a real Django HTTP server and PostgreSQL: exact Unicode/CRLF thesis, explicit approval, paper attachment and a current fictional notice. The private trace retained exact text and quantity, no password was echoed, and no provider calls occurred. The temporary test account was disabled afterward; immutable history was preserved. Django checks, migration-state comparison and updated desk OpenAPI validation pass.

[Recorded-news service](../src/macro_agent/lab/recorded_news.py) permits only the fixed fixture under explicit local settings, the synthetic gate and a development/test database name. It derives the actor from the session, resolves real approved context, protects publication and materializes currentness before releasing the locks. Identical context returns its current notice without another interruption. The shared pure [fixture builder](../src/macro_agent/lab/fixtures.py) retains existing fixture behavior; tools keep a compatibility entry point. No application service imports laboratory tools.

All twelve non-user-context roles remain fictional, including the source manifest and coverage. Screening is prescribed by the fixture, personalized relevance and portfolio impact are unresolved, and external delivery remains absent. This earlier checkpoint established a runnable user-input workflow, not continuous monitoring, agent thesis refinement or analytical usefulness. Fresh Docker provisioning is documented against the official image; the actual walkthrough was verified with the isolated native PostgreSQL instance.

## Text-grounded compilation verification, 2026-10-06

All 356 distinct tests pass: 181 core/laboratory/client/provider tests and 175 PostgreSQL integration tests. The new cases verify exact Unicode/CRLF text, strict model documents and attribution quotations, explicit missing intent, provider price units, credential isolation, catalogue selection and model switching. Truncated or malformed HTTP compilation responses remain unknown outcomes without automatic retries or leaked response bodies. Session/CSRF and owner scope apply to compilation as well as approval. Django checks, migration-state comparison and generated desk OpenAPI validation pass without warnings.

Independent PostgreSQL connections change the draft or approval during inference; stale results remain historical without replacing the current draft. Competing owners cannot overrun the shared admission limit. Crash-after-admission and historical retry cases issue no additional model call. Database guards enforce immutable attempts/results and interpretation provenance. Inference occurs outside database locks, and a compiled proposal never changes the current approval implicitly.

An actual terminal walkthrough passed through a real Django HTTP server and PostgreSQL using two recorded model responses: exact thesis input, catalogue search, model switch, explicit approval, paper attachment, fictional notice and an owner-only trace. No real model key or live inference was used. Public NanoGPT and OpenRouter catalogues were fetched successfully through their adapters. Cheaper Inference's authenticated catalogue and response handling were fixture-tested; live access remains unverified. These checks establish workflow mechanics, not analytical usefulness.

Inspect the pure [compiler contract](../src/macro_agent/domain/compilation.py), [provider registry](../src/macro_agent/providers/__init__.py), [protected compilation service](../src/macro_agent/theses/compilation.py), [migration](../src/macro_agent/theses/migrations/0002_model_compilation.py), and [HTTP boundary](../src/macro_agent/api/compilation_views.py). Each attempt pins exact input, prompt/schema versions, provider, model, advertised prices and operating limits before the one permitted inference call. Reported charges, estimates and unknown costs remain distinct. Timeout does not prove cancellation, and admission/token limits do not guarantee a dollar cap.

[THESIS_COMPILATION.md](THESIS_COMPILATION.md) is the runnable setup and review guide. The compiler currently receives only thesis text. Fact verification, current macro context, source manifests, live monitoring, morning briefs and external delivery remain outstanding. Protected preparation time is not exact durable known-at time. Source-backed thesis compilation and the continuous desk gates in [ROADMAP.md](ROADMAP.md) remain unsatisfied.

## Compilation review and source planning, 2026-10-06

All 206 core/laboratory/client/provider tests pass, including 15 review-pack/baseline tests and ten one-thesis review-command tests. The preceding 175 PostgreSQL suite is unchanged in this increment. No database migration or API route changed. The new [review command](../tools/evaluate_compilation.py) uses the existing authenticated API and saves an owner-only incremental JSONL journal before transmitting the one permitted compilation request. Tests cover no-call cancellation, exact text, credential isolation, stale/unknown results without quality grades, changed draft text during inference, interrupted review, mismatched draft/document, escaped custom rubric controls, journal failure before transmission and refused file overwrite.

A real terminal/Django HTTP/PostgreSQL exercise passed with one recorded model response, exact Unicode/CRLF input, a literal baseline, five explicit uncertain ratings and private journaling. The resulting research thesis remained unapproved, no trade was attached and the temporary account was disabled afterward. No live inference or real model key was used. Human ratings assess model output; they neither grade the trader nor establish predictive skill, model superiority or a full compiler readiness gate.

[COMPILATION_REVIEW.md](COMPILATION_REVIEW.md) explains how to test one case or your own exact file. The eight [synthetic cases](../fixtures/compilation_cases.json) preserve qualitative concerns rather than factual answer keys. The pure [evaluation module](../src/macro_agent/domain/compilation_evaluation.py) separates literal label extraction from interpretation and operational disposition from manual review. No automated ranking, outcome learning or accepted numeric quality threshold was added.

[SOURCE_OPTIONS.md](SOURCE_OPTIONS.md) compares current primary provider documentation; no feed was purchased, contacted or accepted. [MONITORING_SLICE.md](MONITORING_SLICE.md) identifies the next source, durable receipt, correction-ordering, work/recovery and sourced-brief contracts. These are reviewable proposals. Live capture, a daemon, sourced macro context, personalized portfolio assessment, morning briefs and external delivery remain outstanding. Data budget, specific permitted source scope, latency targets and worker/durable-availability choices remain open.
