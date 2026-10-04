# Pre-development audit resolution

Accepted in joint review through 2026-10-02. These are product decisions, not claims of completed implementation or validated data access. Updated ADRs preserve the original rationale; ADRs 011 to 013 record added boundaries.

After comparing language arrangements, the user selected Python API/research workers with a TypeScript web UI in [ADR 014](ADR/014-python-backend-and-typescript-ui.md). Concrete frameworks and persistence were still open at that stage.

Update 2026-10-04: [ADR 016](ADR/016-django-postgresql-foundation.md) selects Django/PostgreSQL with ORM, migrations, authentication, sessions, and restricted internal admin. API/wire tooling, frontend tooling, durable worker/queue, hosting, and providers remain open. Selection does not establish private-row isolation, PostgreSQL publication safety, or live-pilot readiness.

| Finding | Accepted resolution | Contract owners |
| --- | --- | --- |
| 1. Materiality | Broad screening; independent thesis/trade impacts; credible severe unknowns investigated without novelty-only alerts; urgent qualified notices; distinct accumulated evidence with offsets. | [Monitoring](MONITORING_AND_SOURCES.md), [graphs](EXECUTION_GRAPHS.md), [ADR 011](ADR/011-materiality-and-continuous-desk.md) |
| 2. Meaning and rough theses | Approve prose plus concise interpretation; version and review material interpretation changes; technical repairs audited; agent hypotheses separate. Distinguish factual error, unsupported mechanism, missing detail, and defensible disagreement. | [Thesis engine](THESIS_ENGINE.md), [domain](DOMAIN_MODEL.md), [ADR 001](ADR/001-user-thesis-ownership.md) |
| 3. Historical truth | Public availability and actual receipt distinct; exact input context pinned; deterministic replay and historical reasoning separated from forward usefulness. | [Architecture](ARCHITECTURE.md), [ontology](EVENT_ONTOLOGY.md), [evaluations](LEARNING_AND_EVALS.md) |
| 4. Reliability | Atomic assessment/notification intent; idempotent retry with visible failures; evolving briefs; source corrections supersede stale analysis. External delivery guarantees depend on channel capabilities. | [Architecture](ARCHITECTURE.md), [graphs](EXECUTION_GRAPHS.md), [ADR 004](ADR/004-bounded-execution.md) |
| 5. Initial scope | Paper pilot followed by first-trader observation; ES/NQ/XAU/DXY-linked trades plus EUR/USD, USD/JPY, USD/CNH; broad global context; equities/valuation, studies, user packs deferred. | [Specification](PRODUCT_SPEC.md), [roadmap](ROADMAP.md), [ADR 005](ADR/005-monitor-first.md) |
| 6. Input completeness | Validate source contracts; withhold surprise/priced-in claims without expectations; collect timestamped inputs prospectively and verify historical vintages. | [Sources](MONITORING_AND_SOURCES.md), [ontology](EVENT_ONTOLOGY.md) |
| 7. Evaluation | Independent missed-event review; simpler same-source baseline; calibration separate from later frozen evaluation; small pilot claims bounded. | [Evaluations](LEARNING_AND_EVALS.md), [ADR 012](ADR/012-pilot-learning-and-evaluation.md) |
| 8. Learning | Entire automated learning chain deferred, including provisional retrieval; retain basic records and human-reviewed corrections; later offline fresh-case experiment before rollout. | [Evaluations](LEARNING_AND_EVALS.md), [ADR 007](ADR/007-learning-without-online-training.md), [ADR 012](ADR/012-pilot-learning-and-evaluation.md) |
| 9. Cost and BYOK | Measure shared/private costs and aggregate budgets. Internal configured keys support tests now; external BYOK deferred; configured managed routes before adaptive optimisation. Shared/private context policy and subscription allocation remain open. | [Runtime](AGENT_RUNTIME.md), [ADR 013](ADR/013-internal-byok-and-cost-boundaries.md) |
| 10. Coverage and evidence | Dated per-thesis/exposure coverage contracts; source passage/field support checks; hypotheses/assumptions separate; credible event with unresolved consequences can receive narrower notice. | [Sources](MONITORING_AND_SOURCES.md), [doctrine](PRODUCT_DOCTRINE.md), [safety](SAFETY_AND_REGULATORY_BOUNDARIES.md) |

## Implementation status

The initial reference increment established portable contracts, synthetic source fixtures, and a test-only trace. Those demonstrate specified mechanics under controlled inputs. [IMPLEMENTATION.md](IMPLEMENTATION.md) records subsequent modules and verified integration status; [DEVELOPMENT_START.md](DEVELOPMENT_START.md) separates the remaining gates. Neither framework selection nor synthetic tests establish live feeds, entitlements, useful production reasoning, or a paper-pilot launch.
