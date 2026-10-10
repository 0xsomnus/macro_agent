# Internal continuous runner

Status, 2026-10-10: internal implementation verified with recorded inputs and PostgreSQL. [ADR 018](ADR/018-internal-runtime-and-daily-review.md) accepts separate Django capture and analytical processes with durable scheduling and leases. Missed daily reviews create once and label late. Production queue, supervision and deployment choices remain open.

## Configure before starting

Follow [local setup](GETTING_STARTED.md) and [model/news setup](NEWS_ANALYSIS.md), load the database and model environment files in each operator terminal, and run migrations. Use `macro_agent.web.local_settings`, a database ending in `_dev` or starting with `test_`, and these explicit gates:

```sh
export MACRO_ENABLE_MONITORING_PROOF=1
export MACRO_ENABLE_NEWS_ANALYSIS=1
export MACRO_ENABLE_CONTINUOUS_DESK=1
```

Model catalogue access also needs `MACRO_ENABLE_MODEL_COMPILATION=1`. Fictional sources require `MACRO_ALLOW_SYNTHETIC_SETUP=1`. Keep provider keys in the backend environment, never in the watch JSON. A watch requires explicit configuration; this guide supplies no default polling rate, briefing time or spending target.

| Configuration | Required review |
| --- | --- |
| Owner and thesis | Explicit UUIDs, active account, exact approved thesis/interpretation and complete attached paper exposure. Starting research is not approval to monitor an inferred thesis. |
| Sources | Reviewed source IDs, permitted processing/retention/display, payload scope, coverage gaps and source failure behavior. A narrow feed must fit the thesis. |
| Model | Configured provider and explicit catalogue model, with private inputs and possible charges understood. No adaptive routing or automatic model fallback. |
| Timing | Capture and analytical cadence, daily time/timezone, reporting cutoffs and explicit lease/recovery limits. |
| Bounds and allowances | Work and catch-up limits, complete exposure/evidence limits, encoded context bounds and shared model admission allowance. Overflow cannot silently discard inputs. Call/token limits do not guarantee a dollar ceiling. |
| Ambiguous outcomes | Review unresolved dispatches and admitted calls without conclusive results. Neither authorizes an automatic paid retry. |

The first research question concerns AI buildout, affected assets and whether positioning over a few weeks to months is late. Candidate copper CFD and equity perpetual exposures still require research and mapping. No approved thesis or source manifest follows merely from choosing that question.

## Command and configuration interfaces

An active owner, approved thesis and already retained source contracts are prerequisites. [Capture setup](MONITORING_PIPELINE.md) describes official and fictional sources. Preview committed inputs without a catalogue or model request:

```sh
.venv/bin/python manage.py desk_watch --owner OWNER_UUID --thesis-id THESIS_UUID --preview
```

Save a JSON object in ignored `.local/watch.json`. It must contain exactly these fields; copy the approval, complete exposure digest, selected source digests and complete model configuration from the preview. Model selection is an explicit supported catalogue ID, with no inferred routing.

| Fields | Required value |
| --- | --- |
| `schema_version` | `internal-desk-watch-v1` |
| `approval_id`, `exposure_digest` | Current approved UUID and complete paper exposure digest. |
| `sources` | List of 1 to 16 unique objects, each exactly `source_id` and `contract_digest`. Select reviewed sources from the preview. |
| `provider`, `model_id`, `model_configuration` | Explicit provider/model and the complete safe server configuration object, including its version and limit fields. |
| `capture_interval_seconds`, `analysis_interval_seconds`, `lease_seconds` | Explicit positive integer seconds. Size leases for bounded transport and inference work; expiry fences completion. |
| `timezone`, `daily_time`, `daily_start_date` | IANA timezone, exact local `HH:MM`, and first daily slot date as `YYYY-MM-DD`. Nonexistent or ambiguous daylight-saving times require review. |
| `daily_backlog_limit` | Positive integer bound on daily dates admitted during catch-up. Overflow leaves the cursor unchanged and visible. |
| `context_bounds` | Object with positive integer `reports`, `analyses`, `exposure_versions`, `issues`, `source_contracts`, `encoded_bytes`. `analyses` cannot exceed 1000; source bounds must fit the complete manifest. |
| `allowances` | Object with positive integer `window_seconds` and nonnegative integer `analysis_dispatches`, `inflight_slots`, `unresolved_slots`. These supplement shared model admission limits. |

Unknown fields, duplicate JSON keys and coercion are rejected. Bounds reject overflow rather than dropping evidence or exposure. The local configuration file is limited to 262144 bytes. No key belongs in it.

Create the watch with a fresh command UUID and revision zero:

```sh
.venv/bin/python manage.py desk_watch --owner OWNER_UUID --thesis-id THESIS_UUID --config .local/watch.json --command-id COMMAND_UUID --expected-revision 0
```

The response supplies `watch_id` and `revision`. A slot already admitted retains its original watch configuration. Amend using a fresh command UUID and the inspected current revision. Repeating the same configuration command is inert; an old command cannot restore an old watch version. `daily_start_date` cannot rewrite scheduling history. Approval, exposure, source or model changes require explicit review of the pinned configuration.

These commands exercise one bounded tick and read saved state:

```sh
.venv/bin/python manage.py desk_run --watch-id WATCH_UUID --owner OWNER_UUID --role capture --once
.venv/bin/python manage.py desk_run --watch-id WATCH_UUID --owner OWNER_UUID --role analysis --once
.venv/bin/python manage.py desk_inspect --watch-id WATCH_UUID --owner OWNER_UUID
.venv/bin/python manage.py desk_inspect --watch-id WATCH_UUID --owner OWNER_UUID --brief
.venv/bin/python manage.py desk_inspect --review-id REVIEW_UUID --owner OWNER_UUID
```

Replace the UUID placeholders with the reviewed watch and owner identities. These are operator commands; the HTTP API continues to derive identity from its authenticated session.

Continuous operation uses two separate terminals/processes with `--role capture` and `--role analysis`, omitting `--once`. Each requires `--idle-seconds` between 0.1 and 60; optional positive `--max-ticks` bounds the run. Idle time is the delay between ticks, not the saved polling cadence. A capture tick handles at most one slot across its bounded source manifest; an analytical tick handles at most one daily slot and one news-analysis slot. Slow inference stays outside the capture process. Process supervision and production readiness remain separate.

For fictional capture, add `--fixture-map .local/fixture-map.json`. This bounded JSON object maps each configured `fixture-` source ID to a local recorded feed path; it is not a source-rights override. Read-only inspection never starts capture, a catalogue request or inference.

## Daily review behavior

The first daily surface is a private deterministic context assembled from retained evidence and analyses, with source links, original labels, coverage failures, unresolved work and known/unknown costs. Assembly makes no new model call. There is no LLM macro synthesis, external briefing publication, notification or current-context pointer in this increment. Model hypotheses retain their original labels.

Authenticated local clients can list saved reviews with `GET /api/v1/theses/{id}/daily-reviews/` and inspect full retained content with `GET /api/v1/daily-reviews/{id}/`. [The API guide](API_DEVELOPMENT.md#internal-daily-review-inspection) explains pagination, gates and snapshot semantics. These reads preserve the original review and separately observe current staleness; they cannot create, retry or publish work.

Eligibility uses conservative postcommit availability witnesses over `(previous cutoff, current cutoff]`, separately for reports and analyses. Late analysis of an older report belongs to the interval when the analysis became available, provided its source is also eligible. Publication, receipt and analysis finish times cannot replace these witnesses. Missing witnesses remain visible and cannot be backdated.

The reporting cutoff and actual preparation time stay separate. A retained result keeps its original outcome and context; its current disposition is observed at preparation. That observation is not reconstructed currentness at the earlier cutoff.

Complete retained history counts against the configured review bounds, including historical revisions and attempts. Exceeding a bound blocks assembly explicitly; it does not drop the oldest evidence.

Each daily slot has a stable identity. If processing misses its intended time, recovery creates at most one review for that slot and labels it late, with intended and actual times visible. Repeated ticks, schedule changes or restarts cannot create another artifact for the same slot. Daily work proceeds oldest first; an unresolved older daily slot blocks newer daily assembly. Catch-up stays within explicit bounds. Overdue capture and analytical polling is coalesced, which cannot reconstruct missed feed contents.

## Restart and inspection

Capture persists receipts and pending work independently of model availability. A scheduler lease protects a work attempt; network calls run after releasing scheduler/database locks. Postcommit receipt/result observations provide conservative availability witnesses, including recovery after a crash. They do not claim exact admission or commit time.

Before analytical dispatch, the runner commits a marker with the stable command and pinned request. This is deliberately earlier than model admission. Once the marker exists, recovered work only reads the saved news command; it does not repeat catalogue or inference requests. A crash between the marker and admission can therefore leave unresolved work with no news receipt. The marker proves neither a provider call nor a charge. Its conservative boundary prevents automatic paid retries at the cost of requiring operator review of that gap.

An expired lease cannot finalize scheduler state even if a capture or model result was retained. Recovery inspects saved state under a new lease. Lost responses and missed slots do not prove cancellation or zero billing. Failed and uncertain dispatched analysis remain visible and count against configured unresolved allowances. A preflight block with no dispatch does not consume the uncertain-call allowance. These allowances do not stop capture or deterministic daily assembly. Reported charges, estimates and unknown costs remain separate; dispatch/call/token limits do not establish a dollar ceiling.

Approval/exposure changes, source corrections and permission changes must preserve the shared publication ordering protocol. Protect governing sources and owner/thesis/brief state in consistent order before sampling time. Correction-first blocks obsolete current output; publication-first preserves the original decision before invalidating current output and pending notices. An inspection record alone grants no publication or external notification authority.

[Audited operator recovery](JOB_RECOVERY.md) now allows a blocked job to acquire a new fenced lease against its exact last outcome and current reviewed watch revision. Original configurations and failures remain immutable. Deterministic/unstarted work can retry; a dispatched analysis can only reconcile its saved command. Exact recovery-command replay does no work, and failed/uncertain model calls cannot be resent. A recovered earlier daily job unlocks later intervals without skipping a date. Stopping the processes stops polling; no service supervisor or automatic machine-start activation is installed.

## Evidence required before a weekly run

The initial runner regression passed 327 core tests and 344 PostgreSQL/API tests. [Current implementation evidence](IMPLEMENTATION.md#audited-blocked-job-recovery-2026-10-10) records the additional recovery and diagnostic checks. The [fictional trace](../artifacts/continuous-desk-audit.md) proves retained capture-witness recovery, saved-result recovery without credentials, late daily deduplication, predecessor lineage and correction-aware inspection. Tests also cover unknown admitted calls, marker-without-admission recovery, source/model failure independence, explicit overflow, owner scope, protected clock ordering and lease fencing. No real network/model request or week-long unattended soak was performed. Existing publication races remain tested, but these daily reviews have no publication authority.

The [context contract](CONTEXT_CONTINUITY.md) and [weekly test](WEEKLY_WORKFLOW_TEST.md) distinguish these operational requirements from pure domain tests. A successful narrow-feed run cannot establish broad coverage, investment usefulness or full supported-instrument readiness.
