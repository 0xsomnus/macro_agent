# Macro Agent

Macro Agent is being built as a research desk for solo discretionary macro and fundamental traders. Its goal is to follow developments that affect your theses and open trades, explain their possible impact, provide morning briefs and counter-analysis, and help you improve your reasoning. You retain investment judgment and execution.

## Current status

This is an early backend prototype. The terminal walkthrough lets you enter your own thesis, review either a manual interpretation or a model proposal, approve both text and interpretation, attach a paper trade, and see a notice from recorded fictional news. Model compilation now presents a structured review card, including affected assets, causal paths, assumptions, catalysts, scenarios and explicit gaps. You can save exact answers to its questions and explicitly recompile. Thesis and position history is private and approval is explicit.

The compiler currently reads only your thesis text and saved answers. It does not verify facts, use current macro context or judge investment quality. A monitoring harness captures a narrow official feed, preserves source revisions and recovers pending work after restart. You can now initiate analysis of the next captured report against an approved thesis and its paper trades. The mechanics are tested with recorded model output; live usefulness remains unproven. An internal runner now connects separate capture and analysis processes, PostgreSQL scheduling and retained daily evidence reviews. Broad macro context, synthesized morning briefs, external alerts and the trader UI remain to be built. The manual walkthrough needs no model key.

The next internal test targets a week of durable paper workflow with a narrow live feed and headline-level analysis. [The test plan](docs/WEEKLY_WORKFLOW_TEST.md) distinguishes that goal from the broader desk roadmap and records the remaining compilation, context continuity, source and daily-brief work.

The first [research pack](research/ai-infrastructure/2026-10-09/README.md) examines AI infrastructure beneficiaries, copper CFDs and semiconductor stock perps. It separates sourced observations from candidate hypotheses and unknown entry valuation. Daily reviews now retain evidence, original analyses, exact approved inputs and predecessor context in PostgreSQL. They make no new model call and expose missing context explicitly.

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

## Try model compilation

Configure the provider and enter its key through a hidden prompt:

```sh
.venv/bin/python tools/desk_cli.py configure-models
```

Choose NanoGPT, OpenRouter or Cheaper Inference. The key is saved in ignored `.local/models.env` with owner-only permissions. In the backend terminal, stop the server, load that file alongside your database configuration, and restart:

```sh
set -a
source .local/models.env
set +a
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

In your second terminal:

```sh
.venv/bin/python tools/desk_cli.py happy-path --compile
```

The terminal fetches the configured provider's catalogue and lets you search and choose a model. Review its suggested interpretation, complete card, questions and counter-case. Type `refine` to save answers, `switch` to choose another model, or `approve` after review. Saving answers makes no model call; recompilation is separately initiated and may incur a charge. Unknown costs remain unknown. A private journal saves command IDs before requests for read-only recovery after interruption.

Read [thesis compilation](docs/THESIS_COMPILATION.md) for provider switching, failure behavior and current limits.

For a focused test without approval or paper entry, review one example or your own file against a simple baseline:

```sh
.venv/bin/python tools/evaluate_compilation.py --case es-universal-rate-cut
```

The [review guide](docs/COMPILATION_REVIEW.md) explains the test cases and private feedback journal. [Source options](docs/SOURCE_OPTIONS.md) compare broader feeds; no production feed has been selected.

## Prove monitoring capture and recovery

In the configured backend terminal:

```sh
export MACRO_ENABLE_MONITORING_PROOF=1
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py monitor_capture --fixture fixtures/monitoring_feed.json
.venv/bin/python manage.py monitor_inspect --source fixture-monitor
```

Capture leaves pending work in PostgreSQL. Exit the command or terminal, reload your database environment in a new terminal, set the monitoring flag again, then run:

```sh
.venv/bin/python manage.py monitor_work --limit 10
.venv/bin/python manage.py monitor_inspect --source fixture-monitor
```

The [monitoring walkthrough](docs/MONITORING_PIPELINE.md) covers changed payloads, lease recovery, source failures and a real Fed RSS capture. Processing currently records explicit unresolved relevance, with zero model calls. These local commands prove capture mechanics; they do not produce portfolio analysis or alerts. Fictional fixtures require the synthetic setup flag in your development configuration.

## Analyse captured news

Follow [the news analysis guide](docs/NEWS_ANALYSIS.md) to enable the internal endpoint, capture its fictional example and configure a model. With an approved thesis, run:

```sh
.venv/bin/python tools/review_news.py --thesis-id YOUR_THESIS_UUID --source fixture-divergence
```

You review the approved inputs and select a model. Typing `run` asks the backend to select the next report automatically, analyse it once and stop for your review. The response separates exact source quotations, thesis relevance, open-trade relevance and proposed consequences. The example tests news that supports a medium-term thesis while exposing a near-term trade risk.

This call may incur a provider charge. Analysis preserves your thesis and trades, leaves monitoring work unresolved, and creates no alert. The guide covers private journals, read-only recovery after a lost response, costs and current limits.

## Run the internal continuous desk

Follow [the runner guide](docs/CONTINUOUS_RUNNER.md) to preview an approved thesis, configure its source manifest, explicit timing and allowances, then start separate capture and analytical processes. This is an internal operator workflow. No unattended watch is enabled by default.

The runner creates each missed daily review once and labels late preparation. Restart recovers retained evidence and saved command outcomes; an uncertain model call is never automatically repeated. [Job inspection and recovery](docs/JOB_RECOVERY.md) explains blocked jobs and the explicit operator recovery command. Use `desk_inspect --owner OWNER_UUID --watch-id WATCH_UUID --brief` for a readable saved-state summary. Daily output is a private evidence review with gaps and costs, not yet a synthesized macro brief or alert. The AI research workflow still needs a reviewed thesis and matching permitted sources.

The latest [free-source research](research/source-options-2026-10-10.md) compares yfinance, GDELT metadata and official feeds. GDELT is a proposed adapter; live Yahoo automated-use permission remains unresolved. Neither is activated by this research.

## Inspect and develop

Open [the local admin](http://127.0.0.1:8000/admin/) for read-only inspection of your records. The admin does not provide the trading workflow. The [getting-started guide](docs/GETTING_STARTED.md) includes fixed examples, troubleshooting and tests. The [API guide](docs/API_DEVELOPMENT.md) documents the same underlying thesis and paper-position operations.

The stack is Python/Django, PostgreSQL and DRF; the planned web UI uses TypeScript. See the [documentation index](docs/README.md), [implementation status](docs/IMPLEMENTATION.md) and [roadmap](docs/ROADMAP.md). Contributors and coding agents should also read [AGENTS.md](AGENTS.md).

Design documentation lives in `docs/`, with decision records in `docs/ADR/`. Recorded inputs, source code, research and generated audit artifacts have separate folders.
