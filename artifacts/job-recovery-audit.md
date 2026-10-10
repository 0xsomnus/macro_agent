# Audited job recovery, fictional PostgreSQL trace

Generated 2026-10-10 using [continuous_desk_demo.py](../tools/continuous_desk_demo.py) with `--with-job-recovery`. [Complete records](job-recovery-audit.json) preserve the fictional inputs, outcomes, receipts and inspection. Operating values and controlled times are demonstration inputs, not defaults.

## Observed transitions

1. Capture retained fictional reports, including recovery after capture commit. One recorded model result survived interruption before scheduler completion and was adopted after restart without credentials or a second call.
2. Daily assembly rejected a deliberately tiny byte bound with `ReviewCapacityExceeded`. No daily artifact was created and no evidence was discarded. The blocked interval remained the oldest unfinished daily job.
3. A reviewed watch amendment raised the byte bound. Recovery receipt `383910ef-d698-4476-9f61-f3dae251bd14` retained the operator reason, prior token `bed362bd-133d-4b21-9983-501982d119e2` and reviewed version `a5d95c44-be24-41f8-9abc-9b143fd23357`.
4. Recovery completed original slot `28174227-2509-4ac2-8932-3f3f6839e4c6` with one daily artifact `f364fcad-9003-468a-b14e-7ffd2331e05c`. The original failure, original watch version, exact reporting interval and stable daily command remain in history.
5. Repeating exact recovery command `0e38823c-d71d-43a0-bb37-c64167508034` returned its original receipt and current completed state. Execution was patched to fail if invoked; replay returned `processed: null`.
6. The next daily artifact `e856bb55-7cd6-4dfb-b25f-ff512cb04bbe` references predecessor context `61ee194a-5f12-419d-8313-5be39383abc1`, equal to the first context `61ee194a-5f12-419d-8313-5be39383abc1`. A later fictional correction leaves original review content unchanged and present disposition stale.

## Calls, costs and limits

- Recorded catalogue calls: 1; recorded completions: 1.
- Real network calls: 0; real model calls: 0; real model spend: USD 0.
- Reported billing for recorded inference stays unknown. Compute/storage costs were not measured.
- The temporary fictional account was disabled afterward. No live source or unattended watch was activated.
- Sequential trace does not establish races, live usefulness or weekly supervision. Independent PostgreSQL tests separately exercise competing recovery, lock waits, protected clocks, fencing, scope and immutable history.
- Cumulative LLM macro context, current daily publication and external delivery remain outstanding.

## Reproduce

Load the local development database environment, apply migrations, and enable the explicit internal monitoring/news/compilation/continuous-desk/synthetic gates from [the runner guide](../docs/CONTINUOUS_RUNNER.md). Set `DJANGO_SETTINGS_MODULE=macro_agent.web.local_settings`, then use a fresh ignored output path:

```sh
.venv/bin/python tools/continuous_desk_demo.py --with-job-recovery --output .local/job-recovery-trace.json
```

The tool refuses to overwrite an existing trace. Its recorded adapter does not use a real model key. The [operator guide](../docs/JOB_RECOVERY.md) covers actual recovery commands and unresolved-call limits.
