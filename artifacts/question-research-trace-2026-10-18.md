# Recorded question-to-source research proof

Date: 2026-10-18. This proof uses fictional inputs, recorded model responses and a recorded GDELT metadata response through the actual session/CSRF API in disposable PostgreSQL. It uses no existing trader records.

[Exact records](question-research-trace-2026-10-18.json) | [Reproduction tool](../tools/question_research_demo.py) | [Workflow](../docs/QUESTION_RESEARCH.md)

## What happened

1. Start from an exact rough research question, with whitespace and line endings preserved. The user selects a provider/model and supplies no report IDs, thesis interpretation, trade or monitoring request.
2. The recorded planner names an unresolved material question, evidence and counter-evidence to seek, and a targeted query. Its admission is durable before the call.
3. A bounded recorded search returns five fictional candidates. Four are selected in returned order; the fifth remains explicitly excluded. Seen time, receipt, source contract, candidate cap and incomplete coverage remain labelled. No linked article is fetched.
4. Deliberately interrupt after capture commits, before the orchestration step finishes. Close database connections. Read the saved request, then explicitly continue with another discovery request forbidden. The workflow adopts the committed capture and finishes sourced compilation without another search.
5. The research draft includes source-linked proposed drivers and exposure candidates, with assumptions, uncertainty, basis risk and unverified availability. Original question text remains separate from the proposals. No watch, approval, position, current assessment or notification intent is created.
6. Retain a source correction, restart connections and remove/change provider credentials. GET by run, GET by command, exact initial-command retry and continuation preserve the original plan, packet and model output while exposing stale disposition. There is no paid or search fallback.
7. Drop the temporary database.

## Counts and limits

There are two recorded model completions, one for planning and one for compilation, and one recorded discovery call. There are zero real model/source API calls and zero real model spend. Reported planning and compilation charges remain null; local compute/storage costs are unmeasured.

This proves automatic selection and durable workflow mechanics with predetermined replies. It does not prove that the plan is insightful, the selected reports are adequate, a claim is true, a mechanism is causal, or an instrument is tradeable. The current tool is limited to recent headline metadata. Primary-source investigation, independent source-fit assessment, prices, valuation and live usefulness remain outstanding.

## Reproduce

After loading the development database configuration:

```sh
MACRO_ENABLE_MODEL_COMPILATION=1 MACRO_ENABLE_MONITORING_PROOF=1 MACRO_ENABLE_RESEARCH_DISCOVERY=1 DJANGO_SETTINGS_MODULE=macro_agent.web.local_settings .venv/bin/python tools/question_research_demo.py --output .local/new-question-research-trace.json
```

Use a new filename. The tool supplies recorded adapters, creates and drops a unique temporary database, and changes only its cleanup connection's statement timeout to allow bounded PostgreSQL checkpoint work.
