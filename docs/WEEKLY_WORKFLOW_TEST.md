# Weekly workflow test

Scope clarified 2026-10-09: prove the durable internal paper workflow using a narrow live feed and headline-level analysis. Deep investment analysis, comprehensive coverage and a production trading desk are not acceptance criteria for this test. Source fit, context continuity and the confirmed runtime defects remain prerequisites.

Accepted next direction, 2026-10-09: begin with a deterministic daily evidence review and separate Django capture/analytical processes using durable PostgreSQL scheduling and leases, per [ADR 018](ADR/018-internal-runtime-and-daily-review.md). The [internal runner](CONTINUOUS_RUNNER.md) now provides PostgreSQL scheduling, immutable context lineage, retained daily evidence and separate capture/analysis processes. Cumulative macro synthesis, protected daily publication and a live weekly soak remain outstanding.

## Current compilation versus the intended thesis pack

| Element | Current behavior |
| --- | --- |
| Exact trader text | Preserved, versioned and approved explicitly. |
| Drivers, horizon, invalidation | Extracted from supplied text with quotations. Missing intent remains empty/null. Drivers are interpreted mechanisms or associations, not verified causal relationships. |
| Challenge | Refinement issues/questions, separate introduced assumptions and agent hypotheses, and an optional unverified counter-case are displayed. |
| Affected assets, catalysts, causal paths and scenarios | Structured text-grounded sections distinguish extracted items, unverified proposals and gaps. This is no verified instrument mapping or canonical causal graph. |
| Collaborative refinement | The terminal saves exact answers without model work, then supports explicit recompilation, model switching, exact approval and read-only command recovery. |
| External evidence and monitoring manifest | Not supplied to the compiler. No factual verification or current macro regime is established. |

The full design remains in [THESIS_ENGINE.md](THESIS_ENGINE.md); it is not a description of completed implementation. See [current compilation](THESIS_COMPILATION.md).

## Implemented text-grounded compilation checkpoint

The [required review surface and guided refinement](THESIS_ENGINE.md#required-thesis-review-card) now combine claim, affected assets, proposed causal paths, assumptions, catalysts, horizon, invalidation, counter-case/scenarios and unresolved questions. External evidence remains unavailable. Exact trader answers and proposal lineage are retained separately from unchanged original prose; each new model request is explicit.

A missing invalidation criterion is a gap. Suggested additions remain agent proposals; explicit answers can express acceptance before a new compiled interpretation is reviewed. No template may invent thresholds, deadlines, confidence or targets. Approval binds the full card with its authority labels, original input and exact answers. It does not adopt every proposal as trader belief or verified evidence. The card is carried into protected news context, subject to its separate size bound; sourced monitoring inputs and verified relationships remain outstanding.

## Durable end-to-end acceptance

1. Enter a limited thesis, inspect its compilation/challenge, answer consequential gaps and approve exact meaning. Attach a manual paper trade with explicit gaps.
2. Capture a reviewed live API/feed and the relevant official complement repeatedly. Preserve headline text, source identity/revisions, receipt/durability timing and visible acquisition failures. Capture continues when analysis is unavailable.
3. Maintain a sourced starting context and versioned cumulative evidence. Each new assessment names its predecessor and explains what changed for the thesis and trade separately. Related reports, distinct developments, corrections and offsetting evidence remain distinguishable; no count of headlines becomes a measure of conviction.
4. Produce a deterministic daily review from retained evidence and analyses available during the reporting interval, including late analyses of older reports, with pending investigations, coverage status, unknown costs and source links. Repeated scheduling cannot duplicate the same daily artifact. Corrected sources or changed approved inputs cannot leave obsolete analysis represented as current.
5. Restart after capture, admission and brief persistence. Preserve pending work and original outcomes. Never silently repeat an uncertain paid call. Replayed commands cannot reactivate old state.
6. Review the week for lost work, duplicate work, stale output, missed eligible reports, useful updates and effort spent reconstructing context. Profit or loss is not the durability acceptance criterion.

Context selection needs an explicit bound and exclusion record. Overflow must reject or visibly narrow the assessment; it cannot silently discard exposure or important evidence. A headline supports attribution to that headline, not its truth, a complete causal account or market expectations. Market-data-dependent claims remain unavailable.

## Continuity and daily-review implementation contract

[CONTEXT_CONTINUITY.md](CONTEXT_CONTINUITY.md) develops the accepted direction into proposed records, correction ordering, recovery boundaries and remaining decisions for the first internal runner. The evidence/context records, scheduler and internal runner are implemented; cumulative model assessment and daily publication remain outstanding.

| Record | Minimum purpose |
| --- | --- |
| Immutable evidence-set version | Names each retained revision, source contract and receipt/availability witness, plus cutoff, selection-policy version, grouping uncertainty, exclusions and backlog. |
| Private thesis-context version | Pins predecessor context/assessment, approved meaning, full attached exposure and evidence set. Keeps supporting evidence, offsetting evidence, unresolved questions and agent hypotheses distinct. Summaries retain their evidence references. |
| Cumulative analysis admission/result | Commits the exact inputs and model allowance before inference; releases locks for the call; compares protected dependencies before installation. Uncertain calls are not silently repeated. |
| Daily schedule slot and typed publication candidate | A durable unique slot prevents duplicate daily briefs after restart. The candidate identifies multiple evidence revisions, prior assessment, cutoff, currentness dependencies and original outcome. It can explicitly report no new eligible developments received. |

Reuse existing publication generations, immutable assessments and atomic notification intents where their contracts fit. The current single-event publication candidate cannot represent a cumulative digest unchanged. Source corrections and permission changes must participate in publication ordering alongside approval/exposure writers.

Later arrivals after a declared cutoff queue the next update. A correction or permission withdrawal affecting included evidence invalidates affected current output and pending notices. Keeping these cases separate prevents constant capture from indefinitely staling a valid assessment of an explicit earlier cutoff. A quiet receipt does not prove that nothing happened in the market.

Report and analysis eligibility use separate conservative postcommit availability witnesses over `(previous cutoff, current cutoff]`, not publication, receipt or analysis finish time. A late analysis can therefore be new while its source report is background. Missing witnesses remain explicit and cannot be backdated. Current disposition is observed at preparation and labelled with that time; it is not reconstructed cutoff currentness.

Before unattended activation, review the actual thesis/exposure, sources, cadence/detection target, daily time/timezone, explicit context and work bounds, allowances, ambiguous-call disposition and missed-slot policy. Production queue selection remains separate. Call/token limits do not establish a dollar ceiling. Neither a lease expiry nor a missed slot authorizes an uncertain paid retry.

## Source fit

A narrow feed is sufficient when it addresses the test thesis. The first joint research question is which assets are affected by AI buildout and whether it is too late to position over a few weeks to months. Candidate expressions are an Exness `XCUUSD` copper CFD and AMD/NVDA equity perpetuals. These are not approved trades, validated instrument mappings or supported packs; no trading thesis or source manifest is selected. Equity and valuation requirements remain to be reviewed. The product must support [user-led research from a question or observation](THESIS_ENGINE.md#user-led-research-before-a-thesis-exists), including a result of no defensible thesis.

The [source comparison](SOURCE_OPTIONS.md) contains candidates. The [free-source research](../research/source-options-2026-10-10.md) adds yfinance, bounded GDELT metadata and future entitlement-scoped user wire credentials. Live Yahoo automated-use permission remains unresolved; GDELT is a proposed adapter. Official feeds and permitted headline/metadata APIs can prove different parts of ingestion. Linked full articles are not automatically licensed for retention or inference. No new provider, paid subscription or production source is selected by this test plan.

## Remaining work and activation choices

- Research the AI-buildout question into a tentative thesis and counter-case, validate any candidate exposure, and review its source manifest.
- Review whether the implemented proposals and clarification questions help strengthen a real rough thesis without manufacturing conviction.
- Add sourced cumulative macro assessment and correction-aware daily publication under the accepted internal direction.
- Exercise [implemented audited job recovery](JOB_RECOVERY.md) against real failure causes during the supervised run. Its recorded tests do not resolve missing/uncertain remote model outcomes.
- Review cadence, daily time/timezone, bounds, allowances, operator handling of ambiguous calls before unattended activation. Missed daily reviews create once and label late, as agreed.

The [runtime repair report](../artifacts/monitoring-runtime-repair-2026-10-09.md) records the audit repairs. [IMPLEMENTATION.md](IMPLEMENTATION.md) tracks verified status. The new runner separately implements continuous dispatch and deterministic retained context. It still needs matching permitted sources, a reviewed thesis and live operating evidence before the weekly test.
