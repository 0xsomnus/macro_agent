# Weekly workflow test

Scope clarified 2026-10-09: prove the durable internal paper workflow using a narrow live feed and headline-level analysis. Deep investment analysis, comprehensive coverage and a production trading desk are not acceptance criteria for this test. Source fit, context continuity and the confirmed runtime defects remain prerequisites.

## Current compilation versus the intended thesis pack

| Element | Current behavior |
| --- | --- |
| Exact trader text | Preserved, versioned and approved explicitly. |
| Drivers, horizon, invalidation | Extracted from supplied text with quotations. Missing intent remains empty/null. Drivers are interpreted mechanisms or associations, not verified causal relationships. |
| Challenge | Refinement issues/questions, separate introduced assumptions and agent hypotheses, and an optional unverified counter-case are displayed. |
| Affected assets, catalysts, causal chain and scenarios | No dedicated structured fields yet. An asset mentioned in prose does not establish verified instrument mapping. |
| Collaborative refinement | Questions are displayed, but the terminal compilation loop currently offers approval, cancellation or model switching. It does not collect answers and assemble a strengthened thesis through a guided conversation. |
| External evidence and monitoring manifest | Not supplied to the compiler. No factual verification or current macro regime is established. |

The full design remains in [THESIS_ENGINE.md](THESIS_ENGINE.md); it is not a description of completed implementation. See [current compilation](THESIS_COMPILATION.md).

## Proposed next compilation checkpoint

Implement the [required thesis review card and guided refinement](THESIS_ENGINE.md#required-thesis-review-card): claim, affected assets, proposed causal path, assumptions, catalysts, horizon, invalidation, counter-case/scenarios, evidence and unresolved questions. Distinguish extracted trader intent, agent-proposed additions and unavailable evidence. Let the trader answer consequential questions and review a new immutable proposal.

A missing invalidation criterion is a gap. A suggested criterion can be useful, but cannot become approved meaning until the user explicitly accepts it. Do not invent a threshold, deadline, confidence or price target to fill a template. The approval preview must bind exactly the text and interpretation being activated. Richer proposed fields need a reviewed contract before becoming governing monitoring inputs.

## Durable end-to-end acceptance

1. Enter a limited thesis, inspect its compilation/challenge, answer consequential gaps and approve exact meaning. Attach a manual paper trade with explicit gaps.
2. Capture a reviewed live API/feed and the relevant official complement repeatedly. Preserve headline text, source identity/revisions, receipt/durability timing and visible acquisition failures. Capture continues when analysis is unavailable.
3. Maintain a sourced starting context and versioned cumulative evidence. Each new assessment names its predecessor and explains what changed for the thesis and trade separately. Related reports, distinct developments, corrections and offsetting evidence remain distinguishable; no count of headlines becomes a measure of conviction.
4. Produce a concise daily review from retained eligible evidence, with pending investigations, coverage status, unknown costs and source links. Repeated scheduling cannot duplicate the same daily artifact. Corrected sources or changed approved inputs cannot leave obsolete analysis represented as current.
5. Restart after capture, admission and brief persistence. Preserve pending work and original outcomes. Never silently repeat an uncertain paid call. Replayed commands cannot reactivate old state.
6. Review the week for lost work, duplicate work, stale output, missed eligible reports, useful updates and effort spent reconstructing context. Profit or loss is not the durability acceptance criterion.

Context selection needs an explicit bound and exclusion record. Overflow must reject or visibly narrow the assessment; it cannot silently discard exposure or important evidence. A headline supports attribution to that headline, not its truth, a complete causal account or market expectations. Market-data-dependent claims remain unavailable.

## Proposed continuity and daily-brief contract

| Record | Minimum purpose |
| --- | --- |
| Immutable evidence-set version | Names each retained revision, source contract and receipt/availability witness, plus cutoff, selection-policy version, grouping uncertainty, exclusions and backlog. |
| Private thesis-context version | Pins predecessor context/assessment, approved meaning, full attached exposure and evidence set. Keeps supporting evidence, offsetting evidence, unresolved questions and agent hypotheses distinct. Summaries retain their evidence references. |
| Cumulative analysis admission/result | Commits the exact inputs and model allowance before inference; releases locks for the call; compares protected dependencies before installation. Uncertain calls are not silently repeated. |
| Daily schedule slot and typed publication candidate | A durable unique slot prevents duplicate daily briefs after restart. The candidate identifies multiple evidence revisions, prior assessment, cutoff, currentness dependencies and original outcome. It can explicitly report no new eligible developments received. |

Reuse existing publication generations, immutable assessments and atomic notification intents where their contracts fit. The current single-event publication candidate cannot represent a cumulative digest unchanged. Source corrections and permission changes must participate in publication ordering alongside approval/exposure writers.

Later arrivals after a declared cutoff queue the next update. A correction or permission withdrawal affecting included evidence invalidates affected current output and pending notices. Keeping these cases separate prevents constant capture from indefinitely staling a valid assessment of an explicit earlier cutoff. A quiet receipt does not prove that nothing happened in the market.

Before unattended activation, record the actual thesis/exposure, sources, acceptable detection delay, daily briefing time and model allowance. Production runtime selection remains separate. These are proposed contracts for review, not implemented records or authority.

## Source fit

A narrow feed is sufficient when it addresses the test thesis. The first real thesis and appropriate sources will be researched jointly; no copper thesis is selected. For illustration, Fed sources may support a policy/rates branch but do not supply copper mine-disruption coverage. Copper is not a newly validated instrument pack. The product must also support [user-led research from a question or observation](THESIS_ENGINE.md#user-led-research-before-a-thesis-exists), without requiring a fully formed thesis on entry.

The [source comparison](SOURCE_OPTIONS.md) contains candidates. Official feeds and permitted headline/metadata APIs can prove different parts of ingestion. Linked full articles are not automatically licensed for retention or inference. No new provider, paid subscription or production source is selected by this test plan.

## Remaining choices before implementation

- Select the first real thesis/event and its source manifest.
- Decide whether missing thesis details should first become proposed candidates for approval or clarification questions before any draft completion.
- Review the continuity/brief contract and internal runner, including cadence, daily brief time, model allowance and explicit context bounds.

The [runtime repair report](../artifacts/monitoring-runtime-repair-2026-10-09.md) records the audit repairs. [IMPLEMENTATION.md](IMPLEMENTATION.md) tracks verified status. Fixing those defects does not itself implement continuous dispatch, context continuity or daily briefs.
