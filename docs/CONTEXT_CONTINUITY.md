# Durable context and daily reviews

Status: implementation proposal, 2026-10-09. No context chain, daily scheduler or continuous runner is implemented by this document. It refines the [weekly test contract](WEEKLY_WORKFLOW_TEST.md) for review before implementation.

The next slice must retain what the desk has seen, explain changes against prior analysis and recover without losing evidence or repeating uncertain paid work. The first live thesis and matching sources remain a joint research task. Copper and the synthetic gold example are not selected test theses.

## Existing boundaries to preserve

- Approved prose, interpretation and complete attached-thesis exposure remain governing inputs. Context and assessments cannot amend them.
- Evidence acquisition is shared where permitted. Private thesis inputs and interpretation remain owner-scoped. These records do not settle the open shared-versus-private model-generated macro-context policy.
- A prior summary is agent interpretation, with evidence references and uncertainty. It cannot replace the retained evidence or become canonical knowledge through repetition.
- Capture and deterministic source health continue independently of models. Missing context, model failure and exhausted allowances remain unresolved.
- Publication, receipt and conservative postcommit availability witnesses stay distinct. No record claims exact commit time or retroactive operational availability.

## Additive records

| Record | Required content and purpose |
| --- | --- |
| Reviewed source-contract version | Stable source identity, immutable contract/digest, named review provenance and current permitted status. Rights changes preserve prior versions and cannot silently authorize a new use. |
| Evidence-set version and members | Explicit source manifest, cutoff, selected revision/contract identities, exact payload digests and availability witnesses. Record policy, exclusions, backlog and grouping uncertainty. Indexed member references support correction lookup. |
| Private thesis-context version | Exact approved inputs and full exposure, evidence set, predecessor context and assessment, unresolved questions and explicit unavailable starting macro context where necessary. |
| Durable watch/schedule version | Reviewed thesis, sources, provider/model, cadence, timezone/briefing time, explicit context bounds and allowances. Changing configuration cannot rewrite an admitted run. |
| Daily slot and review version | Stable owner/thesis/kind/local-date slot, intended cutoff, actual preparation/publication observations, selected context and retained analysis, source health and unresolved work. Preserve original outcome separately from current disposition. |
| Later cumulative analysis admission/result | Exact context/predecessor, command identity, prompt/model/configuration and allowance admitted before inference. Completion compares protected dependencies before installing a new current result. |

Use relational references for ownership, lineage and correction lookup alongside immutable JSON snapshots for inspection. Do not backfill historical records with claims that these new contracts governed their original execution.

## Evidence selection and cutoffs

Selection is a versioned policy over explicitly reviewed sources. Only evidence conservatively observed durably available by the declared cutoff can enter that cutoff's context. A publication timestamp alone is insufficient. Missing witnesses remain visible and can be recovered through postcommit observation; they cannot be assigned an invented earlier availability.

New reports received after the cutoff belong to the next update. They do not invalidate an otherwise valid assessment of the earlier cutoff. Corrections affecting included evidence and permission withdrawals do invalidate dependent current output. Repeated retrieval of an older payload cannot reactivate it.

Begin with exact native identity/content dedupe. Related reports from different sources have unknown independence until evaluated. Article counts cannot strengthen conviction. Preserve offsetting evidence and unresolved grouping rather than treating each headline as a distinct development.

Bounds and exclusions are inspectable configuration. Overflow must reject admission or produce an explicitly degraded review; it cannot silently select the first few reports, drop exposure or compress away inconvenient evidence. The existing 65,536-byte news-context limit and larger compiler-card limit remain separate constraints until reviewed.

## Source corrections and publication

Current capture only supersedes screening work. It does not atomically invalidate published briefs. The current factual-notice candidate also requires one event and qualifying screening; it cannot represent a cumulative or quiet daily review unchanged.

Before daily publication acquires current pointers or notification authority:

1. Introduce a sibling typed daily candidate, preserving the existing factual-notice rules.
2. Track reverse dependencies from included revisions/contracts to private contexts and briefs.
3. Make source correction and permission writers share the publication ordering protocol: protect relevant sources in stable order, then affected owners, theses and briefs in stable order, then sample time.
4. Correction-first preserves the old analysis as stale without publishing it. Publication-first permits the original decision, then correction invalidates current output and cancels pending notices atomically.
5. Approval/exposure changes and late same-context completions must preserve the same ordering and generation protections.

Synchronous correction fanout needs an explicit internal bound because it can delay capture. A deferred invalidation barrier is a separate architectural choice, not an interchangeable optimization. No external delivery is included in this proposal.

## Proposed first runtime

For the internal test, use separate Django capture and analytical processes backed by PostgreSQL scheduling and leases. A model call in the analytical process cannot delay polling in the capture process. This is a proposed internal runner, not a production queue selection.

Save a stable task/command identity before inference admission. Scheduling work with no admitted call can recover through a lease. Once inference has been admitted, restart inspects the saved outcome; lease expiry does not authorize another paid request. Unknown remote completion and billing remain visible. Capture continues when analytical work is degraded.

Daily identity should be stable by owner, thesis, kind and local reporting date. A changed schedule version alone must not create another daily slot. Intended schedule time and actual creation time remain separate. Late/backfilled work cannot imply that the desk produced it on time.

## Proposed first daily surface

Start with a deterministic daily evidence review: attributed report titles and links, retained eligible analysis with its original labels, changes since the previous context, unresolved investigations, coverage failures and known/unknown costs. A later cumulative model summary consumes the same immutable records and can be compared with this baseline.

A review can report that no new eligible reports were received. It cannot infer that nothing happened in the market. A deterministic evidence review is not yet a synthesized macro brief or evidence of investment usefulness.

## Decisions still requiring review

- First market question and tentative hypothesis, then matching source manifest and permitted payload scope.
- Deterministic daily review first, or cumulative inference in the initial daily increment.
- Separate local runner processes first, or selection of a production queue now.
- Before unattended activation: polling/detection target, briefing time, bounds, allowances, ambiguous-call disposition and missed-slot policy. A dollar ceiling remains open; call/token limits do not prove one.

## Required evidence

Force correction/publication and permission-withdrawal races through independent PostgreSQL connections. Verify approval/exposure changes during inference, predecessor comparisons, later arrivals without false staleness, duplicate daily ticks, schedule changes, missed slots and restarts after capture, admission and review persistence.

Also prove source/model failure independence, visible context overflow, strict owner scope, unresolved paid outcomes and read-only recovery. Extend the shared model-budget accounting when cumulative attempts are added; an uncounted new attempt table would bypass the current aggregate allowance.
