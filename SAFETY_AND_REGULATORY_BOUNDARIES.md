# Safety and regulatory boundaries

Updated 2026-10-02. Internal research and the external pilot retain these authority and evidence boundaries.

This is a product control document, not a legal opinion. Product form, audience, jurisdiction, compensation, personalization, and content can change regulatory treatment. A disclaimer or lack of trade execution alone does not settle that question. U.S. SEC guidance describes investment-adviser analysis as potentially covering compensated analyses or recommendations about securities; obtain written specialist advice before public launch or enabling personalized recommendation features. See [SEC adviser definition guidance](https://www.sec.gov/files/divisions/investment/iaregulation/memoia.htm).

## MVP permissions

Allowed: continuously monitor user-supplied theses and attached open trades; provide morning briefs, analysis and counter-analysis; summarize sourced facts; present conditional scenarios, sensitivities, and research questions; preserve basic decisions/outcomes; and propose thesis refinements for approval. The system may explain that a thesis is weakened or a contract's horizon mismatches its catalyst, with evidence and uncertainty. Supporting a novice means making an argument better supported, explicit, and falsifiable; a useful result can reduce conviction or retire an idea.

Not allowed in MVP: place or route orders, access brokerage credentials, allocate capital, calculate personalized position sizes, provide a one-click trade recommendation, silently change a user thesis, imply certainty, conceal major source gaps, or present a hypothetical valuation as a guaranteed fair value. Hedge ideas and Discovery candidates remain deferred until product and legal review.

## Controls in product and system

- User-facing output labels facts, user beliefs, model assumptions, inferences, and data gaps. Every material hypothesis includes evidence, counter-case, uncertainty, signposts, and horizon. Important factual claims link to the supporting passage or data field; a citation alone does not establish support for a claim or its causal interpretation.
- A credible urgent event can produce a narrower notice while portfolio impact is unresolved. State what is established, why investigation merits attention, and what remains unknown; withhold unsupported conclusions and update the same brief as evidence develops. Unknown expectations cannot become a claim about surprise or priced-in conditions.
- Distinguish factual error, unsupported mechanism, missing detail, and defensible disagreement. Present sourced conflicts before interpretation; preserved user wording does not make a false premise an established fact. Proposals identify which assumptions came from the user and which from the agent.
- Approval covers both exact thesis text and its concise compiled interpretation. Changes to drivers, horizon, or invalidation signposts need explicit approval; equivalent source repairs are audited. Additional investigated drivers remain agent hypotheses until adopted by the user.
- Audit full provenance, model/rule versions, user approvals, corrections, and visible conflicts. Preserve public availability, actual system receipt, and durable known-at times separately, alongside the exact approved interpretation and assessment inputs.
- Enforce permissions at service boundaries. Neither runtime workers nor source packs can call trading APIs or promote canonical knowledge.
- Apply source licence and entitlement checks before storage, redistribution, shared-analysis reuse, model processing, and display. Shared evidence or analysis cannot contain private theses, exposures, or user-specific licensed content accessible to other users. User-owned Bloomberg access is a future entitlement requirement subject to contract review.
- Protect portfolio and thesis data with access control, encrypted secrets, retention rules, and provider/model data-flow review.
- Internal BYOK uses scoped configured credentials without logging secrets. Customer-facing BYOK is deferred; external pilots use operated credentials. Neither a cheaper provider nor a user's own key establishes permission to process source content.
- Dated coverage contracts state watched drivers, source freshness, exclusions, current failures, and contextual limits. Narrow supported instruments retain global contextual monitoring without a claim of comprehensive coverage of every economy or event.
- Automated outcome learning is deferred, including provisional-learning retrieval and promotion. Current evidence can change the agent assessment; canonical relationship corrections need a named human reviewer during the pilot. Shared macro interpretation is versioned, disputable agent context, not automatic canonical truth.
- Prepare jurisdiction-aware feature flags and marketing review before public release. Avoid claims such as “buy,” “sell,” “guaranteed alpha,” or exhaustive coverage without substantiation.

## Review gates

Before public launch, counsel should assess at least the actual target jurisdictions, U.S. investment-adviser and CFTC/CTA perimeter where relevant, UK/EU rules if served, marketing and data rights, and the status of any personalized hedge or Discovery feature. Congressional-trading monitoring is separately blocked pending legal and data-rights review. Record written decisions and translate them into feature gates; do not infer legality from this document.

## Acceptance

- A generated output with an unsupported trade instruction is blocked or rewritten into a conditional research assessment and logged.
- A permitted source becoming unlicensed disables its adapter and shows a coverage gap.
- A simulated worker cannot mutate `UserThesis`, promote a graph edge, or submit an order.
- A novice's draft can be strengthened or rejected through sourced questions and approved refinement, without silently increasing conviction or substituting the agent's assumptions.
- A missing model, unavailable feed, or exhausted budget is disclosed as an operational/coverage limit, never reported as proof that an event is irrelevant.
