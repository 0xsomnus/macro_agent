# Continuous internal desk trace

Verified 2026-10-10 with local PostgreSQL, fictional source/thesis/trade, a controlled clock and one recorded model response. [Complete records](continuous-desk-audit.json) preserve inputs and transitions.

- Capture committed a report, then crashed before its receipt witness. A fresh database session recovered the retained revision even though the next snapshot omitted it. The later witness was not backdated.
- News analysis committed its immutable result, then crashed before scheduler completion. Restart without a model key recovered the saved result under the same command. Recorded catalogue/completion counts stayed at one each.
- The missed first daily slot created one review and labelled it late. Repeating the tick produced no duplicate. A second daily review retained the first context as predecessor.
- A correction to an included report changed current disposition from `prepared` to `stale`. Exact original review content and digest `4978e2a6d82ea0417c424f1072496bf2d1315a625423c77f26bc08de37770c71` remained unchanged.
- Daily assembly and capture made no model calls. Real network/model calls and model spend were zero. Recorded model costs remain unknown; local compute/storage were not measured. The fresh account was disabled afterward.

| Local date | Intended cutoff | Saved state | Created late |
| --- | --- | --- | --- |
| 2026-10-10 | 2026-10-10T10:54:00+00:00 | completed | True |
| 2026-10-11 | 2026-10-11T10:54:00+00:00 | completed | True |

The full regression passed 327 core tests and 344 PostgreSQL/API tests, 671 total. Independent connection tests cover lock order, duplicate commands, source/permission races and immutable scope. Migrations and Django checks pass.

These are local workflow mechanics. No live inference quality, live feed suitability, week-long process supervision, cumulative LLM macro context, daily publication or external delivery is established. Blocked outcomes require an operator resolution workflow that remains unimplemented. Demonstration timing and allowances are fixtures, not operating defaults.

Reproduce in an explicitly configured development/test database with all local desk/news/fixture gates enabled:

```sh
.venv/bin/python tools/continuous_desk_demo.py --output .local/continuous-desk-trace.json
```

The tool refuses to overwrite a trace and creates fresh fictional history. See [the operator guide](../docs/CONTINUOUS_RUNNER.md) for setup and honest runtime boundaries.
