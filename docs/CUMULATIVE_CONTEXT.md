# Cumulative monitoring context

Status, 2026-10-10: implemented for explicitly reviewed internal watches, verified with recorded model output and PostgreSQL. This closes the retained-input continuity gap between news calls. It does not establish a verified macro regime, useful live analysis or daily briefing publication.

## What changes for the trader

Each analysis still focuses on one newly selected report. In cumulative mode it also receives the complete eligible retained evidence from the watch's explicit source manifest, earlier private analyses, the current approved thesis and the complete attached paper book. Intraday evidence enters immediately; analysis does not wait for a daily review.

Earlier analysis stays labelled model interpretation. The response can quote multiple eligible reports and must explicitly compare with earlier completed interpretations. Relationships are `strengthens`, `weakens`, `offsets` or `unresolved`, with evidence references and uncertainty. These labels are hypotheses for review, not calibrated weights or automatic thesis amendments. A supportive headline cannot erase earlier counterevidence through input selection.

## Try the recorded proof

After [local PostgreSQL setup](GETTING_STARTED.md), load your development database environment and run:

```sh
export DJANGO_SETTINGS_MODULE=macro_agent.web.local_settings
export MACRO_ALLOW_SYNTHETIC_SETUP=1
export MACRO_ENABLE_MONITORING_PROOF=1
export MACRO_ENABLE_NEWS_ANALYSIS=1
export MACRO_ENABLE_CONTINUOUS_DESK=1
export MACRO_ENABLE_MODEL_COMPILATION=1
.venv/bin/python tools/cumulative_context_demo.py --output .local/cumulative-context-trace.json
```

The tool creates and drops a separate temporary test database; the database role needs test-database creation permission. Use a fresh output path because it refuses to overwrite an existing trace. It uses fictional feeds and a recorded provider, creates two analyses with an offsetting comparison, then simulates a restart after saving the second result. Recovery reads the saved outcome with blank credentials and makes no further call. No real source, model or trader watch is activated. The [retained trace](../artifacts/cumulative-context-trace-2026-10-10.md) records the result and limitations.

## Opt in through a reviewed watch

Follow the [runner setup](CONTINUOUS_RUNNER.md) and preview cumulative configuration:

```sh
.venv/bin/python manage.py desk_watch --owner OWNER_UUID --thesis-id THESIS_UUID --preview --cumulative
```

This reads committed inputs and returns the safe model configuration, including `context: complete_retained_context`, prompt v3 and output schema v2. It neither calls a provider nor creates a watch. Copy the configuration into the reviewed watch JSON with an explicit provider/model, complete source manifest, bounds, timing and allowances. Create or amend the watch using its current revision as described in the runner guide. Existing watches remain in their reviewed mode until explicitly changed.

The manual `review_news.py` HTTP workflow remains single-report v1. Authenticated saved-analysis reads preserve cumulative context and v2 comparisons. Cumulative activation currently belongs to the internal operator runner.

## Admission and recovery contract

1. Read-only preflight assembles and validates the complete selection before catalogue access. It creates no evidence, permission or context rows. Record/byte overflow prevents catalogue and inference calls.
2. After catalogue selection, admission repeats protected assembly against current inputs. Sources are protected in stable order, then owner/thesis, then the existing shared model-budget anchor. The clock is sampled after protection. A catalogue-time change can still reject admission without inference.
3. Admission atomically saves immutable relational evidence membership, private context, complete exposure references, the model attempt and command receipt. The attempt pins the exact model context and messages with digests before inference releases the database transaction.
4. Completion protects every manifest source before owner/thesis, then checks approval, exposure, consumed report heads and source contract/permission versions. A changed dependency preserves the returned result as stale. A distinct later report does not invalidate the earlier cutoff.
5. Saved command identity remains historical. Recovery does not need a key or current model configuration and cannot resend a paid or uncertain call. The original result and its present disposition remain separate.

The scheduler's earlier dispatch marker pins the reviewed source manifest and bounds. The exact context ID/digest becomes available at model admission, not at dispatch or preview. A marker with no saved receipt remains ambiguous after restart; even preflight failure cannot authorize an automatic retry of that marker.

## Selection and bounds

Daily reviews and cumulative admission reuse the same evidence eligibility rules. Reports and analysis results require independent conservative postcommit availability witnesses. Missing or later witnesses appear as explicit deferrals and cannot support quotations. Failed and uncertain results with eligible witnesses remain unresolved metadata, including known/unknown costs.

Every retained revision and private attempt in the manifest counts against the explicit bounds, including historical and deferred records. No input is silently truncated. The configured retained-input byte bound and the existing 65,536-byte complete model-context bound both apply. Long-running watches can reach these limits; automatic summarization or compaction is not implemented.

Private context follows the newest retained daily or admission context and records changes in approval/exposure. Prior documents are validated against their original contexts, then projected without recursively embedding old prompts. Narrowing a source manifest cannot omit sources governing an included prior cumulative analysis. Withdrawal of such a source prevents fresh cumulative admission; historical results remain readable. Source retirement or redaction requires a later explicit policy.

Source claims retain payload digests, receipt and availability observations, observed revision heads and contract provenance. Neither preparation time nor receipt establishes exact durable commit time. Related reports have unknown independence; repeated coverage cannot establish stronger conviction by count.

## Remaining milestones

- Protected daily briefing publication, current pointers, correction propagation and notification intent.
- A reviewed real thesis and suitable permitted sources for the weekly workflow.
- Supervised live model evaluation, operational recovery and weekly soak evidence.
- Source-backed thesis compilation and broader verified macro context.

Charts, broker data, maps, GEX and richer visualizations remain deferred. The compiler still reads exact thesis text and saved answers; cumulative monitoring does not silently change its input contract.
