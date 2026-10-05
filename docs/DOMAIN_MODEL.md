# Domain model

Implementation update, 2026-10-05: [PAPER_POSITIONS.md](PAPER_POSITIONS.md) specifies immutable manual declarations with instrument, direction, optional quantity/unit and horizon, reviewed approval provenance, explicit mapping gaps and terminal closure. Positions belong to a thesis aggregate while preserving the approval reviewed for each version. The full book includes closed records with status visible; it never silently truncates open exposure. Mapping remains `user_declared_unverified`. Quantity is a declaration, not P&L or risk arithmetic.

`ThesisBriefBinding` records pending/ready admission state for protected synthetic publication. Immutable `ContextAdmission` stores exact resolved approved text, interpretation, approval and complete exposure content with governing pins. Approval/exposure changes clear obsolete current output and pending notices atomically. Its committed-input observation witness is distinct from command/preparation times and exact durable admission commit time. These implementation records do not collapse the three truth stores or establish permitted live coverage.

## Three kinds of state

| Aggregate | Owner | Mutation rule |
| --- | --- | --- |
| `UserThesis` | User | Append-only versions. Only explicit user approval makes a proposed amendment current. Original prose and rationale remain available. |
| `AgentAssessment` | System | New immutable assessment per material evidence change or user request. It may agree, disagree, or mark unresolved. Agent-proposed drivers and regime interpretations remain labelled as hypotheses. It never edits `UserThesis` or silently changes its active interpretation. |
| `SystemKnowledge` | Reviewed evidence process | Sourced facts/observations plus versioned relationships. Candidate canonical edges require review before promotion. |

## Core entities

- `User`, `PortfolioContext`, `PositionContext`, `WatchlistEntry`: ownership and versioned exposure context, without execution privileges. Actual instrument, direction, horizon, and attached thesis are captured where supplied; missing exposure inputs remain explicit.
- `Asset`, `Instrument`, `Underlying`, `Economy`, `Currency`, `Issuer`: use underlying and economy packs to avoid one source adapter per ticker or derivative. Instrument IDs carry exchange, venue, expiry, currency, and symbol aliases.
- `UserThesisVersion`: exact text, user-supplied scope/horizon, approved status, created/approved times, parent version, and explicit contrarian flag if selected. A contrarian flag cannot erase a factual conflict.
- `ThesisAmendmentProposal`, `ThesisRefinementIssue`: proposed prose or intent changes and separately typed factual error, unsupported mechanism, missing detail, or defensible disagreement. Record trader input versus agent additions and disposition.
- `CompiledThesisVersion`: immutable machine interpretation linked to a particular user version, containing `Claim`, `Driver`, `Assumption`, `Catalyst`, `InvalidationSignpost`, `Scenario`, `FactualConflict`, and `SourceManifestVersion`. Recompilation creates a new draft version; it never substitutes for user prose.
- `CompiledThesisActivation`: append-only activation record, prior/new interpretation IDs, effective time, actor, and authority (`user_approval` or `equivalent_maintenance`). Material meaning changes require user approval; maintenance records an equivalence basis and audit reason.
- `AgentAssessment`: stance and confidence *in the analysis*, independent thesis/trade impact, driver deltas, evidence, counter-case, alternatives, unknowns, signposts, prior assessment reference, and run metadata. Early unresolved notices need not pretend to be complete assessments.
- `AssessmentContextSnapshot`: immutable IDs/versions of thesis text, active compiled interpretation and activation, portfolio/position context, evidence/event revisions, regime interpretation, knowledge, manifest, coverage, expectation vintage if available, rules, prompt/model, entitlements, and budget used. Preserve chosen context content or lawful reproducible references and hashes.
- `Source`, `SourcePack`, `SourceManifest`, `RawReceipt`, `NormalizedEvent`, `EventRevision`, `Evidence`: provenance, licensing/entitlement, original versus revised content, and temporal eligibility.
- `SourceContractVersion`: validated source content, timeliness, permitted processing/display/retention, entitlements, and failure behavior. A feature cannot claim inputs beyond its validated contracts.
- `MaterialityDecision`, `DriverEvidenceWindow`: auditable screening/investigation/notification dispositions and a bounded set of independent evidence assessed against a driver and prior macro context. Keep thesis impact, trade impact, credible urgency, unresolved relevance, offsets, and novelty distinct. Duplicate reports do not count as independent developments.
- `CoverageContractVersion`: dated thesis/exposure coverage promise with watched drivers, sources/event families, freshness targets, licensing/use scope, exclusions, and current health references. Distinguish supported instruments from global contextual monitoring.
- `ClaimEvidenceLink`: factual claim and exact supporting passage/data field, revision, verification disposition, and limitations. Hypotheses separately link assumptions, mechanisms, support, counter-evidence, and uncertainty; a citation does not establish entailment.
- `IntelligenceBrief`, `BriefVersion`, `NotificationIntent`: stable event/thesis brief identity, immutable evolving content, and durable notification request. An early notice, completed analysis, and corrections update one brief; further interruption requires material change. A cumulative case links multiple independent events instead of treating duplicate articles as additional evidence.
- `RelationshipEdge`: typed, directed, versioned edge with causal/association distinction, mechanism, sign, regime, horizon, confidence, source support, reviewer and validity interval.
- `CorrelationObservation`: rolling estimate with series definition, window, sampling, regime, missing-data policy, and known-at timestamp. It is not a causal edge.
- `MacroContextVersion`: timestamped sourced observations, competing regime interpretations, unknowns, and references to reviewed relationships. Context updates from current evidence are distinct from outcome-derived rule learning; shared interpretations are hypotheses that private analysis can challenge.
- `ContextManifest`: the exact permitted records/versions selected for a node or assessment, selection reasons, exclusions, temporal cutoff, and entitlement constraints. It supports the immutable `AssessmentContextSnapshot` without implying all available data was used.
- `ExpectedEvent`, `OutcomeObservation`, `DecisionJournalEntry`, `GraphChangeProposal`, `ReviewDecision`: expected releases where data permits, basic outcome/decision records, and human-reviewed sourced knowledge corrections. The pilot names an authorized human reviewer for canonical changes.
- Deferred entities: `EventStudy`, automated `Postmortem`, `CandidateLearning`, and outcome-derived promotion/retrieval workflows. Preserve prospective records now; these workflows require later offline validation on fresh cases.
- Deferred `ValuationModelVersion`: method, company classification, assumption provenance, deterministic calculation version, scenario outputs, sensitivities, and linked thesis drivers. Individual equities and automated valuation are outside the initial pilot.

## Time and replay contract

- `occurred_at`/`observed_at` describe the event or measurement. `published_at` is the source's claimed publication time for that exact revision, not proof of receipt or public availability.
- `public_available_at` is the earliest evidenced public availability of that revision. If unavailable or uncertain, record the uncertainty; do not invent a historical instant from ingestion time.
- `system_received_at` is the actual successful receipt by this desk. `ingested_at`, if used for persistence/normalization, is an operational processing timestamp and cannot replace receipt.
- `known_at` is the earliest durable availability of that exact record/version for system use. Source-derived records cannot precede actual receipt; normalized, derived, and approved records also respect required processing, completion, and activation. For raw receipts it can equal receipt. Evidence available through restricted entitlements carries those restrictions separately.
- Operational replay uses `known_at` and the activations valid at the cutoff, including actual received vintages and then-approved thesis interpretation. A late historical backfill stays unavailable to an earlier operational replay.
- A separately labelled public-information study may use evidenced `public_available_at` vintages, but cannot claim the live desk had them. Both modes preserve amendments, approvals, exposures, source/coverage, knowledge, and macro-context versions.
- Historical fixtures verify deterministic capture, authority, and temporal rules. Retrieved point-in-time evidence does not remove knowledge of historical outcomes from a modern model; genuine forward usefulness requires prospective observation.

## Invariants

1. No write path from `AgentAssessment` or `SystemKnowledge` to an approved `UserThesisVersion` or material change of active interpretation. Proposed amendments and recompilations remain separate until approved; equivalent maintenance has explicit limited authority.
2. Facts, forecasts, user assumptions, estimates, inferred relationships, and observed correlations carry different types and source labels.
3. Every event/evidence revision preserves public availability, actual receipt, usable known-at time, and uncertainty where timestamps cannot be established. Corrections preserve predecessors; backfills cannot retroactively become operational knowledge.
4. Every relationship edge states its scope and regime. Edges cannot be promoted or changed solely by an automatic threshold.
5. Every assessment freezes its exact context snapshot. Currentness is distinct from completion time; later-finishing stale work cannot replace analysis of newer evidence. Brief revisions preserve history.
6. Published assessment/brief state and its pending `NotificationIntent` commit together. Delivery retries are idempotent where the channel supports stable identities; unresolved delivery failure remains visible.
7. Missing expectation evidence cannot support surprise or priced-in claims. Unknown relevance and exhausted budgets cannot silently become non-relevance. Early notices may publish narrower supported claims while investigation remains unresolved.

## Acceptance examples

- Updating an assessment for the same thesis leaves the approved user text and version unchanged.
- A late-revised CPI value produces a new event revision and a new assessment if material; operational replay before actual system usability sees only the original received vintage, even if a public-information study has a different cutoff.
- A BTC/NDX rolling correlation observation may be near zero while a reviewed hypothesis about a shared liquidity driver remains separately represented and qualified.
- Recompiling gold's primary driver from real yields to central-bank demand creates a pending material interpretation change. The agent may independently investigate demand, but cannot change approved monitoring intent without approval.
- A DXY thesis and its actual contract/product exposure have separate identities. A global event can be considered contextually without representing full coverage of its jurisdiction.
- A retained factual error remains visibly false against the cited source; a missing horizon remains unresolved. Refinement can lower conviction without rewriting the trader's words.
