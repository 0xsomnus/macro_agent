# Thesis engine

Status, 2026-10-09: this document specifies intended behavior. The [current compiler](THESIS_COMPILATION.md) implements only text-grounded extraction and separate challenge output. The complete review card, guided refinement and sourced research below remain implementation work for the [weekly workflow test](WEEKLY_WORKFLOW_TEST.md).

## Compilation contract

Input: exact user thesis, asset or position context, horizon where supplied, optional explicit assumptions and sensitivity. Output: an immutable `CompiledThesisVersion` draft linked to exact user text, plus separate refinement issues and proposed amendments. Compilation never silently substitutes new user belief.

1. Parse thesis into claims, observable facts, forecasts, causal mechanisms, associations, assumptions, catalysts, timing, and invalidation signposts.
2. Resolve asset identity and relevant economy, underlying, issuer, and instrument relationships. Build a driver graph with typed, versioned edges.
3. Verify checkable premises using canonical sources. Put errors in `FactualConflict` with the supporting passage/data field, source, and vintage, and show these before the agent's assessment. Do not correct the user's prose silently.
4. Compare with current evidence, consensus or market-implied expectations when available, and relevant historical regimes. Label unavailable expectation data explicitly.
5. Generate base, upside, and downside paths, a credible counter-case, alternative explanations, uncertainty, and leading signposts. Ask what must be true for the thesis to work.
6. Compile a canonical source manifest mapping each driver to its observation, source, cadence, threshold candidate, fallback, and coverage status.
7. Show an epistemic quality diagnostic: causal coherence, empirical support, current-regime support, expectation awareness, counter-case strength, and observability. The diagnostic is a prompt for scrutiny, not a veto.
8. Show a concise interpretation of main drivers, horizon, and invalidation signposts, including unresolved items. User explicitly approves both exact `UserThesisVersion` text and the interpreted `CompiledThesisVersion`, revises a draft, or keeps visible conflicts. An append-only `CompiledThesisActivation` records what became active and the authority for doing so.

## Required thesis review card

Present the following together before approval, rather than scattering the thesis across model prose and questions. Each element must be populated or explicitly marked unresolved or not applicable, with a reason. A complete review surface does not imply a complete or verified investment argument.

| Element | Required content |
| --- | --- |
| Central claim | What the trader believes may happen, and the conditional forecast or direction where supplied. |
| Affected assets | Relevant assets, economies and underlying exposures; distinguish these from an actual instrument or attached trade. Unverified mappings remain labelled. |
| Causal drivers | Proposed transmission path, links between drivers and affected assets, conditions and limitations. Distinguish causal hypotheses from observed associations. |
| Assumptions | What must hold, distinguishing trader-supplied assumptions from agent-proposed additions and sourced observations. |
| Catalysts | Developments that could advance, delay or challenge the argument, linked to the relevant driver; timing remains unknown unless supported or supplied. |
| Horizon | The thesis's intended period, separately from catalyst timing and any attached trade's horizon. |
| Invalidation and signposts | Observable conditions that challenge the argument, plus supporting or weakening signposts. Do not invent thresholds or equate a price stop with thesis invalidation. |
| Counter-case and scenarios | A credible competing explanation and conditional base/upside/downside paths where defensible. No forced price targets or probabilities. |
| Evidence and monitoring scope | Supporting and conflicting source references, retained revisions, factual conflicts, proposed watched inputs and coverage gaps. Missing evidence stays unavailable. |
| Open questions | Consequential gaps and what the trader or a bounded investigation must resolve. |

Label extracted trader intent, agent proposals and external evidence separately throughout the card. A fluent proposal cannot become a sourced fact, verified causal relationship or approved intent by appearing in this structure. Headline-only research must disclose its depth and cannot imply article-level verification or a known market expectation.

The guided flow is: initial input, draft card and consequential questions, trader answers, revised immutable proposal, then exact approval preview. Preserve attributable trader inputs and links between proposals; do not replace the original prompt with a model rewrite. The trader can revise, decline or leave gaps visible. Proposed additions only enter active monitoring meaning after explicit approval. The richer contract must be reflected in versioned domain and approval hashes before these fields become governing inputs; this specification does not change the current API schema.

## User-led research before a thesis exists

A trader may begin with a question, observation or event rather than an investment conclusion. Help them define a bounded research question, examine permitted evidence and counter-evidence, and construct a candidate review card together. Ask consequential questions without requiring the trader to know the complete fundamental framework in advance.

Retain the initial question and research inputs separately from any proposed thesis. No thesis, conviction, horizon, trade or active monitoring mandate is inferred merely because research began. The result may be a tentative candidate, further questions or no defensible thesis. Search requires a named unresolved question, bounded allowance and recorded provenance/cost.

This user-initiated workflow is distinct from deferred Discovery, which proactively proposes opportunities from macro context. Copper was illustrative; the first internal example thesis and its appropriate sources will be researched jointly rather than hard-coded as a supported copper pack.

## Collaborative refinement of rough theses

| Issue | Response |
| --- | --- |
| Factual error | Show sourced correction and its consequence for the argument. A retained false premise remains labelled a factual conflict. |
| Unsupported mechanism | Ask what evidence supports the transmission path; bring counter-evidence and distinguish causal hypotheses from association. |
| Missing detail | Ask for the consequential horizon, exposure, assumptions, or invalidation criterion. Do not invent user conviction or timing. |
| Defensible disagreement | Preserve the trader's view and present competing scenarios and evidence without treating disagreement as a factual error. |

Explain the consequential gaps before offering a strengthened draft. Separate trader-provided assumptions from agent-proposed additions. Strengthening means more explicit, supported, and falsifiable; it does not mean more persuasive or greater conviction. The result can be reduced conviction or abandonment. Treat the agent's current-regime interpretation as a hypothesis with alternatives, not authority over the trader.

If the trader declines refinement, monitor approved observable elements and visibly retain unresolved gaps. The agent can investigate and challenge gaps without inventing missing intent.

## Interpretation authority and maintenance

- Every compilation or recompile creates a new immutable version; it cannot overwrite an active interpretation.
- A change to interpreted drivers, mechanisms, horizon, or invalidation signposts requires user approval before activation, even when the raw prose is unchanged.
- Equivalent source substitutions and technical repairs may activate automatically only when monitoring meaning is preserved. Record prior/new versions, reason, equivalence basis, initiator, and effective time. Reduced or uncertain coverage is visible and cannot be labelled equivalent maintenance.
- Additional agent-discovered drivers can be investigated and surfaced under `AgentAssessment` immediately. They stay separate from approved user reasoning until incorporation is explicitly approved.
- Activation records distinguish user-approved material change from audited equivalent maintenance. An assessment always references the actual active interpretation and its activation record.

## Assessment behavior

Assessments are driver-level deltas with independent thesis-impact and attached-open-trade-impact routes. State what new evidence strengthens, weakens, or complicates each driver and whether the overall thesis is unchanged, under review, or materially challenged. Explain catalyst timing and actual instrument exposure where available; a trade can be affected while the thesis stays intact. Record disagreement and feedback without suppressing contrary evidence.

Tie independent developments together against the prior macro context. Duplicate reporting does not strengthen a case; offsetting evidence can weaken it. A provisional additional transmission path stays labelled as an agent hypothesis. Investigate the links through supply, inventories, substitution, policy, expectations, and actual exposure rather than equating an alarming headline with portfolio damage.

Completed briefs provide supported facts, impact hypotheses, counter-case, horizon, uncertainty, and next signposts. Early qualified notices can be narrower when urgency is credible and impact is unresolved: state supported facts, why timely awareness matters, and what remains unknown. Do not fabricate a complete thesis path or signpost to pass a template. A cited article does not prove a portfolio consequence. Withhold surprise/priced-in claims without suitable expectation evidence.

Freeze an `AssessmentContextSnapshot` with exact thesis/interpretation activation, exposure, evidence, macro regime, knowledge, source manifest/coverage, rules, and run versions. Preserve late or superseded analysis for audit without activating it as current. Public availability and actual system receipt are separate; historical analysis may only use the versions eligible at the relevant replay cutoff. Modern-model knowledge of historical outcomes limits predictive claims even when retrieved evidence is correctly restricted.

For example, if a user claims rate cuts always lift SPX, retrieve comparable regimes and ask why rates were cut, what was expected, and what changed. A current weak BTC/tech correlation should be displayed as a windowed observation, not presented as permanent disproof of a possible shared liquidity mechanism.

## Fundamental valuation skill

Deferred from the paper pilot together with individual-equity support. When enabled, invoke at initial relevant equity thesis compilation, on request, material filing/guidance change, or threshold crossing in a linked macro assumption. Valuation must be considered when compiling supported equity theses; missing suitable inputs or a validated method produce an explicit limitation and unsupported scope, not a false target. Classify company type before choosing methods. Mature operators may use DCF plus multiples; high growth may add reverse DCF; banks, insurers, REITs, commodity producers, unprofitable firms, and holding companies require appropriate alternatives.

The LLM may propose and explain assumptions. Versioned deterministic code calculates outputs and sensitivities. Store assumption source, user overrides, method, calculation version, bear/base/bull scenarios, and changes from the prior model. Link rates, growth, margins, commodity prices, or regulation assumptions back to thesis drivers. For an option position, compare valuation horizon and catalyst timing with expiry; detailed options valuation is deferred.

## Acceptance

- A prompt produces one review card covering claim, affected assets, drivers/causal path, assumptions, catalysts, horizon, invalidation, counter-case/scenarios, evidence/coverage and gaps. Unknowns are explicit; no template manufactures missing intent or evidence.
- A trader can answer consequential questions and inspect the resulting new proposal before approving it. Prior inputs/proposals remain traceable and approval does not silently extend to later revisions.
- A trader can start with a research question and jointly develop or reject a candidate thesis without enabling proactive Discovery or automatically starting monitoring.
- Compiler preserves exact user input and requires explicit approval of text and concise interpretation before active monitoring.
- A factual error is visible before the assessment, with a source link and a path to keep the thesis as written.
- An assessment can disagree without modifying user belief; user feedback creates a new record.
- A material recompile cannot alter active monitoring intent without approval. An equivalent repair has an audited version and activation record.
- A half-formed thesis can become more explicit or less convincing without the agent inventing trader intent. A novel agent driver remains separate from the approved interpretation.
- An assessment or qualified notice uses only supported claims and states unresolved impact; its exact evidence and context remain reconstructable.
- Re-running the same valuation calculation with identical inputs produces identical results. A model change report explains which assumptions or method versions moved the range.
