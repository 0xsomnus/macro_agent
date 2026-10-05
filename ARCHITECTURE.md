# Architecture

Updated 2026-10-05. [ADR 014](ADR/014-python-backend-and-typescript-ui.md) selects Python API/domain/research workers and a TypeScript web UI. [ADR 015](ADR/015-auditable-publication.md) requires small auditable modules, forced concurrency cases, and read-only transition evidence. [ADR 016](ADR/016-django-postgresql-foundation.md) selects Django with PostgreSQL, Django ORM/migrations, authentication, sessions, and internal admin. [ADR 017](ADR/017-drf-and-openapi-boundary.md) selects explicit DRF serializers/APIViews and generated drf-spectacular OpenAPI through delegated judgment. Frontend/client tooling, durable workers/queue, hosting, and providers remain open.

The Python backend owns authority, input validation, temporal eligibility, and atomic publication. API and workers share domain/application contracts; the UI uses versioned wire contracts. Keep those rules independent of transport, SDKs, and queue libraries. The UI does not require a TypeScript backend by default.

## Logical components, stack-neutral

```text
Official sources / permitted continuous news / market data
      -> provider adapters -> immutable lawful receipts + provenance
      -> normalization, identity resolution, dedupe, revision tracking
      -> event store + deterministic capture and source-health watchers
      -> conservative candidate routing + broad relevance screening
      -> thesis-impact / open-trade-impact / accumulated-driver assessment
      -> bounded context, analysis, counter-analysis, selective research
      -> evidence validation -> assessment + durable notification intent
      -> evolving brief / morning brief / delivery worker
                              |
                    decision/outcome records + evaluation
```

The product is a continuous research and monitoring desk. Capture, scheduling, source health, conservative routing, and delivery continue without an LLM. Model screening can recognise unfamiliar transmission paths; unknown relevance, model failure, and exhausted budgets never become a negative materiality decision. Credible potential urgency can produce a narrower notice with unresolved portfolio impact while investigation continues.

Persist source receipts, normalized events, approved thesis versions and interpretations, assessments, brief versions, graph edges, model runs, and audit transitions separately in PostgreSQL through Django ORM and migrations. Ordinary relational tables with indexed relationships are adequate initially. A dedicated graph database is deferred; queue and worker technologies are open.

## Selected application foundation

Target Django 5.2 LTS and Python 3.13 with the psycopg driver. ORM models and migrations own persistence; explicit application services call the independent domain rules and coordinate transactions. Keep API and internal-admin actions behind those same authority gates. Inspect migration SQL and prove protected publication on PostgreSQL; SQLite laboratory evidence is not interchangeable with PostgreSQL evidence.

Use Django authentication, sessions, and restricted internal admin for their established application mechanisms. Private-row access, immutable records, entitlement checks, and secure deployed configuration remain explicit responsibilities. Evidence, approvals, and publication history are read-only in admin; workflow actions cannot bypass application rules.

The DRF boundary uses strict JSON parsing and explicit request/response serializers, with schema annotations for drf-spectacular generation. It preserves text exactly, rejects coercion and unknown/duplicate fields, derives identity from the session, and scopes reads and writes in application services. Session writes require CSRF. The first [OpenAPI artifact](artifacts/thesis-openapi.yaml) covers thesis endpoints; ordinary Django session endpoints are documented separately in [API_DEVELOPMENT.md](API_DEVELOPMENT.md). Runtime and database tests prove authority and concurrency rules.

The first authenticated slice persists immutable user-provided drafts and manual interpretations, then approves both hashes and exact latest draft versions with a protected expected-aggregate-revision comparison. Saved approvals remain separate from current state; retries cannot reactivate an older version. Private history uses a coherent read-only snapshot, caps each category at 100 records, and exposes truncation. Complete history pagination must precede external use. This slice does not compile theses, attach exposures, or participate in publication governing pins. Its protected `approved_at` is an acceptance/effective timestamp, not proof of exact durable availability at commit. The manual interpretation's provisional `known_at` likewise records preparation time. Establish durable availability and integrate the ADR 015 ordering protocol before operational replay or publication uses this state.

## Shared and private boundaries

- Share permitted evidence acquisition, normalization, dedupe, and source-health work. Distinct articles about the same underlying event are not independent evidence.
- Reuse event analysis when measured duplication warrants it and rights permit reuse. Private theses, positions, investigations, and user-specific evidence must not enter shared artifacts or cache keys accessible to other users.
- A future shared macro context contains versioned observations, hypotheses, competing explanations, and unresolved questions. A private analyst can disagree; shared model interpretation is not canonical truth.
- Shared versus independent model-generated context construction remains an explicit pilot experiment. Do not make a global analytical pipeline or one pipeline per trader an architectural prerequisite.
- Internal BYOK uses configured credentials and provider/model selection per role. External pilots use operated credentials; customer-facing BYOK, adaptive routing, and subscription-credit billing are deferred. Preserve a replaceable provider boundary; see [ADR 013](ADR/013-internal-byok-and-cost-boundaries.md).

## Contracts

| Boundary | Required record or behavior |
| --- | --- |
| Provider adapter | `SourceContractVersion`, native ID/revision, timestamps, payload hash, lawful retention, polling/feed method, latency and failure expectations, rate limits, and entitlement scope. A capability depends on validated input feasibility. |
| Normalized event | Stable underlying-event identity, independent source provenance, entities/assets, family/subtype, occurrence and availability times, facts/units, quality, revision, and correction lineage. |
| Candidate routing | Versioned deterministic rules plus logged semantic screening. Independent thesis-impact and open-trade-impact routes; `DriverEvidenceWindow` accumulates independent developments and offsetting evidence. Novelty alone does not justify escalation. |
| Coverage | `CoverageContractVersion` identifies drivers, sources, freshness targets, exclusions, current health, supported exposures, and contextual monitoring. An instrument label does not promise exhaustive global monitoring. |
| Interpretation | Immutable `CompiledThesisVersion` and append-only `CompiledThesisActivation`. Initial interpretation and changes to drivers, horizon, or invalidation signposts require user approval. Equivalent source repairs are audited technical changes. |
| Assessment | `AssessmentContextSnapshot` and `ContextManifest` freeze all inputs. Store `ClaimEvidenceLink` to the supporting passage or data field, counter-evidence, assumptions, uncertainty, tools, costs, and output revision. |
| Brief and delivery | `IntelligenceBrief` holds append-only `BriefVersion` records for an event or accumulating development and affected thesis, including attached trades. `NotificationIntent` identifies the version and reason for interruption; further interruption needs a material change. |
| Review | Canonical relationship corrections require a named human reviewer during the pilot, with supporting evidence, rationale, scope, and predecessor version. Automated outcome-learning proposals are deferred. |

## Time and reproducibility

Distinguish `public_available_at`, when the specific source version became public if verifiable; `system_received_at`, when this system acquired it; and `known_at`, its earliest durable availability for system use. For source-derived records, `known_at >= system_received_at`. A normalized, derived, or approved record can become usable later. Do not substitute publication time for receipt or silently fabricate a public-availability timestamp.

Freeze the exact approved `UserThesisVersion`, `CompiledThesisVersion` and activation, exposure snapshot, source manifest, coverage contract, event revisions, retrieved source excerpts, knowledge/edge versions, macro-context version, rules, execution graph, prompt or prompt hash, model/provider configuration, and calculator versions used by an assessment. Retain lawful input content or identify reconstruction limits when rights prevent retention. Later corrections create new versions; they do not alter the prior assessment's context.

System replay at a cutoff uses records durably available and activated by that cutoff. Historical public-information studies can use verified original vintages under a separate declared protocol; they do not claim the desk actually received that information then. Deterministic replay tests mechanics. Historical LLM evaluation carries possible model hindsight; forward observation tests usefulness with genuinely contemporaneous inputs.

## Reliability and authority

Commit an assessment, its brief revision, and its notification intents in one transaction. A delivery worker leases pending intents, retries bounded failures, and records acknowledgement or a visible failed state. Use a stable idempotency identity across retries and channel-specific dedupe where supported. Do not promise exactly-once external delivery from a channel without that guarantee; ambiguous delivery remains visible.

Deduplicate capture by source-native ID and revision/content hash while preserving independent provenance. At publication, atomically check relevant input versions and active interpretation. An analysis that lost a revision race remains in history as superseded, cannot become the current assessment, and schedules reassessment against current evidence. If evidence is corrected after publication, mark the old brief superseded and publish the correction through the same history.

An early qualified notice and its later analysis share a brief identity. Concurrent work cannot overwrite newer conclusions. Source failures create coverage incidents and retry/dead-letter states. Budget or model failures create visible queued/degraded work, with a qualified urgent notice when evidence supports it; they never erase a captured event or establish irrelevance.

Version reads and current-state writes use the same protected transaction, and every governing-version writer participates in its ordering protocol. Sample the trusted publication clock after acquiring that protection. A publication generation additionally prevents an older run with identical inputs from replacing a newer output. Retries report current disposition without altering the immutable original decision. See [IMPLEMENTATION.md](IMPLEMENTATION.md) for the domain port and local adapter proof, including their limits.

Enforce authenticated access, scoped credentials, secret isolation, entitlement checks before every reuse/display/model call, audit logging, and retention controls. Workers cannot amend an approved thesis, approve their own interpretation changes, promote canonical edges, or execute trades.

## Build seams and acceptance

Define typed interfaces before choosing libraries: `Provider`, `Normalizer`, `EventRepository`, `ManifestCompiler`, `MaterialityGate`, `ContextBuilder`, `GraphRunner`, `AssessmentRepository`, `BriefRepository`, `NotificationOutbox`, `FeedbackRepository`, and `CostLedger`. A later `ValuationCalculator` remains replaceable. Use recorded fixtures and a fake clock before expanding connector coverage.

- Identical receipts and deterministic rules reproduce normalized events and routing. A model change can alter interpretation, never event identity, source facts, or user text.
- A duplicate story does not strengthen accumulated evidence; distinct developments and counter-evidence can change the current driver assessment.
- Crash after assessment commit resumes pending delivery. Duplicate retries and concurrent source revisions preserve one coherent brief history without claiming unsupported delivery guarantees.
- An approved interpretation cannot silently change through recompilation; newly investigated drivers remain agent assessment until user approval.
- Rights or provider failures appear as coverage gaps. Cross-user and cross-entitlement reuse cannot disclose private or unauthorised content.
- Per-run and aggregate budgets account separately for shared acquisition, shared analysis, and private work. Routing optimisation and pooled subscription allocation remain open until measured.
