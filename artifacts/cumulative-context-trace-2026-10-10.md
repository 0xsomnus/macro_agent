# Cumulative context, recorded PostgreSQL trace

Generated 2026-10-10 with [the isolated demonstration](../tools/cumulative_context_demo.py). [Full JSON evidence](cumulative-context-trace-2026-10-10.json) retains the approved inputs, selected reports, model documents, dispatch requests, context lineage and restart result.

## Observed behavior

1. A fictional funding-stress report receives one recorded analysis against an approved thesis and attached NQ paper declaration.
2. A second fictional policy-easing report receives a fresh admission-time context containing both source reports and the first labelled analysis. No daily review is required: the retained evidence accumulates intraday.
3. The second recorded output quotes both report revisions and explicitly compares the new policy response with the earlier funding interpretation using `relationship: offsets`. This is authored fixture reasoning, not a measured model judgment.
4. Second context `38036c50-1873-4b39-8c6f-1d9c78c74211` references first context `1cfeedd4-6f69-4fb3-9f14-b605e5444766` as its predecessor. The JSON records both immutable context digests and prompt-context digests.
5. A simulated process loss after the second result commit leaves the scheduler unfinished. Restart with a blank key and changed provider adopts the saved result. Model-configuration lookup is patched to fail if recovery attempts it. Recorded catalogue and completion counts remain two each.
6. Both original analysis records remain current after a distinct later report; retained context is unchanged. Daily reviews created: zero. No thesis amendment, publication or notification occurs.

## Isolation, costs and limits

- The tool creates and migrates a unique temporary PostgreSQL test database, then drops it. It uses no existing trader records and leaves no watch behind.
- Real news-network calls: zero. Real model calls: zero. Real model spend: USD 0. Provider creation and live source fetching are patched to fail if reached.
- Recorded token usage is fixture metadata, and reported billing remains unknown. Compute/storage costs were not measured.
- Complete context means the eligible retained set from the explicit source manifest within configured bounds. It does not establish broad source coverage, factual verification or a current macro regime.
- Prior output remains model interpretation. Exact quotations establish attribution, not factual truth or causal validity.
- This sequential trace does not establish live usefulness, independent race behavior or a supervised weekly workflow. Daily publication and external delivery remain separate milestones.

## Reproduce

Load the local development PostgreSQL environment. The database role must be allowed to create temporary test databases. Use a fresh output path; the tool refuses to overwrite an existing trace.

```sh
set -a
source .local/native-db.env
set +a
export DJANGO_SETTINGS_MODULE=macro_agent.web.local_settings
export MACRO_ALLOW_SYNTHETIC_SETUP=1
export MACRO_ENABLE_MONITORING_PROOF=1
export MACRO_ENABLE_NEWS_ANALYSIS=1
export MACRO_ENABLE_CONTINUOUS_DESK=1
export MACRO_ENABLE_MODEL_COMPILATION=1
.venv/bin/python tools/cumulative_context_demo.py --output .local/cumulative-context-trace.json
```

All cadence, allowance and context values in the demonstration are illustrative fixture inputs, not operating defaults. No real model key is required.
