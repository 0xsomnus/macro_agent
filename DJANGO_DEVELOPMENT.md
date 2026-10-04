# Run and inspect the Django foundation

Updated 2026-10-04. Django and PostgreSQL are selected in [ADR 016](ADR/016-django-postgresql-foundation.md). This increment persists the existing publication rules and exposes a restricted internal admin. The trader journey, API library, monitoring connectors, and delivery worker remain to be implemented.

## Local setup

Use Python 3.13 and a separate development database. Dependencies are pinned with hashes in [requirements.lock](requirements.lock); [requirements.in](requirements.in) records the supported dependency ranges.

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
```

The verification environment uses an isolated PostgreSQL 17 container named `macro-agent-postgres-dev`, bound to loopback. Its throwaway credentials and assigned port are in ignored `.local/db.env`. To restart that existing container:

```sh
docker start macro-agent-postgres-dev
docker port macro-agent-postgres-dev 5432/tcp
```

Docker may assign a different port after restarting. Set `MACRO_DB_PORT` in `.local/db.env` to the loopback port printed by the second command before loading that file.

For a fresh checkout, create a local PostgreSQL database and fill a copy of [.env.example](.env.example) at `.local/db.env`. Never point these setup or test commands at an existing trader database. The Django test runner creates and drops `test_macro_agent`; the synthetic setup gate requires an explicitly named development or test database.

```sh
set -a
source .local/db.env
set +a
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

`/health/` identifies this as a foundation service. It does not check source freshness, coverage, database readiness, or monitoring health. `/admin/` uses Django authentication and sessions. Create an operator account with `manage.py createsuperuser` if needed. Domain records are read-only and scoped to their owner, including for superusers. A new operator will therefore see no other user's fixture briefs. Account management retains Django's built-in permission model.

Local settings deliberately permit HTTP on loopback. Deployment settings require an explicit secret key and enable secure cookies, HTTPS redirection, and security middleware. Hosting, database TLS and least-privilege roles, proxy trust, rate limiting, and production session configuration need review before external use.

## Verify the publication boundary

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python manage.py test macro_agent.persistence.tests --noinput --verbosity 2
.venv/bin/python manage.py makemigrations --check --dry-run
```

The first command runs 95 framework-independent and SQLite laboratory tests. The PostgreSQL suite covers separate-connection races, real lock-contention probes, rollback after an injected outbox failure, unchanged retry state, ownership, and database mutation guards. It refuses another database engine. The final verified count is recorded in [IMPLEMENTATION.md](IMPLEMENTATION.md).

Every publication and evidence-head writer locks its brief before reading governing versions. Reasoning occurs outside that transaction. Different briefs can progress concurrently. Built-in Django authentication does not establish application authority by itself: future HTTP and worker entry points must derive the adapter's actor from their authenticated principal.

## Read the records and database changes

```sh
.venv/bin/python tools/postgresql_demo.py --output artifacts/postgresql-audit.json --report artifacts/postgresql-audit.md
.venv/bin/python tools/postgresql_demo.py --inspect-only --output artifacts/postgresql-audit.json --report artifacts/postgresql-audit.md
```

The first command creates two fictional briefs under a synthetic account with an unusable password. It refuses existing demo records. The second regenerates the reports through read-only PostgreSQL snapshots. No provider calls, model reasoning, or external notifications occur. The report is a sequential trace; the tests establish the concurrency behavior.

Inspect [the readable audit](artifacts/postgresql-audit.md), [complete records](artifacts/postgresql-audit.json), and the generated migration SQL: [initial schema](artifacts/postgresql-0001.sql), [lifecycle guards](artifacts/postgresql-0002.sql). To regenerate SQL:

```sh
.venv/bin/python manage.py sqlmigrate macro_persistence 0001
.venv/bin/python manage.py sqlmigrate macro_persistence 0002
```

Immutable history and scoped foreign keys are enforced by PostgreSQL constraints and triggers. Stable intent identities and terminal states are protected as well. These do not authenticate raw SQL callers or enforce the application lock protocol. Ordinary admin edits cannot bypass the application rules.

## Next vertical slice

Choose the API adapter and wire-schema tooling, then connect Django authentication to durable approval of exact thesis text and interpretation, attached paper exposure, watched drivers, and evolving event briefs. Preserve the [implementation limits](IMPLEMENTATION.md) and [roadmap gates](ROADMAP.md). This foundation does not establish live desk coverage or external-pilot readiness.
