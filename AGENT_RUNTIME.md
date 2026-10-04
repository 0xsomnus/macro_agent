# Agent runtime

Updated 2026-10-02. API, monitoring, and research workers use Python under [ADR 014](ADR/014-python-backend-and-typescript-ui.md); the web UI uses TypeScript. Specific worker/runtime libraries remain open. The initial desk uses configured provider/model roles, not a commercial routing engine.

## Roles and permissions

The orchestrator routes typed inputs through approved execution graphs. It does not invent worker roles or bypass gates. The primary analyst interprets events, portfolio exposure, accumulated evidence, and macro context. An on-demand researcher resolves a named material evidence gap; an on-demand skeptic tests consequential conclusions and missing counter-cases. The morning brief synthesizes current evidence and assessment changes without manufacturing new certainty.

A later valuation worker selects supported methods and runs deterministic calculators. Valuation, Discovery, automated postmortems, outcome-derived learning retrieval, and learned-edge promotion are inactive in the pilot. No worker can approve a thesis amendment or substantive interpretation change, promote canonical knowledge, or execute a trade.

## Three engineering disciplines

| Discipline | Responsibility | Observable output |
| --- | --- | --- |
| Context engineering | Select the smallest sufficient evidence, approved interpretation, exposure, history, and macro hypotheses for this node. Include counter-evidence, not merely support for the trader's view. | Immutable context snapshot, source IDs/versions, and context budget. |
| Loop engineering | Bound repeated screening, research, critique, model/tool calls, and retries. | Iteration count, costs, stop reason, unresolved questions. |
| Execution graph engineering | Define node state, transitions, branches, joins, authority, publication guards, and retry boundaries. | Trace with input/output versions and route reasons. |

The knowledge/thesis graph is domain data retrieved by the runtime, distinct from its execution graph. Shared macro hypotheses are also separate from canonical knowledge and the trader's approved interpretation.

## Capture, screening, and urgency

Deterministic capture, source-health monitoring, conservative routing, and delivery continue during model outages. Broad model screening may detect relevance beyond compiled drivers. Novelty alone does not trigger escalation: unfamiliar developments need credible evidence plus a plausible route to significant exposure or credible broad disruption. Unknown relevance receives a bounded investigation or a visible unresolved state, never silent dismissal.

Thesis impact and attached-trade impact are independent escalation routes. Independently sourced developments accumulate against a driver with offsetting evidence and prior macro context; duplicate reporting of one event does not increase signal strength. Investigation is separate from notification. Credible urgency can justify an early factual notice with unresolved impact; subsequent analysis updates the same brief, and further interruption requires material change.

## Budgets and stopping rules

Configure per-investigation limits for model calls, tools/search, elapsed time, context size, and spend. Also bound aggregate work over time across events, theses, users, and shared tasks. A per-run cap alone cannot contain fan-out. Defaults are measured hypotheses, not accepted numeric thresholds.

Every search names its unresolved material question, trigger, permission, and budget. Stop when evidence supports a qualified result, the budget is exhausted, conflicts remain unresolved, or a required user/reviewer action is pending. Budget exhaustion is an operational limit; it cannot turn uncertainty into a negative materiality result. Prioritize urgent exposure, publish only supported partial results, and visibly queue or mark deeper work as deferred/failed. Capture and critical qualified notices must have an explicitly reserved operational path.

Use deterministic work where sufficient, broad economical screening where useful, and deeper analysis for material or unresolved cases. Invoke skepticism for high stakes, conflicting evidence, or consequential conclusions. Record why it ran and whether it changed synthesis. Evidence validation checks that each important factual claim is supported by its passage/data field; the existence of a citation alone does not validate a claim or its portfolio inference.

## Providers and cost attribution

Internal researchers can use existing scoped BYOK configuration immediately. Provider and model are explicitly configured per role behind replaceable adapters; never log secrets. External pilots use operated credentials. Adaptive model routing, customer key management, public BYOK, and subscription credits are not prerequisites for testing.

Record model/provider versions, configuration, prompts or hashes, evidence IDs, request IDs, tool calls, latency, token/usage units, retry costs, and charged or estimated spend. Distinguish estimates from billed values. Attribute work to shared acquisition/monitoring, shared analysis, or private context/investigation. Evaluate cost per useful assessment, including failures and retries, rather than advertised model price alone.

Shared evidence capture is settled. Shared versus independent model-generated context construction remains a pilot comparison. Reusable event analysis can reduce measured duplication, subject to entitlements and privacy. If shared macro context is introduced, private analysts can challenge its versioned hypotheses. Context should update incrementally from new evidence, rather than reconstruct the entire macro environment for every event.

Subscription allocation for shared work and private premium investigation allowances remain commercial modelling questions. No percentage tax, BYOK platform fee, or customer credit formula is selected by these contracts.

## Runtime acceptance

- A clearly non-material event invokes no specialist. Unknown or urgent unfamiliar events take the logged investigation/unresolved route, including when a model is unavailable.
- Source/model/budget failure cannot silently discard a captured event; queued work and supported early notices remain visible.
- An assessment snapshot identifies the approved interpretation, evidence revisions, exposure, macro context, graph, prompts, and model configuration actually used.
- A stale run cannot become current after an input revision race. Assessment persistence and notification intent share a transaction; delivery retries retain identity.
- A worker cannot fetch unlicensed content, leak private inputs into shared output, activate a substantive interpretation change, promote an edge, or call broker APIs.
- Exhausted loops terminate with a stop reason and explicit uncertainty. No automated outcome-learning stage runs in the pilot.
