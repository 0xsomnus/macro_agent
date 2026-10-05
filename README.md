# Macro Agent handoff pack

Status: approved product direction, paper-pilot contracts, and selected application foundation. Updated 2026-10-05: Python owns the API/research workers and TypeScript the web UI. Django with PostgreSQL, ORM, migrations, authentication, sessions, and internal admin is selected in [ADR 016](ADR/016-django-postgresql-foundation.md). [ADR 017](ADR/017-drf-and-openapi-boundary.md) records the delegated selection of explicit DRF serializers/APIViews and generated drf-spectacular OpenAPI. The independent Python core and publication-ordering evidence exist; each application increment and live readiness require their own evidence. Frontend/client tooling, queue, hosting, and providers remain open. Start here, then read `AGENTS.md` before changing the design.

## Purpose and reading order

| Read | Document | Question answered |
| --- | --- | --- |
| 1 | [PRODUCT_DOCTRINE.md](PRODUCT_DOCTRINE.md) | What behavior is non-negotiable? |
| 2 | [PRODUCT_SPEC.md](PRODUCT_SPEC.md) | What does the first user experience prove? |
| 3 | [DOMAIN_MODEL.md](DOMAIN_MODEL.md) and [EVENT_ONTOLOGY.md](EVENT_ONTOLOGY.md) | What state and events exist? |
| 4 | [THESIS_ENGINE.md](THESIS_ENGINE.md) | How are theses compiled, challenged, and amended? |
| 5 | [MONITORING_AND_SOURCES.md](MONITORING_AND_SOURCES.md) | What is watched, from where, and at what cost? |
| 6 | [ARCHITECTURE.md](ARCHITECTURE.md), [AGENT_RUNTIME.md](AGENT_RUNTIME.md), [EXECUTION_GRAPHS.md](EXECUTION_GRAPHS.md) | How does work move through the system? |
| 7 | [LEARNING_AND_EVALS.md](LEARNING_AND_EVALS.md) and [SAFETY_AND_REGULATORY_BOUNDARIES.md](SAFETY_AND_REGULATORY_BOUNDARIES.md) | How is quality measured and authority bounded? |
| 8 | [ROADMAP.md](ROADMAP.md) and [ADR/](ADR/) | What is next, deferred, and locked? |
| 9 | [AUDIT_RESOLUTION.md](AUDIT_RESOLUTION.md) and [DEVELOPMENT_START.md](DEVELOPMENT_START.md) | Which audit decisions were accepted, and what does the first increment prove? |
| 10 | [IMPLEMENTATION.md](IMPLEMENTATION.md), [DJANGO_DEVELOPMENT.md](DJANGO_DEVELOPMENT.md), and [API_DEVELOPMENT.md](API_DEVELOPMENT.md) | Which modules exist, how are they audited, and how is the authenticated approval slice run? |

## One sentence

Macro Agent is a continuous research and monitoring desk for solo and retail discretionary macro and fundamental traders: it connects news and accumulating developments to approved theses and attached trades, provides morning briefs, analysis and counter-analysis, and helps the trader refine or amend their reasoning while they retain judgment and execution.

The paper pilot supports ES, NQ, XAU, DXY-linked trades, EUR/USD, USD/JPY, and USD/CNH, subject to source and instrument validation. Global macro context remains in scope even where direct instrument support is absent. The actual venue and traded instrument must be identified for each exposure. Individual equities and supported valuation are future core capabilities. Automated outcome learning is deferred; the pilot retains history and basic outcomes.

## Decision status

- **Locked:** principles explicitly settled or selected through delegated judgment and recorded in ADRs, including the Python backend/TypeScript UI arrangement in [ADR 014](ADR/014-python-backend-and-typescript-ui.md), Django/PostgreSQL foundation in [ADR 016](ADR/016-django-postgresql-foundation.md), and DRF/generated OpenAPI boundary in [ADR 017](ADR/017-drf-and-openapi-boundary.md).
- **MVP target:** desired first usable behavior, subject to evidence gates in `ROADMAP.md`.
- **Open:** frontend and TypeScript client/validator tooling, durable worker/queue and hosting, source contracts and rights, numeric materiality/evaluation thresholds, exact instrument mapping, shared versus private macro interpretation in the pilot, shared subscription cost allocation, future top-100 recipe, retention, and jurisdiction-specific product perimeter. Coding agents must not silently turn these into permanent decisions.
- **Deferred from the pilot:** individual-equity support and automated valuation; statistical event studies; user-defined source packs; automated postmortems, candidate-learning retrieval and relationship-promotion workflows; customer BYOK and adaptive model routing; Discovery; dedicated graph database; public community marketplace; congressional-trading monitoring. Internal BYOK through configured adapters is available for development and research.

## Start development

Use [IMPLEMENTATION.md](IMPLEMENTATION.md) for verified module and integration status, [DJANGO_DEVELOPMENT.md](DJANGO_DEVELOPMENT.md) to run the selected foundation, and [API_DEVELOPMENT.md](API_DEVELOPMENT.md) for session/CSRF setup and exact draft approval. Inspect the [thesis trace](artifacts/thesis-audit.md), [generated thesis OpenAPI](artifacts/thesis-openapi.yaml), and read-only [PostgreSQL publication report](artifacts/postgresql-audit.md). The earlier [SQLite report](artifacts/publication-audit.md) remains laboratory evidence. [DEVELOPMENT_START.md](DEVELOPMENT_START.md) records the reference spike and next application slice. [STACK_OPTIONS.md](STACK_OPTIONS.md) preserves the comparisons and selected foundation. Synthetic fixtures test mechanics, not live news coverage or trading foresight. Passing them does not approve a live or external pilot. A usable pilot must include continuous permitted news monitoring as well as scheduled sources.

These documents are implementation guidance, not a claim that all feeds, asset packs, or legal permissions have been verified. Source endpoints are examples to validate during integration. Current official examples are linked in `MONITORING_AND_SOURCES.md`.
