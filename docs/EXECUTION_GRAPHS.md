# Execution graphs

Nodes are independently testable responsibilities or authority boundaries. Explicit transitions include failure, timeout, unresolved evidence, and exhaustion. Add a node only for a distinct permission, budget, validation, or route. Capture/scheduling never depend on model availability; broad screening and interpretation may use bounded models.

## Common envelope

Every node records `run_id`, graph/node versions, exact input IDs/versions, allowed tools, deterministic rule or provider/model identifier, individual and aggregate budget, start/end times, output schema, stop reason, retries, and next-edge predicate. Joins wait only for invoked branches. `ContextManifest` within `AssessmentContextSnapshot` references the exact approved interpretation, manifest, event/evidence revisions, macro/knowledge versions, position snapshot, prompt, and rule/model metadata used. Replay cannot substitute the latest version.

## G1: thesis compilation and refinement

```text
draft_received -> parse -> verify_facts -> identify_gaps -> clarify_or_propose
  -> compile_drivers -> compile_manifest -> challenge_and_quality -> user_review
user_review: approve_text_and_interpretation -> active_thesis
             edit -> new_draft
             keep_flagged -> approved_active_thesis_with_unresolved_limits
failure: identity/source gap -> user_review with coverage limit
```

Distinguish factual error, unsupported mechanism, missing detail, and defensible disagreement. Proposals label user assumptions versus agent additions. Approval covers exact user text and concise interpretation of drivers, horizon, and signposts. Changes to interpretation semantics require approval; equivalent source/technical repairs can proceed with an audit trail. Additional agent hypotheses can be investigated without rewriting the trader's reasoning. Declined refinement leaves unobservable elements explicitly unresolved.

## G2: continuous monitoring and event analysis

```text
scheduled_or_feed_tick -> fetch -> validate -> persist_receipt
  -> normalize_revision_and_dedupe -> broad_screen -> driver_evidence_accumulation
screen/accumulation: justified_low -> audit_only
                     possible_relevance -> bounded_investigation
                     credible_severe_unknown -> bounded_investigation
                     unresolved_or_classifier_failure -> unresolved_queue + retry
investigation: sufficient_for_qualified_analysis -> primary_analysis
               named_gap -> bounded_research
               consequential_uncertainty -> on_demand_skeptic
credible_urgent_relevance + unresolved_impact -> early_qualified_notice
analysis_or_early_notice -> synthesize -> evidence_gate
  -> atomic_result_and_notification_intent -> delivery_worker
  -> current_brief + basic_outcome_record
failure: source unavailable -> live_coverage_downgrade + retry
         model unavailable -> preserve/unresolved + retry
         exhausted budget -> visible_partial_or_queue
```

Broad screening retains potential relevance before deciding interruption. Thesis and trade impacts are independent escalation routes. Credible severe disruption or a plausible significant exposure path can enter investigation outside existing graph edges. Novelty alone cannot escalate. Unresolved routing/failure cannot become low. Independent developments accumulate with offsets; duplicated articles do not add signal weight. Threshold values/windows remain evaluation hypotheses, not hidden defaults.

Deterministic capture, known-route urgency, source health, and preservation continue without models. Where credible potential urgency and relevance can be established, the desk may publish a narrow evidence notice with unresolved effect; no fallback fabricates portfolio analysis. The evidence gate checks important facts against exact passages/fields, keeps consequences as qualified hypotheses, and requires counter-case, uncertainty, horizon, and signposts where supported. Missing inputs narrow the claim. Missing expectations prevent priced-in/surprise conclusions.

## Persistence, ordering, and delivery contract

Save any immutable `AgentAssessment` produced, its `BriefVersion`, and `NotificationIntent` in one transaction. An early unresolved notice may have a qualified brief without a completed impact assessment. A leased/idempotent outbox worker retries pending delivery, records acknowledgements, and exposes exhaustion/dead-letter failure. A crash after result persistence cannot lose the notification intent. A stable intent identity dedupes repeated attempts where the channel supports idempotency; channels without it have a disclosed residual duplicate risk rather than an exactly-once promise.

Maintain one evolving event/thesis `IntelligenceBrief` covering attached trades. Early notice, completion, and source corrections update it; only material updates create new interruption intents. Multi-event cumulative briefs reference all contributing revisions. Source correction marks dependent analysis superseded. Before committing a current assessment, compare its inputs with active evidence and approved interpretation versions; a stale completion remains history and queues reassessment instead of replacing the current view.

## G3: targeted search

`existing_evidence -> permitted_interpretation -> named_missing_question -> budget_check -> targeted_search -> source_support_verification -> evidence_or_unresolved`. Searches have stated gaps, permissions, cost, and stops. Search is never the recurring news detector and cannot create trusted facts without verification.

## G4: valuation, defined but deferred

`trigger -> classify_business -> supported_method -> source_inputs -> explicit_assumptions -> deterministic_calculation -> sensitivity -> validation -> publish_version_or_limited_result`. Individual equities and automated valuation are absent from the initial pilot; do not schedule this graph. Retain method-specific support, stale-input handling, deterministic arithmetic, and user-override versioning for later reviewed expansion.

## G5: basic records now; outcome learning deferred

Pilot: `assessment_or_user_decision -> immutable_record -> due_signpost/outcome_observation -> evaluation_record`. Preserve evidence and basic decision/outcome records without deriving lessons for production retrieval.

Deferred offline branch: `postmortem -> candidate_learning -> fresh_case_evaluation_against_existing_desk -> governance_review`. Automated postmortems, lesson generation/retrieval, evidence-accumulation for learned rules, and promotion workflows remain unscheduled. Production use requires demonstrated improvement on fresh cases and later approval. Human-reviewed sourced knowledge corrections remain possible; canonical relationship changes require a named human reviewer in the pilot and a rationale/version trail. No outcome automatically rewrites an edge, user thesis, or model weights.

## G6: regulatory lifecycle, defined but deferred

`official_action -> validate_process_id -> transition_guard -> new_state_version -> future_catalyst -> route_to_theses`. The specialised workflow is unscheduled in the pilot. Relevant policy news can still enter G2 as context; an interpretive headline cannot advance a confirmed official lifecycle state.

## G7: scheduled desk brief

`brief_tick -> gather_permitted_events_and_open_work -> compare_driver/macro_deltas -> prioritise_thesis_and_trade_impacts -> qualified_synthesis -> evidence_gate -> atomic_brief_and_delivery_intent`. A morning brief includes developing cumulative changes, counter-analysis, upcoming catalysts, unresolved investigations, and current coverage limits. It reuses events and assessments, not a new unbounded web search. Context reuse respects entitlements; private trader data never enters shared analysis.

## Reserved Discovery branch

`macro_state -> driver_changes -> asset_mapping -> research_candidates -> user_review` is future and separately gated. Do not schedule or expose it in the pilot. Reuse normalized evidence and authority contracts when it is approved.

## Graph verification

Verify valid/invalid transitions, duplicates, late receipts/revisions, source/model failures, exhausted individual/aggregate budgets, approval gates, and receipt-time replay with a fake clock. Include unfamiliar severe events, classifier failure, cumulative independent/offsetting developments, exact fact-support failure, crash between persistence and delivery, lease retry, and stale concurrent completion. No branch can amend approved thesis semantics or canonical relationships without its required review. Historical reasoning evaluation alone cannot establish foresight.
