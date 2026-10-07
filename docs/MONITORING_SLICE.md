# First continuous monitoring slice

Status: broader implementation plan, updated 2026-10-07. The trader chose to prove the monitoring pipeline before setting a news-data ceiling. The [local capture/restart harness](MONITORING_PIPELINE.md) now uses fictional fixtures and a narrow official Fed RSS snapshot after source review. It does not select a production feed, worker library, hosting or urgency thresholds. Live compilation testing remains one thesis at a time.

## Outcome and boundary

For one approved thesis and its attached paper trade, capture a permitted continuous news feed plus a relevant official complement, preserve revisions, and explain a development against the trader's view and exposure. A credible urgent case can produce a narrower qualified notice while impact remains unresolved. Later analysis and corrections update that same brief.

The instrument list limits supported exposure promises, not contextual geography. Keep relevant global developments and offsetting evidence in the context. Scheduled releases alone, headline forwarding and the existing fictional notice do not prove this outcome. Morning briefs and external delivery remain later parts of Phase 1, with their own readiness gates.

## Current reuse and missing pieces

| Reuse | Limit requiring work |
| --- | --- |
| [SourceTimes and revision selection](../src/macro_agent/domain/time.py) and [capture proof](MONITORING_PIPELINE.md) | Durable source receipts and conservative postcommit observations exist locally. Publisher revision ordering, canonical event admission, verified public availability and exact commit-time witnesses remain absent. |
| [Deterministic routing](../src/macro_agent/domain/routing.py) | Screening inputs are supplied observations, not an implemented classifier. Severity, credibility and urgency need evidence and versioned rules. Accumulation weights/windows are synthetic. |
| [Publication rules](../src/macro_agent/domain/publication.py) and [application service](../src/macro_agent/application/publication.py) | Candidate output supports exact structured source-field notices with unresolved portfolio impact. It does not yet express sourced narrative analysis, counter-cases or passage-level support. |
| [PostgreSQL publication store](../src/macro_agent/persistence/publication_store.py) and [source work](../src/macro_agent/monitoring/work.py) | Protected per-brief currentness, local intents and separate fenced capture-work leases exist. Observed source heads do not govern brief publication; global correction protection and external sends remain absent. |
| [Context binding](../src/macro_agent/persistence/context_binding.py) and [paper positions](PAPER_POSITIONS.md) | Approved text/interpretation and complete exposure are resolved. Initial non-user dependencies remain synthetic-gated; real contract/coverage admission needs an explicit service. Instrument mappings remain unverified. |
| [Provider boundary](../src/macro_agent/providers/__init__.py) and [compilation service](../src/macro_agent/theses/compilation.py) | Explicit models, bounded admission and uncertain-call handling can inform monitoring. The compiler schema is text-only and must not become the monitoring schema. |
| [Read-only brief inspection](../src/macro_agent/persistence/inspection.py) and [source inspection](../src/macro_agent/monitoring/inspection.py) | Local source health, pending-work counts and bounded receipt/attempt traces exist. Continuous gap detection, cursor/backfill completeness and private or entitled trader views remain unimplemented. |

The [recorded-news service](../src/macro_agent/lab/recorded_news.py) stays a fictional test path. Removing its gate would create source and publication authority without the required contracts.

## Minimal durable records

The capture proof implements a subset in ordinary Django/PostgreSQL records. The table describes the broader remaining contracts, including source-to-thesis admission; it is not a production migration design.

| Record | Required content |
| --- | --- |
| Source contract and manifest versions | Reviewed feed identity, event families, cadence/stream method, pagination/backfill and correction behavior, rate limits, timeliness, freshness, rights for storage/model processing/display/reuse, entitlement, retention, exclusions and fallback. Driver/exposure mapping remains explicit. |
| Capture attempt and source state | Requested interval/cursor, adapter version, transport outcome, byte/item limits, last check and successful receipt, outstanding backlog, next retry and gap reason. A quiet successful check differs from a failed check. |
| Receipt revision | Source-native ID/revision where present, exact lawful content or permitted reference/excerpt, hash, receipt time, source-claimed publication time, occurrence time if known, availability evidence, predecessor, rights version and processing disposition. Invalid normalization does not erase the receipt. |
| Event revision and evidence links | Stable underlying-event identity, source reports, typed observations versus attributed claims, entities, exact passages/fields, revision lineage and identity-resolution uncertainty. A model cannot edit source content. |
| Screening and work admission | Separate thesis-impact and open-trade-impact candidates; credibility, severity, urgency, transmission path or broad disruption, unresolved inputs, rule/model versions, reasons, budgets, lease/attempt identity and terminal outcome. |
| Context and coverage versions | Exact approved interpretation and complete exposure, selected evidence and competing macro hypotheses, counter-evidence, manifest, coverage, rights and rule/model dependencies. Coverage scope and current health are separate. |

Repeated retrieval of the same source revision is idempotent capture. A changed payload under the same native ID is preserved as a new or disputed revision according to the source contract. A second publisher's report remains separate provenance, even when linked to one underlying event. Corroboration is not another independent development. Uncertain cross-source identity remains explicit; neither aggressive merging nor headline counts may decide cumulative materiality.

Preserve four distinct clocks: publisher-claimed `published_at`, evidenced `public_available_at` or unknown, first actual `system_received_at`, and durable usable `known_at`. Also retain occurrence time and subsequent acquisition attempts. Restricted receipt is not public availability. A pre-commit clock is not proof of durability. The first persistence increment must choose and test a durable availability protocol; a conservative post-commit observation may prove availability by that time but cannot be labelled the exact earliest commit instant. Expose its precision and reconstruction limit. Backfills never enter an earlier operational replay merely because their publication date is old.

## Bounded execution

```text
reviewed source tick -> bounded fetch -> persist lawful receipts + cursor outcome
  -> normalize/revision/identity -> deterministic candidates + bounded broad screening
  -> shared evidence/global context -> private thesis route AND open-trade route
  -> qualified notice OR bounded analysis OR visible unresolved work
  -> evidence gate -> protected currentness -> atomic brief + notification intent
```

Capture and source health use no model. Commit a cursor only for the durably preserved span; page or byte exhaustion leaves a visible backlog. Schema drift and denied retention enter a visible incident rather than a successful empty feed. Source-native acknowledgement behavior needs its own recovery contract.

Screening is not interruption. Either thesis or trade relevance can justify investigation. Credible severe broad disruption or a plausible significant transmission path can enter outside mapped drivers; novelty alone cannot. Model failure, unknown exposure and budget exhaustion remain unresolved. Persist explicit rule inputs and reasons, including the evidence behind `credible`, `urgent` and severity. No live urgency rule or accumulation threshold is enabled by copying fixture defaults.

Start with sourced global observations and labelled competing hypotheses, then select the smallest relevant context for private analysis. Shared acquisition is settled; a shared model-generated regime assessment is not. Private thesis/trade data cannot enter shared output. Preserve counter-evidence and prior assessment changes. Without market/consensus rights and vintages, omit surprise/priced-in claims and unsupported reaction arithmetic.

A qualified notice states the supported development, the provisional thesis/trade connection, unresolved effect and next question. A model-free path can publish only where reviewed rules and retained evidence establish those narrower claims. Otherwise show pending investigation. A template cannot manufacture a portfolio connection or an urgent finding.

Before publication, protect governing state and compare all frozen dependencies. Reuse owner, thesis and sorted brief ordering, sampling trusted time after protection; perform network/model calls outside locks. Global source/event corrections need an additional proven protocol: authoritative head checks and all governing writers must participate, or affected briefs must become pending atomically before old work can publish. Asynchronous fan-out alone leaves a stale-publication window. Rights/coverage changes also invalidate affected work. Preserve original results separately from their current disposition and queue reassessment.

## Worker choices for review

| Option | Benefit | Work and limit |
| --- | --- | --- |
| Django management worker, durable PostgreSQL work/leases | Small internal footprint, explicit services and terminal inspection; one-pass mode supports debugging. | Implement and prove lease expiry/fencing, cursor recovery, backoff, fair work claiming, bounded attempts and shutdown. Process supervision remains a deployment choice. |
| Established task-queue worker with PostgreSQL as domain authority | Established scheduling and worker operations may reduce custom runtime work as concurrency grows. | Select and operate the library/backend; prove duplicate delivery, broker loss, durable dispatch and expiry behavior. A queue message cannot replace database currentness or paid-call admission. |

A one-pass command may be a useful test harness before either long-running choice. It is not a production daemon decision. In either option, capture retries follow source rules; model-call ambiguity follows durable admission and cannot silently issue another paid call. Restart recovers preserved pending work. Lease expiry permits a new worker to claim work but does not prove an old model request stopped; fence stale completion and keep unknown billing visible.

Keep capture/health capacity independent from analytical budgets. Record shared acquisition, shared analysis and private work separately, with rate, page, context, token, wall-time and aggregate limits. Missing reported charges remain unknown. A token cap is not a guaranteed dollar cap.

## Terminal proof and review gates

Proposed inspection surfaces, not existing commands: `source health`, `source receipts`, `monitor once`, `monitor work`, `monitor trace` and a private evolving brief view. Each exposes IDs/revisions, times and precision, supported facts and source context, route reasons, current versus historical disposition, leases/retries, cost uncertainty and coverage gaps. Historical evidence unavailable under current rights is labelled unavailable.

Before enabling live capture, resolve the permitted feed and official complement, storage/model/display rights, retention, adapter security, cursor/correction guarantees and source freshness targets. Review worker choice and the durable availability/correction ordering protocols before writing governing-state paths. Freeze explicit calibration criteria before forward evaluation; choose model and an internal test allowance without treating price as analytical quality.

Required mechanics include duplicate receipts, same-event reports, independent and offsetting developments, late backfill, source revision, unavailable models, exhausted budgets, malformed source data, crash after receipt commit, lease expiry and both correction/publication orderings through independent PostgreSQL connections. Approval/exposure changes must prevent stale notices. No model or worker may activate interpretation changes.

Then observe one thesis prospectively and independently sample feed flow for misses. Measure material recall and disputed labels, useful connections, noise, unsupported claims, capture-to-notice/analysis latency, source gaps and cost. Compare against a simpler brief using the same sources. Set numeric criteria before evaluation rather than deriving a passing threshold from results. Recorded fixtures prove mechanics only; one successful live event does not establish continuous coverage.

Governing references: [continuous sources](MONITORING_AND_SOURCES.md), [event ontology](EVENT_ONTOLOGY.md), [execution graphs](EXECUTION_GRAPHS.md), [ADR 011](ADR/011-materiality-and-continuous-desk.md), [ADR 013](ADR/013-internal-byok-and-cost-boundaries.md), [ADR 015](ADR/015-auditable-publication.md), [ADR 016](ADR/016-django-postgresql-foundation.md) and [roadmap](ROADMAP.md). This plan accepts none of the remaining choices.
