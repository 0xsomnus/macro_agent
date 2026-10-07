# Prove capture and restart recovery

This local harness preserves source updates and pending work in PostgreSQL. Capture runs without a model, and a separate worker can recover the work after the capturing process exits. It proves the first part of the monitoring pipeline, not a continuous trading desk.

No model key or news subscription is required. These commands do not approve a thesis, analyse portfolio impact, publish a brief or send an alert. Screening currently records `unresolved_queue`, so successful processing does not mean an event was judged immaterial.

## Prepare the local database

Run commands from the repository root. Follow [getting started](GETTING_STARTED.md) if Python, dependencies or PostgreSQL are not ready. In the prepared checkout, load its existing configuration and apply migrations:

```sh
set -a
source .local/native-db.env
set +a
export MACRO_ENABLE_MONITORING_PROOF=1
export MACRO_ALLOW_SYNTHETIC_SETUP=1
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
```

For a separately configured development checkout, load `.local/db.env` instead. Repeat the environment-loading step in every new terminal. The commands require `macro_agent.web.local_settings`, a database ending in `_dev` or starting with `test_`, and `MACRO_ENABLE_MONITORING_PROOF=1`. Fixtures also require `MACRO_ALLOW_SYNTHETIC_SETUP=1`. Keep reports in ignored `.local/`.

## Capture now, process after restarting

The recorded feed contains fictional source items. Capture them without starting the worker:

```sh
.venv/bin/python manage.py monitor_capture --fixture fixtures/monitoring_feed.json
.venv/bin/python manage.py monitor_inspect --source fixture-monitor
```

Inspect the receipts, revisions and pending work. Capture commits the receipts and their work together. Exiting this command leaves the work in PostgreSQL.

On a fresh fixture source, the first capture creates two reports, two revisions and two pending work items. Later runs may reuse those records.

Close the terminal, open a new one, return to this checkout and reload the database configuration. Then process the preserved work:

```sh
set -a
source .local/native-db.env
set +a
export MACRO_ENABLE_MONITORING_PROOF=1
export MACRO_ALLOW_SYNTHETIC_SETUP=1
.venv/bin/python manage.py monitor_work --limit 10 --lease-seconds 30
.venv/bin/python manage.py monitor_inspect --source fixture-monitor --output .local/monitor-trace.json
```

The trace should show the original receipts and completed attempts with an unresolved outcome. Restart did not require fetching those items again. If more than ten items are pending, another bounded worker pass can process the remainder. `--output` creates a new file with owner-only permissions and refuses to overwrite one; choose another filename for a later report.

Capture the original fixture again:

```sh
.venv/bin/python manage.py monitor_capture --fixture fixtures/monitoring_feed.json
.venv/bin/python manage.py monitor_inspect --source fixture-monitor
```

The additional capture attempt is visible. Identical item payloads do not create extra revisions or work. Existing records may already be present from an earlier walkthrough, so compare changes rather than assuming an empty database.

## Preserve a changed source payload

```sh
.venv/bin/python manage.py monitor_capture --fixture fixtures/monitoring_feed_correction.json
.venv/bin/python manage.py monitor_inspect --source fixture-monitor
.venv/bin/python manage.py monitor_work --limit 10 --lease-seconds 30
.venv/bin/python manage.py monitor_inspect --source fixture-monitor
```

A previously unseen payload under the same native item ID creates a new observed revision and pending work. The older revision remains inspectable. Its completed result keeps its original decision, while its current disposition becomes superseded. Fetching an already known older payload does not roll the current revision back.

This correction fixture changes one of the two original items.

This is observed payload history. The adapter does not establish publisher revision order or authoritative correction semantics. It does not propagate a source correction into existing thesis briefs, whose publication protection remains a separate requirement.

## Try the narrow official feed

After the recorded workflow, capture the configured Federal Reserve press-release RSS snapshot:

```sh
.venv/bin/python manage.py monitor_capture --source fed-press
.venv/bin/python manage.py monitor_inspect --source fed-press
.venv/bin/python manage.py monitor_work --limit 10 --lease-seconds 30
```

The adapter uses a fixed official endpoint and retains bounded feed fields, including the publisher's description where supplied. It does not fetch linked articles. A successful poll establishes what this bounded snapshot returned, not complete news coverage or continuous operation. Items missing from a later snapshot are not treated as deletions.

The source contract records the permitted internal use and its exclusions. Adding another source requires its own identity, transport, correction and rights review. News-data spending remains undecided.

## Read the trace correctly

| Evidence | Meaning and limit |
| --- | --- |
| Capture attempt and source health | Successful capture, transport/parser failure and last successful capture are distinguishable. Health does not establish coverage or a latency guarantee. |
| Native item ID and payload hash | Repeated payloads are deduplicated within a source. Separate publishers are not merged or counted as independent developments by this harness. |
| Published time | A publisher claim where supplied. It is not proof of public availability or system receipt. |
| Receipt time | When this process received the snapshot. Historical publication dates do not move receipt into the past. |
| First post-commit witness | A conservative observation that persistence had completed by that time. It is not the exact earliest durable known-at instant. |
| Work lease and attempt | A bounded worker claim. Expired deterministic work can be reclaimed; an obsolete lease token cannot complete a newer claim. This does not authorize retries of uncertain paid model calls. |
| Original result and current disposition | What an attempt decided remains distinct from whether that result still applies to the current observed payload. |
| `unresolved_queue` | Classification and personalised impact are still unresolved. This is not a low-relevance decision. |

The JSON report contains `source`, `health`, `counts`, `revisions` and `work`. Counts distinguish pending, running, completed and superseded work. Inspection displays at most 100 revisions, 100 captures and 100 attempts per displayed work item, with separate truncation flags. Terminal JSON escapes control characters from source text.

Network fetching happens outside database locks. Capture admission permits one in-flight fetch per source until its 30-second deadline; no automatic fetch retry is issued. Per-source protection serialises receipt revision and work admission. There is no cursor-completeness promise: byte/item limits and failures remain visible, and a snapshot cannot guarantee recovery of items that disappeared between polls.

## Verified mechanics and limits

On 2026-10-07, 26 monitoring tests passed against PostgreSQL, including crash recovery through an independent connection, both changed-payload/completion lock orderings observed on the server, lease fencing, immutable evidence, work admission beyond 100 live leases, and coherent read-only inspection during a concurrent source change. Tests also verify mid-batch rollback, naive-clock rejection, inspection limits and preservation of original receipt/witness times after duplicate capture.

Separate command processes captured the two fictional items, inspected them as pending, and processed both without recapture. Re-fetching created no extra revisions; one changed payload added a revision and superseded the original result's current disposition. Re-fetching the original payload did not roll the head back. A real capture from the configured Fed endpoint durably saved 20 items. The [audit trace](../artifacts/monitoring-audit.md) separates these observations from test evidence and coverage limits. Continuous operation remains unproven.

| Tested failure or transition | Evidence |
| --- | --- |
| Capture crashes after receipt commit | An independent connection recovers the same durable pending receipt without recapture or a pre-crash availability witness. |
| Identical retrieval | Another capture attempt, no additional revision or work for the identical payload. |
| Changed payload followed by an old payload | Preserved revision history, superseded old disposition, no rollback to an already known payload. |
| Worker lease expires | A later claim can finish, and completion using the earlier token is rejected. |
| No model is configured | Capture and deterministic unresolved processing still work; relevance remains unresolved. |
| Malformed or unavailable source | A failed capture is visible and does not masquerade as an empty successful feed. |

A daemon, production queue, backfill completeness, materiality screening, shared macro analysis, thesis/trade routing, global correction protection, morning briefs and delivery remain ahead. The next design step is to connect committed source evidence to protected context and useful analysis without weakening approval or currentness rules. See the [monitoring slice](MONITORING_SLICE.md) and [roadmap](ROADMAP.md).
