# Source recovery proof, 2026-10-20

This recorded exercise proves saved-plan recovery through the session/CSRF API and PostgreSQL. It does not establish live GDELT availability or research quality. [Exact records](research-recovery-trace-2026-10-20.json) retain every response and dependency.

## Sequence

1. A fictional rough helium question admits one recorded planning call and one named source question.
2. The first recorded source exchange returns rate limiting with a forty-second cooldown. The failed attempt and exact plan remain saved.
3. Repeating the original command and reading after closing database connections use saved state without credentials or another model/source call.
4. Explicit continuation at thirty-nine seconds makes no source request. Continuation at forty seconds captures one fictional headline.
5. An application exception interrupts after durable capture, before the discovery result is saved. Connections close and the clock advances ninety seconds, beyond the source lease.
6. Read-only inspection exposes retained work. Explicit continuation adopts the committed capture without another GET, then admits the one remaining recorded compilation call.
7. The final evidence packet retains the original failed attempt, safe cooldown metadata, exact successful selection and original research plan. Historical retries remain inert after credentials are removed.

## Results and limits

| Observation | Result |
| --- | --- |
| Recorded model calls | Two: planning and compilation |
| Recorded source exchanges | Two: rate limit and successful capture |
| Real model/source calls | Zero |
| Real model spend | USD 0 |
| Provider-reported fictional charges | Unknown |
| Watches, approvals, positions and notification intents | Zero |
| Existing trader records used | None |
| Temporary PostgreSQL database | Removed after the trace |
| Alternate provider configured | No |

The interruption is an application exception plus closed connections, not an operating-system crash. Other database tests exercise concurrent admission, permission withdrawal, deadlines and immutable records. Compute and storage costs were not measured.

The separate [real diagnostic](gdelt-recovery-probe-2026-10-20.json) received GDELT rate limiting after 11.534 seconds under the new twenty-second policy. It made one request, no automatic retries, no database writes and no model calls. Successful live acquisition remains unverified.

## Reproduce

Complete the local PostgreSQL setup and load its environment privately. Then use an unused output path:

```sh
DJANGO_SETTINGS_MODULE=macro_agent.web.local_settings \
  MACRO_ENABLE_MONITORING_PROOF=1 \
  MACRO_ALLOW_SYNTHETIC_SETUP=1 \
  .venv/bin/python tools/research_recovery_demo.py \
  --output .local/research-recovery-reproduction.json
```

The tool creates and drops an isolated test database, uses only recorded responses, and refuses to overwrite an existing trace. The [recovery guide](../docs/RESEARCH_SOURCE_RECOVERY.md) explains actual terminal usage and pending fallback selection.
