# ADR 016: Django and PostgreSQL foundation

Status: Accepted by user review on 2026-10-04, including Django ORM and migrations.

**Decision:** Build the Python backend on Django with PostgreSQL. Use Django ORM, migrations, authentication, sessions, and the internal admin as the application foundation. Target Django 5.2 LTS, Python 3.13, and the psycopg driver; pin supported patch versions in the implementation environment. The TypeScript web UI and independent Python domain modules remain as selected in [ADR 014](014-python-backend-and-typescript-ui.md).

**Why:** The owner prefers established frameworks, documented conventions, and less custom security and operations infrastructure. The complete desk needs accounts, schema evolution, internal inspection, and reviewer access alongside its API. Small auditable domain modules are possible with either Django or FastAPI; the thin HTTP layer alone did not justify the earlier FastAPI preference.

**Domain boundary:** ORM models persist records; explicit application services apply approval, temporal, entitlement, and publication rules. Keep reasoning outside transactions. All writers of governing state share the protected ordering protocol from [ADR 015](015-auditable-publication.md). Use migrations for schema changes and inspect their generated SQL. Do not make model signals or ordinary admin edits alternate paths around authority or immutable history.

**Security and inspection:** Adopt Django's authentication and session mechanisms rather than inventing equivalents. Restrict admin access and make immutable evidence, approvals, and publication history read-only. Workflow actions must use the same application authority checks as other entry points. Built-in authentication is not proof of private-row isolation, complete authorization, production session configuration, or live security. Verify these separately before external traders use the desk.

**Still open:** The API adapter, including Django REST Framework versus Django Ninja; authoritative wire-schema tooling and TypeScript client generation; frontend tooling; durable worker and queue implementation; hosting; data and model providers. Django selection does not select Pydantic, Ninja, or DRF. Durable capture and delivery must survive HTTP-process restarts regardless of API library.

**Rejected for this increment:** FastAPI as the application foundation, because its smaller HTTP surface does not offset the owner's preference for integrated accounts, migrations, and internal tooling. SQLite remains laboratory tooling rather than the chosen persistent service database. A dedicated graph database and a second TypeScript backend remain unnecessary without evidence.

**Consequence:** Port the persistence boundary into reviewed Django models, migrations, and PostgreSQL transactions while retaining the framework-independent domain contracts. Prove correction-first and publication-first behavior through independent PostgreSQL connections, atomic assessment/outbox writes, immutable history, retry identity, and readable transition evidence. Selection is not implementation completion or live-pilot approval; the laboratory's SQLite tests do not prove PostgreSQL behavior.

**References:** [Django 5.2 release and LTS notes](https://docs.djangoproject.com/en/5.2/releases/5.2/), [migrations and SQL inspection](https://docs.djangoproject.com/en/5.2/topics/migrations/), [object-permission limitations](https://docs.djangoproject.com/en/5.2/topics/auth/customizing/#handling-object-permissions), [admin scope](https://docs.djangoproject.com/en/5.2/ref/contrib/admin/), [PostgreSQL row locking](https://www.postgresql.org/docs/current/explicit-locking.html).
