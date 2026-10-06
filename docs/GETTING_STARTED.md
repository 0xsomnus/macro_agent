# Getting started

This guide runs the local backend and a terminal walkthrough using your own thesis and paper trade with recorded example news. Live news monitoring and model analysis are not available yet. You do not need a model API key.

Commands below use macOS/Linux shell syntax and run from the repository root. Requirements are Python 3.13 and PostgreSQL 17, either installed locally or run through Docker. Native Windows instructions have not been verified.

## Install the project

```sh
git clone https://github.com/0xsomnus/macro_agent.git
cd macro_agent
python3.13 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
mkdir -p .local
cp -n .env.example .local/db.env
```

Skip cloning when you already have the checkout. Keep an existing environment file and database rather than overwriting or reinitializing them. If `python3.13` is missing, install Python 3.13 before creating the environment.

## Start PostgreSQL

Choose one database option. Use a separate development database named with a `_dev` suffix. The recorded-news walkthrough requires that suffix or a `test_` prefix and the explicit synthetic setup gate.

### Option A: a fresh Docker database

Start Docker first. In `.local/db.env`, set `MACRO_DB_PASSWORD` to a password for this local database. Keep these values for the example:

```dotenv
DJANGO_SETTINGS_MODULE=macro_agent.web.local_settings
MACRO_DB_NAME=macro_agent_dev
MACRO_DB_USER=macro_agent
MACRO_DB_HOST=127.0.0.1
MACRO_DB_PORT=5432
MACRO_DB_PASSWORD='replace-with-your-local-password'
MACRO_ALLOW_SYNTHETIC_SETUP=1
```

Load those values and start a new container:

The environment file is sourced by your shell. Keep passwords quoted so spaces, dollar signs and other shell characters remain literal. The quoted value must match the password used to create the database.

```sh
set -a
source .local/db.env
set +a
docker run --name macro-agent-local-db \
  -e POSTGRES_DB="$MACRO_DB_NAME" \
  -e POSTGRES_USER="$MACRO_DB_USER" \
  -e POSTGRES_PASSWORD="$MACRO_DB_PASSWORD" \
  -p "127.0.0.1:${MACRO_DB_PORT}:5432" \
  -v macro-agent-local-db-data:/var/lib/postgresql/data \
  -d postgres:17
docker exec macro-agent-local-db pg_isready \
  -U "$MACRO_DB_USER" -d "$MACRO_DB_NAME"
```

Wait until the final command says `accepting connections`, rerunning that readiness check if initialization is still in progress. The [official PostgreSQL image](https://hub.docker.com/_/postgres) creates the requested role and database on first initialization. The named volume preserves them between container restarts. Local bootstrap uses that role for migration and test privileges; deployment permissions require a separate setup.

If port 5432 is occupied, change `MACRO_DB_PORT` to an unused local port before loading the file and creating the container. If this container already exists, use `docker start macro-agent-local-db`. Changing environment values later does not change credentials in an existing database.

### Option B: an existing local PostgreSQL installation

Using a local PostgreSQL administrator account, create the development role and database once:

```sh
createuser --login --createdb --pwprompt macro_agent
createdb --owner=macro_agent macro_agent_dev
```

`createuser` prompts for the new role's password. Add your installation's administrator username/connection options if its defaults differ. For example, an installation whose administrator is `postgres` may need `-U postgres` on both commands. The `CREATEDB` privilege is for disposable test databases. Do not recreate an existing role or database.

Copy the resulting connection details into `.local/db.env`, using the local-settings and synthetic-gate values shown above. PostgreSQL must already be running. The application does not fall back to SQLite if it is missing.

## Create the tables and your account

```sh
set -a
source .local/db.env
set +a
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
.venv/bin/python manage.py createsuperuser
```

Choose your own username and password when prompted. `check` should report no issues. Load the environment in every new backend terminal. The project does not automatically read `.env` files. Django's default settings are for deployment; the explicit local settings select the development configuration.

## Try your own happy path

Start the backend in the configured terminal:

```sh
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

In a second terminal, from the repository root:

```sh
.venv/bin/python tools/desk_cli.py happy-path
```

The client uses the same authenticated API as a future web interface. Log in with the account you just created. Enter your thesis and manually describe its drivers, horizon and invalidation signposts. Review the exact text and interpretation before approving. Declining leaves an unapproved draft.

Then enter the paper position's instrument and direction. Quantity/unit and horizon are optional. Product/venue/currency mapping remains unverified in this prototype. The walkthrough triggers recorded fictional news and displays the resulting factual brief. It does not analyze whether your thesis is correct or infer portfolio consequences.

To use a thesis file without changing its text:

```sh
.venv/bin/python tools/desk_cli.py happy-path --thesis-file path/to/thesis.txt
```

The fixture's screening and relevance are predetermined. This flow tests user input, explicit approval, attachment and protected publication. It is not a test of live coverage, semantic relevance or analytical quality. Each new walkthrough creates new records for your account.

## Inspect your records

The backend is available at `http://127.0.0.1:8000`. Open `/admin/` and log in for read-only inspection. The admin is not a thesis editor or trading screen. Records are private to their owner, so your account cannot inspect the fixed demo's records. `/health/` identifies the service; it is not a monitoring-readiness check.

The [API guide](API_DEVELOPMENT.md) covers manual HTTP requests, and [paper positions](PAPER_POSITIONS.md) covers revision/closure and their effect on pending briefs.

## Run the fixed example

For a scripted demonstration of resizing, thesis amendment, closure and brief invalidation:

```sh
.venv/bin/python tools/paper_desk_demo.py \
  --output .local/paper-desk-demo.json \
  --report .local/paper-desk-demo.md
```

Open `.local/paper-desk-demo.md`. This fixed example runs once per database. Read its saved final state on subsequent runs:

```sh
.venv/bin/python tools/paper_desk_demo.py --inspect-only \
  --output .local/paper-desk-demo.json \
  --report .local/paper-desk-demo.md
```

Inspect-only does not recreate intermediate snapshots. The fixture account has an unusable password and cannot serve as your human login.

For a database-free mechanics example:

```sh
.venv/bin/python tools/domain_demo.py \
  --output .local/publication-example.json \
  --report .local/publication-example.md
```

This earlier example uses temporary SQLite storage solely to demonstrate correction ordering. It does not run the Django application or test a personal trading workflow.

## Use the existing development checkout

For model-assisted interpretation after basic setup, follow [thesis compilation](THESIS_COMPILATION.md). It adds provider setup and terminal catalogue selection while keeping factual verification and monitoring explicitly unavailable.

This computer already has an isolated PostgreSQL 17 cluster in `.local/pg-native`, with a private socket and `.local/native-db.env` configuration. Check it without initializing anything:

```sh
"$(brew --prefix postgresql@17)/bin/pg_ctl" -D .local/pg-native status
```

If it is stopped, start that existing cluster:

```sh
"$(brew --prefix postgresql@17)/bin/pg_ctl" -D .local/pg-native \
  -l .local/pg-native.log \
  -o "-h '' -k $(pwd)/.local/pg-socket -p 55433 -c timezone=UTC" -w start
```

Load its own configuration instead of `.local/db.env`:

```sh
set -a
source .local/native-db.env
set +a
.venv/bin/python manage.py check
```

Create your own account if needed, then start the backend and run the CLI as above. The fixed scripted example already exists here, so use `--inspect-only` for that separate demo. This cluster has no TCP listener and is separate from the earlier Docker database. See [Django development](DJANGO_DEVELOPMENT.md) for operational details.

## Common setup problems

| Symptom | Check |
| --- | --- |
| `Set MACRO_SECRET_KEY` | Load the local environment so `DJANGO_SETTINGS_MODULE` selects local settings |
| Connection refused | PostgreSQL is running, and host/port match the loaded environment |
| Password authentication failed | `.local/db.env` matches the credentials used when the database was created |
| Recorded-news route unavailable | Local settings, a development/test database and `MACRO_ALLOW_SYNTHETIC_SETUP=1` are selected |
| Demo records already exist | Use `--inspect-only` for the fixed scripted demo |
| Admin shows no demo records | Your account is separate from the private fixture account |

## Run tests

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python manage.py test macro_agent.persistence.tests \
  macro_agent.theses.tests macro_agent.positions.tests macro_agent.api.tests \
  --noinput --verbosity 2
```

The first suite needs no running PostgreSQL. The second creates and drops a separate test database and requires the development environment loaded. [Implementation](IMPLEMENTATION.md) records the verified counts and limits. Docker provisioning above is documented against the official image; the current checkout was verified with its native PostgreSQL instance.
