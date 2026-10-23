# Testing roadmap and setup

Updated 2026-10-23. This is the practical route from the current terminal prototype to a supervised week of paper monitoring. It assumes the existing checkout on this computer. For another machine, complete [fresh installation](GETTING_STARTED.md) first and use its `.local/db.env` instead of `.local/native-db.env` below.

The aim is useful sourced research, then durable monitoring of an explicitly approved thesis. A successful command or recorded test is not proof of analytical quality or live coverage. The [product roadmap](ROADMAP.md) remains the broader scope reference.

## Testing sequence

| Stage | Current position | Evidence needed to move on |
| --- | --- | --- |
| 1. One reusable source setup | Agent-led source discovery, generic reader configuration and approval preferences are not implemented. | From a named question, find a suitable source, configure one supported reader, retain inspectable evidence and show failures. Enforce the selected approval policy before unattended setup. |
| 2. Reliable discovery and fallback | GDELT recovery and background work exist; successful live acquisition remains unverified. No alternative discovery provider is configured. | Use a permitted working source. Before enabling paid fallback, connect actual dispatch to the spending ledger and test failure, concurrency and restart behavior. |
| 3. One real research/refinement test | The terminal supports bounded headline research and sourced compilation; live usefulness remains unproven. | Produce ranked possible causes, counter-evidence, qualified exposure ideas and explicit gaps. Preserve exact input and distinguish evidence from hypotheses. No suitable trade is a valid result. |
| 4. Supervised weekly paper workflow | Continuous runner, retained context, daily digest and optional synthesis exist. Suitable live inputs and a reviewed real thesis remain prerequisites. | Observe cumulative updates, morning briefs, internal review notices, restart recovery and visible source failures over a week. |

Build the smallest source slice for stages 1 and 2. A complete autonomous connector platform is not a prerequisite for the first live research test. The existing fixed-source CLI can provide an earlier, narrower baseline when its source is available. A light testing interface can follow the proven flow; equity fundamentals and advanced charts remain deferred.

## Set up the existing checkout

Run commands from the repository root:

```sh
cd /Users/christiangoll/workspace/macro_agent
```

1. Check the existing database. Do not initialize another cluster:

```sh
"$(brew --prefix postgresql@17)/bin/pg_ctl" -D .local/pg-native status
```

If it is stopped, use the [existing-cluster start command](GETTING_STARTED.md#use-the-existing-development-checkout). If the virtual environment or database configuration is missing, follow that guide before continuing.

2. If you have not configured a model provider, run:

```sh
.venv/bin/python tools/desk_cli.py configure-models
```

Choose NanoGPT, OpenRouter or Cheaper Inference and enter the key at the hidden prompt. This saves `.local/models.env` and makes no provider request. If that file already exists, reuse it; setup refuses to overwrite it. See [provider switching](THESIS_COMPILATION.md#switch-providers) when changing providers. Keep keys out of question files, watch configurations and reports.

3. In the backend terminal, load the configuration and enable research:

```sh
set -a
source .local/native-db.env
source .local/models.env
set +a
export MACRO_ENABLE_MODEL_COMPILATION=1
export MACRO_ENABLE_MONITORING_PROOF=1
export MACRO_ENABLE_RESEARCH_DISCOVERY=1
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
```

Expected: migrations complete and the system check reports no issues. If you do not have an account, create one with `.venv/bin/python manage.py createsuperuser`. Use the same account for your private research and thesis records.

4. Before paying for research planning, check the current discovery source:

```sh
.venv/bin/python manage.py research_check_source --query "Uganda shilling" --recovery-policy
```

This makes one real GDELT request, with no model call or database write. A timeout or rate limit is a failed source check, not a finding about Uganda. Stop before paid planning if the source is unavailable; stages 1 and 2 address this dependency. A parsed response proves acquisition only, and an empty result does not establish that there are no relevant developments.

5. Start the backend:

```sh
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

Leave it running. Restart it after changing environment flags. The terminal clients in the following sections run in a second terminal from the same repository root and log in through the local API. Research needs no synthetic setup flag or monitoring watch.

## Stages 1 and 2: source readiness

These are development checkpoints, not switches you can enable today. Prepare one named research question and the evidence it needs. For example, a USD/UGX investigation may need a dated exchange-rate observation, monetary-policy context and evidence for competing explanations. A headline search alone cannot supply all of those.

- [ ] Discover a candidate source and explain which question it can answer, its depth and freshness limits.
- [ ] Configure one supported reader and retain the exact source revision, receipt, attribution and permission basis. Test an unavailable or changed source as well as success.
- [ ] Implement the selected source-approval preference: review connections or approve within recorded limits. Research-only setup must not create a watch. See [source approval preferences](AGENT_RUNTIME.md#agent-led-source-setup-and-approval-preferences).
- [ ] Select and configure a usable discovery/fallback provider. Do not treat a working API key as proof of retention or model-processing rights.
- [ ] For paid search, reserve the reviewed maximum charge before dispatch against both caps: **USD 10 per shared UTC calendar month and USD 0.10 per investigation lifetime**. Keep unknown-charge reservations across restart. Model inference and subscriptions are separate costs.

The [spending ledger](RESEARCH_BACKGROUND.md#search-spending) already exists, but no paid transport is connected. There is no paid-provider setup command or generic source-approval setting to run yet. Do not manually bypass this boundary for a paid test. A suitable working free source can support an earlier test without paid fallback.

## Stage 3: run one rough-question test

After a successful source check, create a UTF-8 file at `.local/question.txt` using your editor. Include your observation, dates and benchmark if known; leave genuine unknowns explicit. One possible prompt is:

> Research the drivers of recent USD/UGX moves. Check the claimed move and dates where evidence permits, rank competing explanations and counter-evidence, and assess possible exposure routes, including no suitable trade. Keep unsupported explanations and unavailable price data explicit.

Use a current question for the first test. Today's GDELT adapter searches a thirty-day window and retrieves headlines/metadata, not article bodies or verified prices. It cannot reconstruct an arbitrary September observation without suitable historical evidence. Primary-source depth and price verification remain separate gaps.

Run in the client terminal:

```sh
.venv/bin/python tools/research_question.py --question-file .local/question.txt --wait
```

Log in, select a model from the provider catalogue and inspect the request before confirming. Planning and compilation can incur model charges even if acquisition later fails. Generated queries go to the discovery provider; the question and retained evidence go to the selected model provider. Save the printed research ID, command ID and private journal path.

Review the result against this checklist:

- [ ] Your exact observation and uncertainty remain intact; missing dates, horizons or conviction were not invented.
- [ ] Possible causes are assessed before trade implications, with supporting evidence, counter-evidence and unresolved attribution.
- [ ] Important claims open their retained evidence. Headline evidence is not presented as full-article verification, proof of causation or known market expectations.
- [ ] Exposure candidates explain their economic relationship and basis risk. Availability remains unverified until checked.
- [ ] Explanation validity, thesis progression and prospective entry attractiveness remain separate. No target, stop or R:R is invented.
- [ ] The result can reject the premise, lower conviction or find no suitable trade. No thesis approval, position or monitoring was created.

For sourced refinement of the same draft, obtain `research.thesis_id` from the private journal's saved `research_response` entry. The printed retained source packet includes its evidence-context `id`. Use those IDs explicitly:

```sh
.venv/bin/python tools/desk_cli.py compile --thesis-id THESIS_UUID \
  --evidence-context EVIDENCE_CONTEXT_UUID --driver-review
```

This initiates another model call, then offers questions, refinement and optional exact approval. Omitting `--evidence-context` does not automatically reuse the research sources. Follow [sourced compilation](SOURCED_RESEARCH.md#terminal-workflow) and [saved-answer continuation](THESIS_COMPILATION.md#save-recover-and-continue), retaining the packet on later calls. A stale packet needs a new current selection. A new happy-path session creates a different thesis. [Question research](QUESTION_RESEARCH.md) documents the graph and limits.

### Recover before trying again

Replace the UUID placeholders with the IDs printed by your run. Inspect saved work without another source or model call:

```sh
.venv/bin/python tools/research_question.py --show-run RESEARCH_UUID
.venv/bin/python tools/research_question.py --recover-command COMMAND_UUID
```

Choose either lookup as needed. To explicitly advance remaining eligible work:

```sh
.venv/bin/python tools/research_question.py --continue-run RESEARCH_UUID --wait
```

Continuation may incur a charge for an unadmitted model step and asks for confirmation. It never resends an admitted uncertain model call. The local wait defaults to five minutes; the source recovery deadline is thirty minutes and does not reset on restart. A new investigation is a new planning attempt, not recovery. Optional [background enrollment](RESEARCH_BACKGROUND.md) lets an already-planned investigation continue through a separate worker; it does not install a system service.

## Stage 4: supervise a week of monitoring

Begin after a useful research/refinement result, exact thesis approval and an explicit monitoring decision. Choose a thesis whose material drivers have suitable permitted inputs. Research may explore USD/UGX or other assets beyond validated pilot coverage; that does not establish their continuous coverage.

A working research search is not automatically a continuous feed. The current GDELT research adapter cannot be enrolled as a monitoring source.

1. Review the approved interpretation, source manifest, paper exposure if any, cadence, daily review time, context/work bounds and model allowances. Use `Africa/Kampala` if that is the desired briefing timezone; choose the actual time explicitly.
2. Follow [continuous runner setup](CONTINUOUS_RUNNER.md#configure-before-starting), including its additional gates, `--cumulative` preview and exact watch configuration. Keep capture and analysis in separate configured terminals. Watch creation is a separate operation from research or background enrollment.
3. Explicitly opt into [daily publication](DAILY_PUBLICATION.md), optional [fresh morning synthesis](MORNING_SYNTHESIS.md) and [driver review notices](DRIVER_ATTENTION.md) as required. An assembled digest alone does not prove that these are enabled. Review sourced starting context; record missing macro context rather than filling it from model memory.
4. Use the runner guide's bounded `--once` ticks before continuous operation. Inspect the saved watch and briefs:

```sh
.venv/bin/python manage.py desk_inspect --watch-id WATCH_UUID --owner OWNER_UUID --brief
```

Run inspection in a terminal with the database environment and runner gates loaded. The detailed watch JSON and worker commands live in the runner guide to avoid conflicting copies here.

During the week, check:

- [ ] A distinct development changes the cumulative driver assessment; duplicate reporting does not count as independent support.
- [ ] A material explanatory change can receive internal review even if direction remains supportive or no trade is attached. Review against actual received evidence, not an assumed price move.
- [ ] A morning brief includes retained developments and earlier labelled analyses, source gaps and unresolved work. Synthesis failure leaves the retained digest available.
- [ ] Stop and restart after capture. Retained work survives, and an admitted uncertain model call is not resent.
- [ ] A missed daily slot creates once and is labelled late. Source outages remain visible rather than becoming "nothing happened."
- [ ] A source correction or permission change invalidates dependent current output; a historical retry does not reactivate it.

Use [job inspection/recovery](JOB_RECOVERY.md) for blocked work. Internal notification intents are not delivered external alerts; external delivery remains unimplemented. The [weekly test contract](WEEKLY_WORKFLOW_TEST.md) defines the wider durability cases. Passing this exercise does not certify broad coverage or trading performance.

## Keep a short private test record

Save notes under ignored `.local/`, alongside the tool-generated private journals. For each test, record: question and purpose; run/thesis/watch IDs; provider/model; selected source revisions and coverage gaps; expected versus observed behavior; concrete unsupported or useful claims; latency; reported/estimated/unknown costs separately; and the next fix. Keep credentials out of notes.

End each stage with **pass**, **needs work** or **blocked**, supported by the saved evidence. Record source availability, workflow durability and analytical usefulness separately so a passing restart test cannot conceal a failed research result.
