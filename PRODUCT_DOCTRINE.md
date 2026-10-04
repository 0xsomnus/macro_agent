# Product doctrine

## Role and authority

1. The product is a continuous research and monitoring desk for a solo or retail discretionary macro/fundamental trader. Morning briefs, news-to-portfolio analysis, counter-analysis, evolving macro context, and collaborative thesis refinement are core functions. It offers hypotheses, challenges, evidence, uncertainty, and signposts while the trader retains judgment.
2. The user owns investment judgment, position sizing, and execution. No broker connection, order placement, autonomous trading, or implied instruction to transact in the MVP.
3. A consciously contrarian thesis is valid user state even when the system disagrees or past calls failed. Challenge the thesis with specific evidence; do not shame, grade the trader, or silently replace the view.
4. Separate `UserThesis`, `AgentAssessment`, and `SystemKnowledge`. The first is user-owned and versioned by approved amendment only. The second is the system's current interpretation. The third holds sourced observations, facts, and reviewed relationships.
5. If a premise conflicts with a verifiable fact, show the conflict first with source and timestamp. Preserve the user's words and ask whether they wish to amend. Monitoring can proceed with the conflict visibly flagged after thesis approval.
6. Preserve meaning as well as prose. Initial approval covers the exact text and a concise interpretation of drivers, horizon, and invalidation signposts. Material interpretation changes require approval; equivalent source repairs are audited technical updates. Additional agent hypotheses remain separate and may be investigated immediately.
7. Support newer traders with rough theses. Distinguish factual errors, unsupported mechanisms, missing detail, and defensible disagreement. Ask focused questions and propose improvements with introduced assumptions labelled. Strengthening means better supported, explicit, and falsifiable, and may reduce conviction. Do not mistake fluent prose or a confident regime assessment for evidence.

## Epistemic contract

Every substantive assessment contains: claim, time horizon, supporting passages or data fields, causal path or an explicit statement that only association is known, counter-case, uncertainty, expectations or their absence, and observable signposts. Evidence links must support the actual factual claim. Keep facts, inference, user belief, and model output visually distinct. A credible urgent event may first produce a narrower qualified notice stating what is established, why attention is warranted, and which impacts remain unresolved; subsequent analysis updates the same brief.

Use scenarios rather than one price target. A historical association is never a causal edge by default. Correlations are rolling, sample-dependent, and regime-conditioned; report window, data vintage, sample size, and uncertainty. A surprising market reaction becomes an observation for review, not an automatic rewrite of the causal model.

## Operating discipline

- Compile a canonical source manifest for each thesis and asset. Cheap deterministic monitoring runs before expensive reasoning; broad search is escalation.
- Capture source events without the LLM. Broad relevance screening can use models, but uncertain relevance or classifier failure cannot silently become non-material. Thesis impact and attached-trade impact are independent escalation routes. Novelty alone is insufficient; credible potential severity or broad disruption can justify investigation outside the existing driver map.
- Separate bounded investigation from interruption. Accumulate distinct developments against a driver in macro context, include offsetting evidence, and deduplicate repeated reporting. Update a stable brief and interrupt again only for a material change. Narrow instrument coverage does not restrict relevant global context to those markets' geography.
- Assemble only the context needed for the current decision. Context engineering decides what a node sees; loop engineering bounds iteration; execution graph engineering defines routes, permissions, joins, and stops. The durable knowledge and thesis graph is a separate domain concern.
- Invoke specialist research, skeptic, and valuation workers only on demand. Record why each was invoked and its cost.
- Keep basic decision/outcome records and immutable assessment history in the pilot. Defer automated postmortems, candidate-learning generation or retrieval, regime evidence accumulation, and promotion workflows. Later learning begins offline and must improve fresh-case results before production adoption. Canonical knowledge corrections require a named human reviewer in the pilot; current evidence may update assessments without creating a learned general rule. No online model-weight training.
- Shared observations and reusable analysis may feed private interpretation, subject to entitlement boundaries. Shared model hypotheses are not canonical truth. Measure acquisition, shared analysis, and private work separately. Internal configured BYOK enables tests; adaptive routing and customer billing are not prerequisites.
- Make absent, delayed, disputed, or unlicensed data visible. Do not turn missing evidence into a confident conclusion.

## Review checks

- Given a thesis with a wrong policy-rate premise, the original thesis text remains byte-for-byte intact and a sourced conflict appears before the agent assessment.
- Given a plausible contrarian thesis, the user can approve monitoring while preserving the original claim and seeing the counter-case.
- Given an alert, a reviewer can trace every important claim to source, observation time, model or rule version, and the relevant thesis driver.
- An unfamiliar severe event enters bounded investigation, while mere unfamiliarity cannot bypass interruption criteria. Several independently relevant developments can jointly become material.
- Approved meaning stays fixed when additional agent hypotheses or routine source repairs are introduced. Public availability and system receipt are separately traceable.
