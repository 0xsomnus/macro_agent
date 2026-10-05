# Macro Agent

Macro Agent is being built as a research desk for solo discretionary macro and fundamental traders. Its goal is to follow developments that affect your theses and open trades, explain their possible impact, provide morning briefs and counter-analysis, and help you improve your reasoning. You retain investment judgment and execution.

## Current status

This is an early backend prototype. The terminal walkthrough lets you enter your own thesis, supply its interpretation manually, approve both, attach a paper trade, and see a brief generated from recorded fictional news. Thesis and position history is private and approval is explicit.

Live news monitoring, model analysis, morning briefs, external alerts and the trader UI are still to be built. The walkthrough tests the workflow and its safeguards; it does not judge the quality of your thesis or generate investment analysis. No model API key is needed.

## Set up locally

You need Python 3.13 and PostgreSQL 17. Docker is one option for PostgreSQL; an existing local installation also works. Start with a separate development database.

```sh
git clone https://github.com/0xsomnus/macro_agent.git
cd macro_agent
python3.13 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
mkdir -p .local
cp -n .env.example .local/db.env
```

Follow the [database setup steps](docs/GETTING_STARTED.md#start-postgresql) to start PostgreSQL and fill in `.local/db.env`. Then load the configuration and create the tables:

```sh
set -a
source .local/db.env
set +a
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
.venv/bin/python manage.py createsuperuser
```

Choose your own username and password when prompted. The environment file is not loaded automatically; load it in each new backend terminal. Local credentials and reports stay in the ignored `.local/` folder.

For the prepared checkout on this computer, load `.local/native-db.env` instead of creating another database. [The setup guide](docs/GETTING_STARTED.md#use-the-existing-development-checkout) explains how to check and start its database.

## Try your own happy path

Start the backend in the configured terminal:

```sh
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

In a second terminal, from the repository root:

```sh
.venv/bin/python tools/desk_cli.py happy-path
```

The walkthrough asks you to log in, enter a thesis and its drivers/horizon/signposts, review the exact approval preview, and attach a paper position. It then displays a brief from recorded example news. Quantity and its unit are optional, as is the position horizon. Missing instrument details remain visible.

To preserve text from a file exactly:

```sh
.venv/bin/python tools/desk_cli.py happy-path --thesis-file path/to/thesis.txt
```

The example news is fictional and its relevance is predetermined for testing. Portfolio consequences remain unresolved. This is the first CLI workflow milestone, not a live monitoring desk.

## Inspect and develop

Open [the local admin](http://127.0.0.1:8000/admin/) for read-only inspection of your records. The admin does not provide the trading workflow. The [getting-started guide](docs/GETTING_STARTED.md) includes fixed examples, troubleshooting and tests. The [API guide](docs/API_DEVELOPMENT.md) documents the same underlying thesis and paper-position operations.

The stack is Python/Django, PostgreSQL and DRF; the planned web UI uses TypeScript. See the [documentation index](docs/README.md), [implementation status](docs/IMPLEMENTATION.md) and [roadmap](docs/ROADMAP.md). Contributors and coding agents should also read [AGENTS.md](AGENTS.md).

Design documentation lives in `docs/`, with decision records in `docs/ADR/`. Recorded inputs, source code, research and generated audit artifacts have separate folders.
