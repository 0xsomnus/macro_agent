# First development increment

Status: contract-and-fixture spike started 2026-10-02. User subsequently selected Python API/research workers with a TypeScript UI in [ADR 014](ADR/014-python-backend-and-typescript-ui.md), then Django/PostgreSQL with Django ORM and migrations in [ADR 016](ADR/016-django-postgresql-foundation.md) on 2026-10-04. [ADR 017](ADR/017-drf-and-openapi-boundary.md) records the delegated DRF/generated OpenAPI choice on 2026-10-05. Frontend/client tooling, durable worker/queue, hosting, and providers remain open. The original standard-library reference spike and SQLite adapter remain laboratory tooling.

Update 2026-10-03: [IMPLEMENTATION.md](IMPLEMENTATION.md) records the independent Python domain/application core, local separate-connection correction tests, and read-only audit report. These port selected contracts into small modules without choosing an HTTP framework or production database. [ADR 015](ADR/015-auditable-publication.md) records the approved auditability requirements.

Update 2026-10-04: target Django 5.2 LTS, Python 3.13, and PostgreSQL through the psycopg driver. Integrate ORM persistence and migrations while retaining the independent domain modules. Framework selection does not establish authenticated user isolation or PostgreSQL concurrency safety. See [IMPLEMENTATION.md](IMPLEMENTATION.md) for verified integration status rather than inferring it from this decision.

Update 2026-10-05: use explicit DRF serializers/APIViews and generated drf-spectacular OpenAPI. The immediate authenticated slice stores exact user drafts and manual interpretations, approves both hashes and latest draft versions with a protected expected-aggregate-revision comparison, and exposes private current/history inspection. [API_DEVELOPMENT.md](API_DEVELOPMENT.md) documents the session/CSRF journey and [thesis trace](artifacts/thesis-audit.md). Model compilation, paper exposure, source capture, and the TypeScript UI follow separately. Protected approval time does not prove exact durable known-at time; replay/publication-pin integration is not part of this slice.

Subsequent increment, 2026-10-05: [PAPER_POSITIONS.md](PAPER_POSITIONS.md) adds the confirmed instrument/direction/optional quantity-unit/horizon declaration and immutable attachment/revision/closure. Real committed approval/exposure records now enter synthetic publication pins. Their changes invalidate current briefs and pending notices atomically; pending context requires fresh admission. The [desk trace](artifacts/paper-desk-audit.md) and [current OpenAPI](artifacts/desk-openapi.yaml) are inspectable. Mapping remains unverified and source/macro inputs fictional. Conservative input observation does not measure exact admission commit time or establish full operational replay.

## Immediate proof

Exercise approved meaning, deterministic event capture, uncertain relevance, correction races, replay, and notification recovery using synthetic fixtures. [contracts/pilot.schema.json](contracts/pilot.schema.json) describes the portable fixture shape; [fixtures/pilot.json](fixtures/pilot.json) contains fictional inputs. [tools/contract_spike.py](tools/contract_spike.py) is a test-only reference model. [tests/test_contract_spike.py](tests/test_contract_spike.py) tests behavior rather than an LLM's prose.

Run from the workspace root:

```sh
python3 -m unittest discover -s tests -v
python3 tools/contract_spike.py --output artifacts/pilot-trace.json
```

The generated [trace](artifacts/pilot-trace.json) is a reproducible mechanics demonstration, not a forecast or live alert. It records no provider calls or spend. A production model can later change analysis but must not change source facts, approved text/meaning, or event identity.

## Acceptance and limits

- A system worker cannot approve prose or interpretation. Hashes bind approval to the displayed text/meaning. The reference spike does not establish authenticated identity; see [IMPLEMENTATION.md](IMPLEMENTATION.md) for evidence from the session boundary.
- First system receipt, durable availability, and public availability remain distinct. Historical system replay excludes publicly available inputs the desk had not received. Revisions remain available before and after correction cutoffs.
- Novelty alone cannot trigger investigation or notification; unresolved screening cannot become resolved non-material. Independent thesis and attached-trade impact routes exist in the reference decisions.
- Cumulative evidence counts distinct events, includes offsets, and applies a fixture-only window and threshold. These numbers have no product calibration or market validity.
- Assessment and notification intent commit or roll back together. A stale event or interpretation cannot replace the current assessment. The demonstration uses SQLite transactions only to test the contract, not to choose production storage.
- The original reference spike demonstrates these transitions sequentially; its version checks precede its write transaction. It does not prove correction-race safety. The new separate-connection tests prove the new local adapter's protocol; another adapter needs its own tests.
- Immutable output versions share a stable event/thesis brief identity. A declared material update supersedes an older pending interruption; a non-material update creates history without cancelling the undelivered material notice. The prototype accepts the fixture's material-change flag; it does not establish a real materiality classifier or a morning-brief UI.
- Stable notification identity permits retry and cooperative-channel deduplication. Tests cover a crash after send before acknowledgement; channels without idempotency can still duplicate external delivery. Production leasing, workers, and channel integration are not implemented.
- Structured fact checks validate cited data-field values. They do not prove natural-language entailment, source truth, or model reasoning quality. Those remain separate pilot checks.
- Schema references, local links, and fixture format are checked. The tooling does not implement a complete JSON Schema validator; full schema validation must be added in the selected stack.

## Next runnable web slice

Build the broader thin web journey incrementally: draft/refine thesis -> approve exact text plus interpretation -> attach a paper trade -> inspect watched drivers and coverage -> ingest scheduled and unexpected source fixtures -> receive an evolving event brief -> review evidence or approve a proposed amendment. ADR 017 settles the API/schema boundary. Its first slice uses manual interpretation and explicit approval; later steps need their own domain and integration evidence.

The ORM publication adapter and authenticated approval/paper boundaries now have independent PostgreSQL ordering, private-row and immutable-history tests. Continue with the thin trader journey, permitted continuous capture and useful thesis challenge. Keep durable monitoring and delivery independent of HTTP-process lifetime. Worker/queue and frontend tooling remain reviewed choices.

Introduce configured internal provider adapters with existing keys, budgets, trace metadata, and no customer-key UI. Begin real reasoning tests behind the existing evidence/authority contracts; add source adapters only after the input/use contract is validated.

Before a live paper pilot, continuous permitted news, official releases, relevant price context, concrete instrument mappings, source-health reporting, and the calibration/evaluation design must pass their gates. No claim of full universe coverage follows from this spike.

## Decisions still required

Frontend and TypeScript client/validator tooling; durable worker/queue implementation and hosting; actual pilot venues/instruments; source contracts and allowed data flows; numeric relevance/urgency/accumulation thresholds; retention; evaluation acceptance criteria; shared versus private macro-context execution. Adaptive routing, customer BYOK, credit billing, and shared subscription allocation are not prerequisites.

## Verification, 2026-10-02

The 26 behavioral/fixture tests pass, and the generated trace has 12 steps with zero provider calls or provider spend. Checks passed across 31 Markdown documents for local links, balanced fences, forbidden punctuation, whitespace, and conflict markers. JSON parses and internal schema references resolve; full JSON Schema validation is not claimed.

Independent review caught and repaired interpretation supersession and screening-bypass defects in the reference harness. Regression cases cover both. The workspace has no Git repository, so these changes are local files without a Git commit or diff baseline.
