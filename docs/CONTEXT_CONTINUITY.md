# Durable context and daily reviews

Status, 2026-10-09: the first daily surface and internal runtime direction are accepted in [ADR 018](ADR/018-internal-runtime-and-daily-review.md). A pure [daily-review domain module](../src/macro_agent/domain/daily_review.py) has 22 recorded-input tests. It does not select sources, obtain availability witnesses, persist reviews or run work. No database scheduler, context chain, publication integration or continuous runner is implemented.

The next slice must retain what the desk has seen, explain changes against prior analysis and recover without losing evidence or repeating uncertain paid work. The first research question is which assets benefit or suffer from AI buildout, and whether positioning over a few weeks to months is already late. Candidate expressions are an Exness `XCUUSD` copper CFD and AMD/NVDA equity perpetuals. These are research candidates, not verified instrument mappings, approved positions or supported asset packs. No trading thesis or source manifest is approved; the original copper example and synthetic gold case are not selected theses.

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
| Daily slot and review version | Stable owner/thesis/kind/local-date slot, reporting interval/cutoff, actual preparation/publication observations, selected context and retained analysis, source health and unresolved work. Preserve original outcome separately from current disposition observed at preparation. |
| Later cumulative analysis admission/result | Exact context/predecessor, command identity, prompt/model/configuration and allowance admitted before inference. Completion compares protected dependencies before installing a new current result. |

Use relational references for ownership, lineage and correction lookup alongside immutable JSON snapshots for inspection. Do not backfill historical records with claims that these new contracts governed their original execution.

## Evidence selection and cutoffs

Selection is a versioned policy over explicitly reviewed sources. The reporting interval is `(previous cutoff, current cutoff]`. Only evidence conservatively observed durably available by the declared cutoff can enter that cutoff's context. Publication, receipt and analysis finish times cannot substitute for a conservative postcommit availability witness. Such a witness is an upper bound on availability, not an exact commit timestamp. Missing witnesses remain visible and can be recovered through postcommit observation; they cannot be assigned an invented earlier availability.

Classify reports and retained analyses independently by their own availability witnesses. An analysis of an older report belongs in the daily review when the analysis becomes available during the reporting interval, even when no fresh report arrived. Its original report must also be available by the cutoff. Earlier eligible inputs can remain background; inputs with missing or later witnesses remain explicitly deferred. This avoids losing late analysis by selecting only recently published or received articles.

The evidence cutoff and the preparation observation answer different questions. Eligibility uses the reporting cutoff. Current disposition is checked during actual preparation, which may be later; preserve that observation time alongside original status and reasons. Do not present preparation-time currentness as reconstructed state at the earlier cutoff. The pure domain module validates supplied records but cannot establish their currentness, permissions or durable availability itself.

New reports received after the cutoff belong to the next update. They do not invalidate an otherwise valid assessment of the earlier cutoff. Corrections affecting included evidence and permission withdrawals do invalidate dependent current output. Repeated retrieval of an older payload cannot reactivate it.

Begin with exact native identity/content dedupe. Related reports from different sources have unknown independence until evaluated. Article counts cannot strengthen conviction. Preserve offsetting evidence and unresolved grouping rather than treating each headline as a distinct development.

Bounds and exclusions are inspectable configuration. Overflow must reject admission or produce an explicitly degraded review; it cannot silently select the first few reports, drop exposure or compress away inconvenient evidence. The existing 65,536-byte news-context limit and larger compiler-card limit remain separate constraints until reviewed.

## Source corrections and publication

Current capture only supersedes screening work. It does not atomically invalidate published briefs. The current factual-notice candidate also requires one event and qualifying screening; it cannot represent a cumulative or quiet daily review unchanged.

Before daily publication acquires current pointers or notification authority:

1. Add daily publication admission for the pure assembly candidate, preserving the existing factual-notice rules.
2. Track reverse dependencies from included revisions/contracts to private contexts and briefs.
3. Make source correction and permission writers share the publication ordering protocol: protect relevant sources in stable order, then affected owners, theses and briefs in stable order, then sample time.
4. Correction-first preserves the old analysis as stale without publishing it. Publication-first permits the original decision, then correction invalidates current output and cancels pending notices atomically.
5. Approval/exposure changes and late same-context completions must preserve the same ordering and generation protections.

Synchronous correction fanout needs an explicit internal bound because it can delay capture. A deferred invalidation barrier is a separate architectural choice, not an interchangeable optimization. No external delivery is included in this proposal.

## Accepted internal runtime direction

For the internal test, use separate Django capture and analytical processes backed by durable PostgreSQL scheduling and leases. A model call in the analytical process must not delay polling in the capture process. This accepted direction leaves the scheduling records and runner to implement; it does not select a production queue.

Save a stable task/command identity before inference admission. Scheduling work with no admitted call can recover through a lease. Once inference has been admitted, restart inspects the saved outcome; lease expiry does not authorize another paid request. Unknown remote completion and billing remain visible. Capture continues when analytical work is degraded.

Daily identity should be stable by owner, thesis, kind and local reporting date. A changed schedule version alone must not create another daily slot. Intended schedule time and actual creation time remain separate. Late/backfilled work cannot imply that the desk produced it on time.

## Accepted first daily surface

Start with a deterministic daily evidence review: attributed report titles and links, retained analysis available during the reporting interval with original labels, changes since the previous context, unresolved investigations, coverage failures and known/unknown costs. This includes late analyses of older reports. Assembly requires no new model call; historical inference costs remain visible. A later cumulative model summary consumes the same immutable records and can be compared with this baseline.

A review can report that no new eligible reports were received. It cannot infer that nothing happened in the market. A deterministic evidence review is not yet a synthesized macro brief or evidence of investment usefulness.

The existing 22 pure-domain tests cover interval boundaries, late analysis, missing witnesses, retained original outcomes, preparation-time disposition, complete exposure references, immutable content and explicit overflow. They are not evidence of database scheduling, restart recovery or daily publication.

## Decisions still requiring review

- Research the selected AI-buildout question into a tentative hypothesis, test alternatives and expectations, then review matching sources and permitted payload scope. A result of no defensible thesis remains valid.
- Validate candidate instrument availability, actual exposures, basis and financing, and any required equity/valuation support before declaring a supported route. No execution is authorized.
- Design durable scheduler, context lineage and typed daily publication integration, including correction propagation and an internal fanout bound.
- Before unattended activation: polling/detection target, briefing time, bounds, allowances, ambiguous-call disposition and missed-slot policy. A dollar ceiling remains open; call/token limits do not prove one.

## Required evidence

Force correction/publication and permission-withdrawal races through independent PostgreSQL connections. Verify approval/exposure changes during inference, predecessor comparisons, later arrivals without false staleness, duplicate daily ticks, schedule changes, missed slots and restarts after capture, admission and review persistence.

Also prove source/model failure independence, visible context overflow, strict owner scope, unresolved paid outcomes and read-only recovery. Extend the shared model-budget accounting when cumulative attempts are added; an uncounted new attempt table would bypass the current aggregate allowance.
