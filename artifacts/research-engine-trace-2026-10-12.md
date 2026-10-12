# Recorded research engine trace, 2026-10-12

This fictional trace exercises both source-backed compilation and fresh morning synthesis in a unique temporary PostgreSQL database. It uses no existing trader records.

| Step | Retained identity | Result |
| --- | --- | --- |
| Selected evidence before approval | `a0f1e3e6-df28-457b-ba33-29c724a39424` | current |
| Source-backed compilation | `9ba58b03-94fe-4955-b89d-513e7e7645d8` | compiled |
| Morning synthesis | `4661ffe6-2a8d-4213-9394-edf1814ee8e4` | synthesised |
| Saved-command restart | `4661ffe6-2a8d-4213-9394-edf1814ee8e4` | same result, replayed |
| Source packet after correction | `a0f1e3e6-df28-457b-ba33-29c724a39424` | stale |
| Synthesis after correction | `4661ffe6-2a8d-4213-9394-edf1814ee8e4` | stale |

The initial trader text asserts a 3% policy rate and a conditional gold view. A fictional retained source states 4%. Compilation quotes both, identifies a possible conflict and asks which date/rate series the trader means. It preserves exact text, including Unicode and line endings. The conflict remains model-identified and answerable; no automatic correction occurs.

The trace explicitly approves that exact review, including its visible unresolved conflict, then attaches one long XAU paper declaration. The digest publishes before fresh synthesis. Recorded synthesis labels the thesis effect `supports` and the open-trade effect `potential_risk`, with citations and uncertainty. These are intentionally recorded interpretations, not validated investment conclusions.

New connections recover the same synthesis command without a configured key or another model call. A later source correction makes the selected packet and synthesis stale, clears the current digest and adjacent synthesis, and cancels the digest's pending internal notification intent. Approved trader text and original model results remain unchanged. No historical output is substituted for a cleared current pointer.

Verification: **964 tests pass**, 418 core/client/provider and 546 PostgreSQL/API. Independent connection tests supplement this sequential trace with forced correction/approval and correction/completion orderings, protected clock checks and lease fencing. Django checks, migration consistency, dependency checks and generated OpenAPI validation pass.

Cost: one recorded compilation completion and one recorded synthesis completion; **zero real model/network calls and zero real model spend**. Unreported charges remain null in retained provider records. Compute/storage cost is unmeasured.

Limits: fictional source and recorded output do not establish live source rights, analytical usefulness, verified macro context, full market coverage or external delivery. A connection restart is not an operating-system crash test. Source selection is manual, and oversized contexts reject without compaction.

Reproduce after loading the local database environment and enabling synthetic setup, monitoring proof and continuous desk:

```sh
export DJANGO_SETTINGS_MODULE=macro_agent.web.local_settings
export MACRO_ENABLE_MONITORING_PROOF=1
export MACRO_ENABLE_CONTINUOUS_DESK=1
.venv/bin/python tools/research_engine_demo.py --output .local/research-engine-trace.json
```

Use a new output filename. The tool creates, migrates and drops its temporary database. [Complete exact records](research-engine-trace-2026-10-12.json), [generated schema](research-engine-openapi-2026-10-12.yaml), [research guide](../docs/SOURCED_RESEARCH.md) and [morning guide](../docs/MORNING_SYNTHESIS.md) expose the contracts.
