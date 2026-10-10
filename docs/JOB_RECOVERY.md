# Inspect and recover blocked jobs

Status, 2026-10-10: internal operator commands, PostgreSQL evidence and recorded model responses. Recovery preserves the original job, configuration, failure and command identity. It grants no thesis approval, publication or external delivery authority.

## What blocked means

`blocked` is a retained terminal outcome for an attempt, not a claim that a provider request failed or was cancelled. Capture, analysis and daily review stop for different reasons:

| Job | Typical cause | What continues |
| --- | --- | --- |
| Capture | Transport/parser failure, missing adapter, changed contract or withdrawn permission | Later scheduled capture polls can run. Missed contents cannot be reconstructed from a rolling feed. |
| Analysis before dispatch | Missing credentials, changed approved meaning/exposure, source/model changes or exhausted allowances | Capture and deterministic daily review continue. This block does not consume uncertain-call allowance. |
| Analysis after dispatch | Invalid output, provider failure, missing response or uncertain admission/result | No repeated model call. Retained result inspection may resolve scheduler state. Unknown billing stays unknown. |
| Daily review | Complete evidence/context exceeds a bound, unavailable permission or invalid predecessor/input state | Capture and analysis continue. Later daily intervals wait for the oldest unfinished daily job. |

New capacity and allowance failures have explicit safe codes. Older outcomes saved only as `ValueError` lack enough evidence to identify their specific cause. Inspection reports that gap rather than inventing one. Exception messages, provider bodies and credentials are not persisted as diagnostics.

## Inspect first

Load the database environment and internal gates described in [the runner guide](CONTINUOUS_RUNNER.md), then run:

```sh
.venv/bin/python manage.py desk_inspect --owner OWNER_UUID --watch-id WATCH_UUID --brief
.venv/bin/python manage.py desk_inspect --owner OWNER_UUID --watch-id WATCH_UUID
```

The brief shows saved counts, failure explanations, recovery links and the oldest unfinished daily interval. Full JSON supplies the latest lease token, current watch revision, original configuration, outcomes and recovery receipts. Inspection never expires a lease or authorizes a retry.

Fix the actual cause first. If approved meaning, exposure, source selection, model configuration or bounds changed, explicitly review and save a watch amendment. Already admitted jobs retain their original configuration. New jobs use the amendment; manual recovery records exactly which reviewed version an older job will use.

## Choose an explicit action

Use a new recovery command UUID, the last lease token and current watch revision from inspection:

```sh
.venv/bin/python manage.py desk_recover \
  --owner OWNER_UUID --slot-id SLOT_UUID --command-id RECOVERY_COMMAND_UUID \
  --expected-token LAST_LEASE_UUID --expected-watch-revision CURRENT_REVISION \
  --action retry --reason "Reviewed complete context and explicitly increased the byte bound."
```

`retry` can execute deterministic capture/review work or analytical work with no dispatch marker. Analytical retry can incur a charge within existing allowances; this command does not raise or waive them. Current source permission is required for fresh processing. A retained daily artifact is adopted through read-only inspection even if permission was subsequently withdrawn; its current stale disposition stays visible.

Use `--action reconcile` only for an analysis job with a saved dispatch marker. It reads the existing news command before considering keys, current provider configuration or processing permission. It makes no catalogue or inference request. A conclusive retained result can complete scheduler state while preserving its original outcome and current stale disposition. A missing/uncertain/failed result leaves the job blocked. No action acknowledges unknown billing away, resends a dispatched request or guarantees remote cancellation.

Fictional capture recovery can use the same `--fixture-map` as `desk_run`; the synthetic setup gate still applies.

## Ordering and crash behavior

- Admission protects sources in sorted order, then owner, thesis, watch and job before comparing the expected revision/token and sampling time. A competing command cannot consume the same blocked outcome twice.
- Recovery creates an immutable reason/configuration receipt and a new fenced lease atomically. The original job identity, interval, command, configuration and failures remain intact. A daily recovery cannot narrow its original source manifest or skip an older interval.
- Daily creation resolves the actual current approved thesis and full paper book at preparation. The saved context exposes those actual inputs; historical watch pins are not a claim of cutoff currentness.
- An already retained daily artifact wins over changed bounds. Adoption preserves its exact content, preparation time and present disposition; it does not regenerate history to clear a barrier.
- Exact recovery-command replay returns its original receipt and present job state, with no execution. After a lost response, repeat the exact command to inspect it. If its lease expired before finishing, the normal runner reclaims it with the same recovery version. A dispatched analysis remains inspection-only.
- Completed reconciliation removes that job from the current unresolved allowance, while every historical failure and all time-window dispatch counts remain retained. Uncertain or failed calls continue to count.

Increasing a watch bound does not silently amend other queued jobs. Another queued job can still block under its old bounds and need separate review. Stopping the processes stops polling; no supervisor or unattended activation is installed.

## Evidence and remaining limits

The [fictional recovery trace](../artifacts/job-recovery-audit.md) demonstrates a complete-context overflow, reviewed bound change, one recovered daily artifact, inert replay, successor lineage and correction-aware inspection. It uses recorded inference with zero real model/network calls or spend. Independent PostgreSQL tests cover competing requests, actual lock waits, protected clock sampling, scope, lease fencing, immutable history and allowance enforcement.

Cumulative model context, a current daily briefing publication surface, broader source adapters and a supervised live weekly test remain separate work. See [the weekly test](WEEKLY_WORKFLOW_TEST.md) and [source research](../research/source-options-2026-10-10.md).
