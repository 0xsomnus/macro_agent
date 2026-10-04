# Python core and Django persistence increment

Updated 2026-10-04. Independent domain/application rules now have a Django/PostgreSQL adapter. [ADR 016](ADR/016-django-postgresql-foundation.md) records the approved framework, ORM, migrations, authentication, sessions, and internal admin. The trader API and live monitoring remain to be implemented.

## Inspectable modules

| Module | Responsibility |
| --- | --- |
| [models.py](src/macro_agent/domain/models.py) | Immutable exact thesis text, meaning, events, context snapshots, runtime validation, and hashes |
| [thesis.py](src/macro_agent/domain/thesis.py) | Owner approval binds exact text and interpretation; trusted actor and clock required |
| [time.py](src/macro_agent/domain/time.py) | Public availability, actual receipt, durable availability, UTC handling, and operational replay |
| [routing.py](src/macro_agent/domain/routing.py) | Investigation and notice eligibility, uncertain screening, severe surprises, and fixture accumulation with offsets |
| [publication.py](src/macro_agent/domain/publication.py) | Supported factual notice validation, dependency pins, currentness, and publication generation |
| [application/publication.py](src/macro_agent/application/publication.py) | Protected read, decision, atomic save, and idempotent retry |
| [ports.py](src/macro_agent/ports.py) | Persistence ordering contract independent of database libraries |
| [persistence/models.py](src/macro_agent/persistence/models.py) | Owner-scoped versions, heads, assessments, current pointer, outbox intent, work, and audit records |
| [persistence/publication_store.py](src/macro_agent/persistence/publication_store.py) | PostgreSQL brief lock, atomic publication, correction, retries, and local acknowledgement |
| [persistence/inspection.py](src/macro_agent/persistence/inspection.py) | Fully materialized owner-scoped report from a read-only repeatable-read snapshot |
| [persistence/admin.py](src/macro_agent/persistence/admin.py) | Read-only domain inspection, scoped to the current account |
| [web/models.py](src/macro_agent/web/models.py) and [web/settings.py](src/macro_agent/web/settings.py) | UUID Django accounts and explicit application settings |

These are internal Python contracts, not the selected HTTP schema or every planned domain entity. The original disposable [spike](tools/contract_spike.py) remains separate. Application modules do not import laboratory tools.

## Publication evidence

The [Django adapter](src/macro_agent/persistence/publication_store.py) locks the brief row before reading any governing version. Evidence changes use that same lock and exact expected-version checks. Every transition atomically persists assessment history, publication state, notification intent, audit, and reassessment work. Different briefs can progress concurrently. Trusted runtime clocks are sampled after the protected read.

Inputs come from [fictional recorded fixtures](fixtures/pilot.json), translated by [domain_fixture.py](tools/domain_fixture.py). Their source contract and every governing dependency are pinned; they establish mechanics, not permitted live source coverage.

[PostgreSQL migrations](src/macro_agent/persistence/migrations/0001_initial.py) enforce immutable history, ownership, and foreign-key scope; [lifecycle guards](src/macro_agent/persistence/migrations/0002_lifecycle_guards.py) protect stable mutable-record identities, terminal transitions, and monotonic brief progress. Equal timestamps cannot reactivate an old evidence version: previously activated versions are rejected; a correction restoring old content needs a fresh version.

The [PostgreSQL tests](src/macro_agent/persistence/tests/test_postgresql.py) exercise separate connections, both correction orderings, atomic rollback, current retry disposition, scope enforcement, and direct forbidden database mutations. [DJANGO_DEVELOPMENT.md](DJANGO_DEVELOPMENT.md) contains setup and inspection commands. The [PostgreSQL audit](artifacts/postgresql-audit.md) and [complete records](artifacts/postgresql-audit.json) expose fictional input pins and transitions. Generated SQL is available for [0001](artifacts/postgresql-0001.sql) and [0002](artifacts/postgresql-0002.sql).

The [SQLite laboratory](tools/lab_sqlite_store.py) implements the publication port for fictional inputs. It reserves the writer before reading state. Corrections follow the same protocol. Assessment/history, current pointer, brief version, notification intent, audit, and reassessment work commit or roll back together.

Analysis that loses a correction race remains historical, without a notification. Correction after publication clears the current pointer and cancels obsolete pending intents. A retry returns current disposition while preserving the original decision in history. A late run using identical inputs cannot replace a newer publication. Non-material updates preserve valid pending material notices.

[Separate-connection tests](tests/test_publication_concurrency.py) force both correction orderings through a file-backed database. Publication-first pauses after the protected read and attempts a correction through another connection. Runtime publication samples its trusted clock inside the protected transaction; a timestamp captured before waiting may become obsolete.

The [readable report](artifacts/publication-audit.md) and [complete records](artifacts/publication-audit.json) show frozen inputs, observed versions, decisions, currentness, notices, and reassessment. Inspection is read-only and consistent. The report generator is sequential; concurrency evidence comes from the tests.

```sh
python3 -m unittest discover -s tests -v
python3 tools/domain_demo.py --output artifacts/publication-audit.json --report artifacts/publication-audit.md
```

## Boundaries and next work

- Django accounts, sessions, and restricted admin exist. Future API and worker entry points must bind the store actor to their authenticated principal. Durable thesis approval, entitlement checks, and authorized production head creation remain application work. Synthetic bootstrap and version registration are explicitly gated; they are not approval or ingestion endpoints.
- PostgreSQL currently stores publication payloads and dependency pins. Complete source content, exact approved thesis text, interpretations, and canonical knowledge still need separate durable version records. Fixtures supply those inputs for this increment; hashes alone do not provide complete production replay.
- Heads are scoped to each brief. Shared correction fan-out across users/briefs, typed revision lineage, live receipt capture, and connector rights are not implemented. Known-at ordering and activation history do not validate source revision lineage. Before scaling head changes, replace audit-JSON history scans with reviewed typed activation/lineage records.
- Exact structured facts are checked against source fields. Source truth and natural-language entailment are separate. Portfolio effects remain unresolved; no model analysis or trade recommendation is generated.
- Accumulation weights are synthetic, not calibrated thresholds. Morning briefs, counter-analysis, rough-thesis conversations, and the TypeScript UI remain part of the next web slice.
- Local delivery acknowledgement does not establish worker leasing, external send/retry behavior, or recall. Real channels need separate tests and linked corrections after acceptance.
- There are zero model calls and spend. Internal BYOK, aggregate budgets, source health, and validated coverage remain required before a usable desk pilot.

Resolve the API adapter and wire-schema tooling, then connect this foundation to the thin web journey. Worker/queue, frontend tooling, hosting, and providers remain open. Retain [ROADMAP.md](ROADMAP.md) gates.

## Verification, 2026-10-03

At this earlier increment, all 94 tests passed, including 12 file-backed publication tests. Controlled races used independent connections and writer-reservation checks. The trusted-clock test held a correction before commit, confirmed publication was waiting, then verified clock sampling after the protected read. The generated report had two reproducible scenarios and zero provider calls or spend. This established internal/local mechanics within the boundaries above.

## Verification, 2026-10-04

All 95 core/laboratory tests and 20 PostgreSQL integration tests pass. The added SQLite regression prevents equal-time restoration of old evidence; the previous audit remains reproducible. PostgreSQL race tests observe the actual guarded query waiting on its blocking backend before release. Concurrent inspection retains one coherent read-only snapshot while a correction commits. Tests also verify atomic rollback, retry state, foreign-owner denial, read-only admin, CSRF on a permitted admin route, and direct database mutation guards.

Migrations 0001 and 0002 applied to an isolated PostgreSQL 17 development database; migration-state comparison reports no changes. The sequential PostgreSQL audit matches subsequent read-only inspection and uses zero provider calls or spend. Django's ordinary system check passes. Its deployment check reports two unsilenced HSTS warnings for subdomain inclusion and browser preloading, which depend on the eventual hosting/domain setup. No production deployment or live desk coverage is claimed.
