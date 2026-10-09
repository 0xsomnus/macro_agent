# Run and inspect the Django foundation

Updated 2026-10-05. Django and PostgreSQL are selected in [ADR 016](ADR/016-django-postgresql-foundation.md); [ADR 017](ADR/017-drf-and-openapi-boundary.md) selects DRF and generated OpenAPI. The foundation persists publication rules, exposes a restricted internal admin, and provides authenticated thesis approval and paper-position APIs. [API_DEVELOPMENT.md](API_DEVELOPMENT.md) and [PAPER_POSITIONS.md](PAPER_POSITIONS.md) document that journey and committed-context admission. The TypeScript UI, monitoring connectors, and delivery worker remain to be implemented.

## Start with the setup guide

[GETTING_STARTED.md](GETTING_STARTED.md) is the human setup and CLI walkthrough. It includes fresh database provisioning and the prepared-checkout shortcut. This document covers development verification and inspection. Run all commands from the repository root.

## Local setup reference

Use Python 3.13 and a separate development database. Dependencies are pinned with hashes in [requirements.lock](../requirements.lock); [requirements.in](../requirements.in) records the supported dependency ranges.

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
```

The earlier verification environment used an isolated PostgreSQL 17 container named `macro-agent-postgres-dev`, bound to loopback. Its throwaway credentials and assigned port are in ignored `.local/db.env`. Docker Desktop became unresponsive on 2026-10-05; its existing database was preserved. Current verification uses the isolated native fallback below. These details describe this development machine, not fresh-install prerequisites. When Docker is available, restart its existing container with:

```sh
docker start macro-agent-postgres-dev
docker port macro-agent-postgres-dev 5432/tcp
```

Docker may assign a different port after restarting. Set `MACRO_DB_PORT` in `.local/db.env` to the loopback port printed by the second command before loading that file.

For a fresh checkout, create a local PostgreSQL database and fill a copy of [.env.example](../.env.example) at `.local/db.env`. Never point these setup or test commands at an existing trader database. The Django test runner creates and drops the database named by `MACRO_TEST_DB_NAME` (default `test_macro_agent`); the synthetic setup gate requires an explicitly named development or test database. Load only the environment for the selected instance.

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

## Isolated native fallback on macOS

The current test runtime is PostgreSQL 17.11 from the official [Homebrew formula](https://formulae.brew.sh/formula/postgresql@17). No startup service is enabled. Its separate data cluster is `.local/pg-native`, with socket directory `.local/pg-socket` mode 0700, log `.local/pg-native.log` and environment `.local/native-db.env`. It has no TCP listener. Trust authentication is confined to this private local fixture socket; this is not a deployment authentication design. The project local settings reject arbitrary socket paths and non-private socket directory modes.

For this existing checkout, start or stop that isolated cluster explicitly:

```sh
/opt/homebrew/opt/postgresql@17/bin/pg_ctl -D .local/pg-native -l .local/pg-native.log \
  -o "-h '' -k $(pwd)/.local/pg-socket -p 55433 -c timezone=UTC" -w start
/opt/homebrew/opt/postgresql@17/bin/pg_ctl -D .local/pg-native -m fast -w stop
```

Run only the needed start or stop command; do not reinitialize an existing cluster. On a fresh macOS checkout, install `postgresql@17`, create `.local/pg-socket` with mode 0700, and initialize the separate cluster with `/opt/homebrew/opt/postgresql@17/bin/initdb -D .local/pg-native -U macro_agent --auth-local=trust --auth-host=scram-sha-256 --encoding=UTF8 --locale=C`. Start it as above and create `macro_agent_native_dev` through that socket. Fill ignored `.local/native-db.env` with local settings, that database/user, absolute socket path, port 55433 and an empty password. The fixture setup gate is optional and explicit.

For current verification, substitute `.local/native-db.env` for `.local/db.env` in the environment-loading example. Cluster state, sockets, credentials and logs remain ignored. Neither fallback nor container evidence proves production database permissions, source coverage or delivery.

## Verify the publication boundary

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python manage.py test macro_agent.persistence.tests macro_agent.theses.tests macro_agent.positions.tests macro_agent.api.tests --noinput --verbosity 2
.venv/bin/python manage.py makemigrations --check --dry-run
```

The first command runs 111 framework-independent and SQLite laboratory tests. The PostgreSQL suites cover separate-connection races and snapshot consistency, real lock-contention probes, atomic publication/approval/exposure rollback, committed-context admission, unchanged retry state, ownership, database mutation guards, Django session login, CSRF, strict JSON, and generated schema contracts. They refuse another database engine. The final verified count is recorded in [IMPLEMENTATION.md](IMPLEMENTATION.md).

Every publication and evidence-head writer locks its brief before reading governing versions. Bound briefs first protect owner and thesis. Approval and exposure changes lock every affected brief in sorted order before sampling time. Reasoning occurs outside these transactions. Separate owners can progress concurrently; bound activity within an owner is conservatively serialized. Both HTTP boundaries derive their actor from the session; future workers must bind their actor to a reviewed authenticated principal as well.

## Database wait limits

Every application connection sets a positive PostgreSQL lock timeout and statement timeout, defaulting to 5,000 ms and 15,000 ms. Override them with `MACRO_DB_LOCK_TIMEOUT_MS` and `MACRO_DB_STATEMENT_TIMEOUT_MS` before starting the process. Values must be integers from 1 to 300,000 ms, with the lock limit shorter than the statement limit. Connection establishment retains its separate five-second limit. These are internal operating limits, not the pilot's agreed news-latency targets.

Timeout aborts the affected database transaction; it does not undo a provider request. After durable model admission, a missing completion remains an unresolved attempt for inspection, without an automatic paid retry. New internal workers must handle database timeout/backoff visibly and preserve pending work. A per-statement limit does not bound an entire multi-statement application operation or queue scan.

## Read the records and database changes

```sh
.venv/bin/python tools/postgresql_demo.py --output artifacts/postgresql-audit.json --report artifacts/postgresql-audit.md
.venv/bin/python tools/postgresql_demo.py --inspect-only --output artifacts/postgresql-audit.json --report artifacts/postgresql-audit.md
```

The first command creates two fictional briefs under a synthetic account with an unusable password. It refuses existing demo records. The second regenerates the reports through read-only PostgreSQL snapshots. No provider calls, model reasoning, or external notifications occur. The report is a sequential trace; the tests establish the concurrency behavior.

Inspect [the readable audit](../artifacts/postgresql-audit.md), [complete records](../artifacts/postgresql-audit.json), and the generated migration SQL: [initial schema](../artifacts/postgresql-0001.sql), [lifecycle guards](../artifacts/postgresql-0002.sql). To regenerate SQL:

```sh
.venv/bin/python manage.py sqlmigrate macro_persistence 0001
.venv/bin/python manage.py sqlmigrate macro_persistence 0002
.venv/bin/python manage.py sqlmigrate macro_persistence 0003
.venv/bin/python manage.py sqlmigrate macro_positions 0001
```

Immutable history and scoped foreign keys are enforced by PostgreSQL constraints and triggers. Stable intent identities and terminal states are protected as well. These do not authenticate raw SQL callers or enforce the application lock protocol. Ordinary admin edits cannot bypass the application rules.

## Desk API and next integration

Use [the API runbook](API_DEVELOPMENT.md) and [paper-position contracts](PAPER_POSITIONS.md) to inspect exact drafts, approval, paper declarations, immutable receipts and private history. [The desk audit](../artifacts/paper-desk-audit.md) demonstrates real user-context admission into fictional event briefs and atomic invalidation. Manual interpretation is not an agent compiler; input observations and effective timestamps do not measure exact admission commit time. Next implement a thin trader journey and permitted continuous monitoring. Preserve the [implementation limits](IMPLEMENTATION.md) and [roadmap gates](ROADMAP.md). This foundation does not establish live desk coverage or external-pilot readiness.
