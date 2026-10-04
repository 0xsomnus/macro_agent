# Learning and evaluations

Updated 2026-10-02. Automated outcome learning is deferred by [ADR 012](ADR/012-pilot-learning-and-evaluation.md); it is not an implicit Phase 1B feature.

## Records now, outcome learning later

The pilot preserves exact approved theses and interpretations, assessment/context snapshots, evidence, approvals, user decisions, permitted price/fundamental observations, and basic outcome records. These support audit, manual review, and future evaluation. Capture is not evidence of predictive success or permission to learn a general rule.

Do not run automated postmortem generation, `CandidateLearning` generation/retrieval, outcome-derived regime evidence accumulation, or a learning-to-edge-promotion pipeline in the pilot. Prior assessments can explain how a current view changed, but outcomes cannot silently supply a new rule for current analysis.

The desk still updates current source facts and macro assessments as evidence arrives. Manual corrections to canonical relationships need a named human reviewer, rationale, scope/regime, evidence and counter-evidence, and retained predecessor versions. This is curated knowledge maintenance, not automated outcome learning.

Later learning begins as an offline experiment. Its proposed path remains `OutcomeObservation -> Postmortem -> CandidateLearning -> evidence accumulation -> GraphChangeProposal -> human ReviewDecision`. Provisional lessons must expose cases, counterexamples, uncertainty, and their provisional status. Fresh cases, including failure cases, must show value beyond the existing desk before any outcome-derived retrieval or promotion reaches production. Trader agreement or one profitable call is not sufficient evidence; online model-weight training remains deferred.

## Outcome records and later studies

Record claim validity, stated horizon, catalyst/signposts, timing, instrument expression, expectations where known, observed response, alternate explanations, confounders, and process quality. Trade P&L or next-day direction alone is not the score. Unknown expectations remain unknown; observed market reactions cannot retrospectively establish what was priced in.

Statistical event studies are deferred. Prospectively collect permitted timestamped inputs from the paper pilot. Later FOMC, CPI, and NFP studies require verified consensus vintages, actual/revised values, available pre-event pricing, regime descriptors, and defined reaction horizons. Report sample count, selection rules, uncertainty, and input limitations. Guard against look-ahead, survivorship, revised-data leakage, and choosing only notable events. A historical association does not establish a causal probability.

## Three different evaluation claims

| Evaluation | What it can establish | Limit |
| --- | --- | --- |
| Deterministic replay | Capture, identities, revisions, routing, authority, state transitions, and delivery recovery under recorded versions and fake clocks. | Does not establish model foresight. |
| Historical reasoning evaluation | Evidence discipline, qualified interpretation, and workflow behavior using declared point-in-time inputs. | A modern LLM may already know subsequent outcomes; restricted retrieval alone cannot remove hindsight. |
| Forward paper pilot | Timely contemporary detection, analytical usefulness, and operational behavior as events arrive. | A small sample does not establish broad universe coverage, stable predictive skill, or returns. |

System replay uses the exact versions durably known and active at the cutoff. `public_available_at`, `system_received_at`, and `known_at` have different meanings. Historical backfills never pretend the desk acquired evidence before it did. Preserve the assessment's approved compiled interpretation, activation, source manifest/contract, coverage contract, exposure, macro context, graph/rules, prompts, model configuration, and evidence excerpts or explicit reconstruction limits.

## Pilot design

1. Use a calibration period to tune thresholds and define costs, alert noise, latency, and usefulness against representative theses and exposures.
2. Freeze acceptance criteria, evaluation protocol, and relevant configuration before a separate subsequent evaluation period. Material configuration changes begin a new evaluation rather than silently retuning the current one.
3. Independently review all feeds in the sampled scope, not just generated alerts. Assemble relevant event labels including events the system never captured or surfaced; record reviewer disagreement and unresolved relevance.
4. Blindly compare the desk with a simpler brief built from the same permitted, available sources and cutoff. Also retain a deterministic monitoring baseline. Compare accurate portfolio connections, counter-analysis, overlooked factors, and research effort saved.
5. Report sample, exclusions, source contracts, feed outages, model/configuration versions, baseline, costs, and failure examples. Separate source acquisition misses from routing/analysis misses and delivery failures. A failed news feed is a coverage incident, not proof that no relevant event occurred.

The first paper pilot covers the approved narrow instrument set while retaining global contextual monitoring. Follow initial traders' workflows afterward. Source coverage contracts define the denominator; manually reviewing sampled feeds cannot prove coverage of every external development.

## Measures

- **Monitoring:** timeliness, candidate recall within declared scope, material misses, false interruptions, dedupe, accumulated evidence, correction handling, and coverage gaps.
- **Reasoning:** factual accuracy, passage/field support, exposure relevance, causal restraint, counter-case quality, explicit unknowns, and authority preservation. Assess forecast calibration only for explicitly defined probabilistic outcomes, not an undefined confidence score.
- **Operations:** shared acquisition, shared analysis and private costs; retries; fan-out; latency to useful notice/assessment; budget and outage behavior; delivery recovery and stale-version protection.
- **User value:** relevant factors discovered, better supported and falsifiable theses, useful challenges, and research time saved. Reduced conviction or abandoning a weak thesis can be a good result. Engagement, trader agreement, and bullish confidence are insufficient measures.

Maintain adversarial cases for factual errors, unsupported mechanisms, incomplete novice theses, defensible contrarian views, stale sources, headline duplicates, slow independent accumulation with offsetting evidence, unfamiliar severe events, regulatory-stage confusion, unlicensed/private content, source attacks, model outages, and exhausted budgets.

## Acceptance

- Replay cannot access later received/derived/approved evidence, later revisions, or later active interpretations and graph/macro versions.
- Independent review can identify missed events absent from the system's output; the evaluation preserves disputed labels.
- A hawkish announcement followed by a positive index reaction creates an observation with confounders, never an automatic bullish-policy rule.
- No automated learning, provisional-learning retrieval, or learned-edge promotion executes in the pilot.
- Reported improvement names its comparison, frozen protocol, fresh evaluation cases, sample size, and failure examples. Small-pilot success cannot support a full-universe claim.
