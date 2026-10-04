# Architectural decision records

These records explain settled choices and rejected alternatives. Updated 2026-10-04 after the Django/PostgreSQL foundation review. Status `Accepted` means the user established the direction; it does not mean implementation, coverage, or legal review is complete. Dated amendments preserve earlier rationale while specifying revised pilot boundaries. A coding agent may propose a superseding ADR, but must not silently change an accepted decision.

| ADR | Decision |
| --- | --- |
| [001](001-user-thesis-ownership.md) | Separate belief, assessment, and knowledge; approve meaning as well as exact text |
| [002](002-monitor-before-reasoning.md) | Deterministic capture before bounded screening/reasoning; uncertainty cannot become low |
| [003](003-typed-graphs-and-review.md) | Typed graph semantics, reviewed edge changes, deferred graph DB |
| [004](004-bounded-execution.md) | Explicit execution graphs and bounded on-demand workers |
| [005](005-monitor-first.md) | Continuous desk and narrow paper pilot with global context; Discovery deferred |
| [006](006-reusable-source-packs.md) | Reusable packs and provider-neutral data rights |
| [007](007-learning-without-online-training.md) | Basic records now; entire automated outcome-learning chain deferred |
| [008](008-event-studies-and-legislation.md) | Event studies and specialised lifecycle machinery staged after pilot |
| [009](009-fundamental-valuation.md) | Method-aware deterministic valuation with later equity expansion |
| [010](010-product-authority.md) | Continuous desk, rough-thesis refinement, evidence, and user authority |
| [011](011-materiality-and-continuous-desk.md) | Separate screening, investigation, and interruption; unknowns and cumulative evidence |
| [012](012-pilot-learning-and-evaluation.md) | Learning deferral; independent misses review and fresh forward evaluation |
| [013](013-internal-byok-and-cost-boundaries.md) | Internal BYOK now; configured routes, aggregate costs, commercial decisions later |
| [014](014-python-backend-and-typescript-ui.md) | Python API/domain/research workers with a TypeScript web UI |
| [015](015-auditable-publication.md) | Small domain modules, protected publication, forced correction races, and inspectable state transitions |
| [016](016-django-postgresql-foundation.md) | Django/PostgreSQL, ORM/migrations, and established account/admin foundation; API/wire tooling remains open |

The language arrangement is accepted in ADR 014 after [STACK_OPTIONS.md](../STACK_OPTIONS.md) review. ADR 016 selects Django/PostgreSQL and Django ORM/migrations with authentication, sessions, and internal admin. API adapter and wire-schema tooling, frontend tooling, durable worker/queue, hosting, and model providers remain unselected.
