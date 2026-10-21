# Background research proof, 2026-10-21

The [exact trace](research-background-trace-2026-10-21.json) demonstrates owner consent, due work and restart through the session/CSRF API and PostgreSQL. All source/model responses are recorded. This is an operational proof, not live research or a source-availability test.

## What happened

1. A fictional rough question admits one planning call. Its first source exchange returns rate limiting with a forty-second delay.
2. The owner explicitly enrolls the saved investigation, binding the exact original request. Repeating enrollment returns history without work.
3. A worker tick at thirty-nine seconds makes no source or model request.
4. The due tick captures a fictional headline. An application exception interrupts before capture observation and discovery-result adoption.
5. Database connections close. After 181 seconds, beyond the worker lease, saved job inspection succeeds with blank credentials and background execution disabled.
6. A new worker lease adopts the committed capture without another source lookup, then admits the remaining compilation. The exact original paid plan is preserved.
7. Session reads expose both immutable leases and their exact source/compilation admission links. Historical enrollment replay remains inert.

## Separate accounting exercise

A named fictional staff operator records a bounded fictional search price. One USD 0.10 maximum reservation fills the investigation's search allowance. A second reservation is rejected. After restart, exact replay retains the original full hold and does not create another reservation.

This is a standalone ledger exercise. The fictional reservation is not a charge for GDELT, which remains the existing free metadata adapter. No paid search transport is configured. The wider database tests independently exercise both monetary limits, concurrent owners and direct database guards.

| Observation | Result |
| --- | --- |
| Recorded model calls | Two: planning and compilation |
| Recorded source exchanges | Two: rate limit and captured response |
| Real source/model calls | Zero |
| Real source/model spend | USD 0 |
| Provider-reported fictional model costs | Unknown |
| Watches, approvals, positions and notification intents | Zero |
| Existing trader records | Not used |
| Isolated PostgreSQL database | Removed after proof |

The interruption uses an application exception and closed connections, not an operating-system crash. The proof establishes neither continuous source coverage nor reasoning quality, broker access, external notification delivery or production supervision. Compute/storage costs were not measured.

## Reproduce

Load the local PostgreSQL environment privately, then choose an unused output path:

```sh
DJANGO_SETTINGS_MODULE=macro_agent.web.local_settings \
  MACRO_ENABLE_MONITORING_PROOF=1 \
  MACRO_ALLOW_SYNTHETIC_SETUP=1 \
  .venv/bin/python tools/research_background_demo.py \
  --output .local/research-background-reproduction.json
```

The tool creates and removes an isolated test database and refuses to overwrite a saved trace. [The user guide](../docs/RESEARCH_BACKGROUND.md) explains enrollment, worker operation, revocation, accounting scope and remaining live-provider work.
