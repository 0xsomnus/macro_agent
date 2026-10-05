# ADR 014: Python API and research workers with a TypeScript web UI

Status: Accepted by user selection on 2026-10-02.

Update 2026-10-04: [ADR 016](016-django-postgresql-foundation.md) subsequently selects Django/PostgreSQL with Django ORM/migrations, authentication, sessions, and internal admin; runtime target is Django 5.2 LTS and Python 3.13 with the psycopg driver. The original language decision below remains intact. API and wire tooling were left open by that review.

Amendment 2026-10-05: [ADR 017](017-drf-and-openapi-boundary.md) records delegated selection of DRF serializers/APIViews and generated drf-spectacular OpenAPI. It settles the API and wire-schema authority while preserving independent domain rules. Frontend/client tooling, durable worker/queue, hosting, and providers remain open.

**Decision:** Use option B from [STACK_OPTIONS.md](../STACK_OPTIONS.md): Python for the API, domain/application logic, monitoring and research workers; TypeScript for the web UI. This selects the language arrangement, not a specific framework, Python version, database, queue, hosting platform, or model provider.

**Why:** The user is more comfortable maintaining and researching in Python. Keeping the backend in Python supports that workflow while retaining the thin web desk required to validate thesis refinement, continuous monitoring, and briefs. This choice is based on maintenance and research fit, not an asserted advantage in reasoning quality or performance.

**Boundary:** Python owns domain validation, authority checks, replay eligibility, assessment publication, and its atomic notification-intent transaction. The UI sends versioned requests and displays typed results; it cannot authorize thesis or interpretation changes on its own. API and workers share Python domain/application contracts. Background execution remains bounded and separate from HTTP requests where needed.

**Wire contracts:** Preserve the portable contract fixtures. DRF definitions and schema annotations now generate the authoritative OpenAPI under ADR 017; TypeScript client/validator tooling still requires review. Python annotations and TypeScript types alone do not validate external data. Domain rules stay independent of HTTP, provider SDKs, queue technology, and UI components.

**Operations:** Two language toolchains are accepted. The TypeScript UI does not require a second backend by default; rendering/build/deployment choices remain open. Give one Python publication boundary ownership of the assessment, brief, and outbox transaction rather than introduce a distributed transaction.

**Rejected for this increment:** TypeScript throughout, because it is less aligned with the user's stated maintenance preference; a TypeScript API plus separate Python research backend without a demonstrated need; treating the disposable SQLite contract laboratory as production persistence.

**Consequence:** The original next review compared concrete Python/API/schema, frontend, persistence, worker, and local development options. ADRs 016 and 017 now settle foundation and API/schema choices; frontend/client and worker options remain open. Existing internal keys continue through configured, replaceable model adapters. No adaptive routing or commercial credit system is a prerequisite. The reference spike remains test tooling until its behavior is explicitly ported into validated application modules.

**Reconsideration:** Revisit this arrangement only if measured operations or contract-maintenance costs outweigh the Python workflow benefit, or a new required capability provides specific contrary evidence. Continue testing the same authority, temporal, cost, and delivery invariants whichever libraries are selected.
