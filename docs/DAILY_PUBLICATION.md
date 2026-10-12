# Internal daily publication

Daily reviews can now become the protected current morning digest for a thesis. Publication saves the exact retained review, its original admission decision, a version and an internal notification intent atomically. It makes no model call. Earlier analyses keep their original status, current labels, provenance and gaps.

This proves publication mechanics. A deterministic digest is still less useful than a fresh analyst synthesis: it preserves evidence reliably but does not newly prioritise developments or reconcile their combined effect. [Fresh synthesis](MORNING_SYNTHESIS.md) and [source-backed compilation](SOURCED_RESEARCH.md) are now implemented separately. Verified starting macro context and live usefulness remain outstanding.

## Try the recorded proof

Load your local database environment as described in [Getting started](GETTING_STARTED.md), then run:

```sh
export DJANGO_SETTINGS_MODULE=macro_agent.web.local_settings
export MACRO_ENABLE_MONITORING_PROOF=1
export MACRO_ENABLE_CONTINUOUS_DESK=1
export MACRO_ENABLE_NEWS_ANALYSIS=1
.venv/bin/python tools/daily_publication_demo.py --output .local/daily-publication.json
```

The synthetic setup flag must also be enabled in your development/test configuration. The tool creates, migrates and drops a unique temporary PostgreSQL database. It uses no existing trader records, provider key or live feed.

The trace publishes generation 1, recovers its saved receipt through new connections, captures a correction, observes a cleared current pointer and canceled intent, and retries the original command without reactivation. A later review publishes generation 2; explicit permission withdrawal cancels it too. See the [readable trace](../artifacts/daily-publication-trace-2026-10-11.md) and [complete records](../artifacts/daily-publication-trace-2026-10-11.json).

## Publish a retained review once

With the continuous desk and monitoring gates enabled, inspect the exact review and preview publication:

```sh
.venv/bin/python manage.py desk_publish --owner OWNER_UUID --review-id REVIEW_UUID --fanout-limit REVIEWED_LIMIT --preview
```

The preview returns the review digest, current generation, current dependency disposition and stable brief identity. Supply those exact values and a new UUID for the command:

```sh
.venv/bin/python manage.py desk_publish --owner OWNER_UUID --review-id REVIEW_UUID --fanout-limit REVIEWED_LIMIT --command-id COMMAND_UUID --expected-generation PREVIEW_GENERATION --expected-review-digest PREVIEW_DIGEST
```

`REVIEWED_LIMIT` must be an explicitly selected integer from 1 to 1000. It is the maximum complete daily-brief fanout permitted for a source correction or permission change. The first attempt fixes this bound for the stream; later commands must match it. There is no implicit activation default.

One-off publication does not enable future automatic publication. For an explicitly reviewed watch, add this optional field to its configuration before enrollment or versioned replacement:

```json
{"daily_publication": {"fanout_limit": 25}}
```

Here, 25 is an example, not a recommended operating value. Absence preserves assembly-only watches. The analytical worker publishes each retained daily review under the slot's stable command identity. Recovery checks saved publication first, including a canceled or originally superseded result. It does not regenerate a review or repeat inference to repair a historical decision.

## Read through the session API

These local endpoints use the existing authenticated session and owner scope:

- `GET /api/v1/daily-reviews/{review_id}/publication-preview/?fanout_limit=REVIEWED_LIMIT`
- `POST /api/v1/daily-reviews/{review_id}/publish/`, with CSRF and exactly `command_id`, `expected_review_digest`, `expected_generation`, `fanout_limit`.
- `GET /api/v1/daily-publications/{publication_id}/`
- `GET /api/v1/theses/{thesis_id}/daily-brief/`

The current endpoint returns the protected pointer and an optional current synthesis for that exact published review. Synthesis adds no publication or delivery authority. A null current publication never falls back to a historical brief. Staff status does not grant access to another trader's records. Responses distinguish the immutable original decision from present disposition and notification state.

## Authority and failure behavior

Publication protects all manifest sources, the owner, thesis and all bound briefs before sampling time. It validates the complete retained review contract, exact hash, approved meaning, exposure book, permission versions and included report heads. Quiet days are valid. Deferred evidence and unresolved/failed analyses remain labelled; publication does not certify their truth or comprehensive coverage.

An included report correction, any consumed-source permission revision, approved-meaning change or paper-book change clears current authority and cancels pending notices in the same transaction. A later distinct report, new analysis or availability witness does not rewrite an already published interval. The next daily review can incorporate it. Original records and versions remain inspectable.

An older review cannot replace a newer retained review or previously published cutoff. A stale generation or dependency produces a retained superseded decision, with no current pointer or new intent. Each review gets one immutable publication identity; a fresh command cannot reactivate it. Exact retries return the saved decision and its present disposition even after permission withdrawal.

New publication preflights each source's complete current/pending dependent set against the smallest affected stream's reviewed bound. Overflow rejects activation atomically. Correction and permission writers independently enforce complete fanout too, so unexpected legacy or bypassed state can visibly block a change rather than partially invalidate. Operator investigation is required; no rows are silently discarded.

Database constraints protect scoped links, immutable history, current/version/intent correspondence and governing changes. The generic factual-notice publisher cannot operate on a daily stream. These safeguards complement the application ordering protocol; raw SQL is not a supported workflow interface.

There is no external notification transport or daily delivery acknowledgement. A pending intent means internal durable work, not a sent alert. Daily `delivered` transitions are rejected. Protected observation times and postcommit witnesses do not measure exact commit or delivery time. Model cost is zero for assembly/publication; compute and storage costs remain unmeasured. Local PostgreSQL checks do not establish live source rights, production performance or analytical usefulness.
