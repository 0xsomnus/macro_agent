# Instructions for coding agents

## Read before implementation

Read `README.md`, `PRODUCT_DOCTRINE.md`, `ROADMAP.md`, then the relevant domain and architecture documents and ADRs. Treat settled principles as invariants. Treat open decisions as questions for joint design, not defaults to hide in code. The user prefers focused Markdown handoffs, concise honest feedback, Socratic architectural discussion, and no em dash in generated documents.

## Working rules

1. Build the smallest vertical slice that proves timely monitoring and useful thesis challenge. Use interfaces and recorded fixtures before broad connector coverage.
2. Preserve exact approved `UserThesis` text. Keep compiled interpretation, factual conflicts, assessments, and system knowledge separate. Only explicit user approval changes the current thesis version.
3. Keep event capture and deterministic routing/urgency controls independent of LLM availability. Broad triage may use models, but uncertainty/failure cannot silently become non-material. Investigate credible severe surprises outside mapped drivers; novelty alone is insufficient. Search only for a named unresolved material question and log cost/trigger.
4. Model provenance, known-at time, source revision, licensing status, and replay from the start. Do not make claims of full coverage based on one API call.
5. Keep causal edges distinct from correlations. Version edges and regimes; route canonical changes through review even when thresholds fire.
6. Define bounded execution graphs with explicit node schemas, budgets, failure paths, and authority gates. Specialists are invoked on demand.
7. For valuation, choose method by business type and run arithmetic in deterministic code. Record every assumption and sensitivity. Decline unsupported methods rather than forcing a DCF.
8. Follow the accepted Django/PostgreSQL persistence foundation. Keep provider, LLM, queue, and deployment choices replaceable until reviewed. Do not assume OpenBB or a terminal subscription grants redistribution or model-processing rights.
9. Add meaningful tests for invariants and replay, not tests that merely mirror implementation. Compare reasoning with deterministic baseline in evaluation work.
10. Report confirmed facts, assumptions, coverage limits, and remaining decisions separately. Ask for architectural choices with concrete options and tradeoffs.
11. Approval covers exact text and a versioned concise interpretation. Material driver/horizon/signpost changes require user approval; agent hypotheses remain separate. Refine rough theses by exposing gaps and assumptions, not by manufacturing conviction.
12. Continuous news monitoring, morning briefs, counter-analysis, attached-trade relevance, and cumulative evidence are core. Preserve global context around the narrowed paper-pilot instruments. Scheduled-source fixtures alone cannot establish desk coverage.
13. Distinguish public availability, actual system receipt, and durable known-at time. Pin interpretation, exposure, source, macro-context, rule, and model dependencies. Save notification intent with assessment atomically; stale analysis cannot replace a newer current revision.
14. Defer the entire automated outcome-learning chain from the pilot, including provisional retrieval. Keep basic history/outcomes, current evidence updates, and named-human knowledge correction review. Internal configured BYOK is allowed; external BYOK, adaptive routing, and subscription allocation are deferred/open as documented.
15. Follow ADR 014: Python owns API/domain/research workers; TypeScript owns the web UI. Keep domain and publication rules independent of frameworks. Frontend/client tooling, queue, hosting, and model providers still require review; the disposable test harness is not a production architecture.
16. Follow ADR 015: audit small domain modules, force correction/publication orderings through independent connections, and expose read-only transition evidence. All governing-state writers share the publication ordering protocol. Sample the trusted clock after acquiring protection. Preserve original decisions separately from current disposition, including retries. Laboratory database behavior does not prove another adapter or external delivery.
17. Follow ADR 016: use Django with PostgreSQL, Django ORM/migrations, authentication, sessions, and restricted internal admin. Target Django 5.2 LTS and Python 3.13 with the psycopg driver. Keep immutable records read-only in admin and route workflow actions through explicit application services. Built-in auth does not establish private-row isolation.
18. Follow ADR 017, accepted through delegated judgment on 2026-10-05: use explicit DRF serializers and APIViews with drf-spectacular OpenAPI generated from their definitions. Reject duplicate JSON keys, unknown fields, and coercion; preserve exact text. Derive the actor from the session, enforce owner scope in every service, require CSRF on session writes, and bind approval to exact hashes with a protected current-version comparison. Historical retries cannot reactivate stale state. Approval time is not proof of exact durable known-at time; publication-pin/replay integration remains separate. Do not add Ninja or Pydantic as competing wire authorities.

## No-go changes without a new ADR and user review

Collapsing the three truth stores; automatic thesis edits; automatic canonical-edge promotion; general web search as the watcher; permanent multi-agent swarm; online model training; MVP Discovery; broker execution; production dependence on unreviewed data rights; or a dedicated graph DB selected without evidence.

## Definition of a handoff-ready increment

The increment identifies its source and domain contracts, updates relevant docs/ADRs, shows an end-to-end trace, verifies authority and replay invariants, reports costs and failure behavior, and lists any unresolved product or licensing question. Do not claim the full v1 universe is supported until coverage tests pass per pack.
