# Evolving driver briefs and internal attention

A retained cumulative driver review can now become a protected current news brief. A separate, explicit policy can admit qualified internal review work when evidence changes the trader's explanation, even with no attached trade. The model's attention recommendation alone is not publication authority.

This is an internal publication and notification-intent path. It sends no email, push or other external alert and does not establish calibrated market materiality or measured detection latency.

## Publish a retained analysis once

Use a cumulative driver-review analysis from a [reviewed watch](CONTINUOUS_RUNNER.md). Single-report analysis remains inspectable but cannot acquire publication authority through this route. The continuous desk, monitoring and news-analysis local gates must be enabled.

```sh
.venv/bin/python tools/publish_driver_news.py --analysis-id ANALYSIS_UUID --fanout-limit REVIEWED_LIMIT
```

The terminal displays the exact digest, generation and policy before confirmation. Publication makes no model or source request. The fanout limit is an explicit integer from 1 to 1000, shared with complete source-dependent invalidation checks. It is fixed for the stream on first publication, with no hidden operating value.

Inspect current authority or recover a saved command:

```sh
.venv/bin/python tools/publish_driver_news.py --thesis-id THESIS_UUID --current
.venv/bin/python tools/publish_driver_news.py --thesis-id THESIS_UUID --recover-command COMMAND_UUID
```

An absent current pointer returns no current brief, without substituting history. A retry returns the original decision and current disposition; it cannot reactivate canceled work.

## Enable on an existing reviewed watch

Keep the exact cumulative driver-review model configuration, then add this option to the complete watch configuration:

```json
{"news_publication": {"fanout_limit": 25, "policy_version": "evidence-linked-driver-review-v1"}}
```

Here, 25 is an example, not a recommended value. Omission preserves previous behavior. This option is independent of daily publication and synthesis. Enroll or replace the watch through its existing explicit versioned command. Research requests do not enroll it.

The runner records the analysis before publication. New automatic publication requires the exact current watch version and a protected live slot lease; an expired or replaced worker cannot install fresh current output. Saved publication recovery precedes that fence and requires no model credentials.

## Qualified-review policy

`evidence-linked-driver-review-v1` requires a retained cumulative driver analysis, current dependencies, exact approved-driver references and current quotations linked to those drivers. The first qualified review, or a change in typed premise support, mechanism support or a related competing/amplifying/offsetting pathway, can request internal review. Unmapped or unlinked recommendations remain visibly unresolved.

New wording, duplicate evidence or new facts with unchanged typed driver states can update the brief without requesting another interruption. This conservative categorical rule is an experimental attention policy. It can miss a meaningful change within the same category; it is not a validated materiality classifier. Semantic deduplication of paraphrased developments, numeric thresholds and live calibration remain outstanding. No result proves an event non-material or disables capture.

An unread pending review is not silently lost as the brief advances. A `review_carried` decision moves the internal work to the current brief while retaining a direct link to its original review request. This is not another interruption. The original evidence, permissions and source heads must still be current and included in the new protected context. Dropping those dependencies rejects publication. Source correction cancels carried work too. External delivery and acknowledgement would need their own lifecycle and idempotency rules.

## Publication invariants

The stable stream is `news:{thesis_id}`. Each retained analysis gets one immutable publication decision. The exact analysis document, approved interpretation, full paper book, source revisions, permissions, model configuration and provenance are bound before publication. Sources precede owner, thesis and sorted briefs; automatic admission additionally protects its watch and slot before sampling time.

The current pointer, brief version and internal notification intent change atomically. Source correction, permission revision, approved-meaning change or paper-book change clears obsolete authority and cancels pending work under the same ordering protocol. Fanout checks cover the complete union of daily and news dependents. The generic factual-notice publisher cannot write this stream. Direct database guards enforce scope, immutable history, correspondence and lease constraints.

Daily briefs remain separate. They can retain earlier labelled analyses without implying another delivery. Publication does not edit approved trader text, adopt an agent hypothesis or promote a causal edge.

## Session API

- `GET /api/v1/news-analyses/{analysis_id}/publication-preview/?fanout_limit=LIMIT&policy_version=evidence-linked-driver-review-v1`.
- `POST /api/v1/news-analyses/{analysis_id}/publish/`, exactly `command_id`, `expected_analysis_digest`, `expected_generation`, `fanout_limit`, `policy_version`.
- `GET /api/v1/news-publications/{publication_id}/`.
- `GET /api/v1/theses/{thesis_id}/news-publication-commands/{command_id}/`.
- `GET /api/v1/theses/{thesis_id}/news-brief/`.

Writes require session/CSRF authority; staff status grants no private-row bypass. Responses separate the original publication decision, current disposition, attention decision, original attention publication and current intent state. The [recorded proof](../artifacts/driver-attention-trace-2026-10-18.md) and independent-connection tests cover corrections, evolving work and restart recovery. They do not prove live coverage, source adequacy, notification delivery or useful market reasoning.
