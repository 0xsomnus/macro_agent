# Recorded evolving driver-attention proof

Date: 2026-10-18. This proof uses fictional retained reports and recorded model output through real session/CSRF commands in disposable PostgreSQL. It does not send an alert or use existing trader records.

[Exact records](driver-attention-trace-2026-10-18.json) | [Reproduction tool](../tools/driver_attention_demo.py) | [Workflow](../docs/DRIVER_ATTENTION.md)

## What happened

1. Retain an explicitly approved fictional thesis and close its paper declaration. There are no open positions.
2. Produce a cumulative driver review. The model recommends reviewing the explanation, but no current assessment or notification intent exists from inference alone.
3. Preview the exact analysis digest and generation, then publish under the explicit qualified-review policy. Generation 1 becomes current with one pending internal review intent. Approved trader text remains unchanged.
4. Retain another analysis of the repeated development with the same typed driver state. Publish generation 2. The unread work is carried with a direct link to its original request, the previous intent is canceled, and exactly one current intent remains. This creates no second qualified-review request.
5. Restart connections and inspect the saved publication. Retain a correction to consumed evidence. The current pointer becomes null and the carried intent is canceled atomically.
6. Remove provider credentials. GET the original receipt and retry its exact publication command. Both preserve the immutable decision and report current cancellation without restoring a pointer, generating a new notice or repeating inference.
7. Drop the temporary database.

## Counts and limits

One new qualified-review request, one carried update and zero pending intents after correction. Two recorded model completions and catalogue responses; zero real model/source API calls, external deliveries or model spend. Model-reported charges remain unknown. No watch is implicitly created.

The trace proves the publication, continuity and invalidation lifecycle. Separate tests force both source/publication orderings through independent PostgreSQL connections and fence expired or replaced runner leases. Predetermined model output does not establish real materiality, causal attribution, source adequacy or useful detection latency. External delivery, acknowledgement, semantic deduplication and live calibration remain outstanding.

## Reproduce

Load the development database configuration, then run:

```sh
MACRO_ENABLE_MODEL_COMPILATION=1 MACRO_ENABLE_MONITORING_PROOF=1 MACRO_ENABLE_NEWS_ANALYSIS=1 MACRO_ENABLE_CONTINUOUS_DESK=1 MACRO_ALLOW_SYNTHETIC_SETUP=1 DJANGO_SETTINGS_MODULE=macro_agent.web.local_settings .venv/bin/python tools/driver_attention_demo.py --output .local/new-driver-attention-trace.json
```

Use a new filename. The tool uses recorded adapters and a unique temporary database. Its longer cleanup timeout applies only to the database-maintenance connection, leaving application timeouts unchanged.
