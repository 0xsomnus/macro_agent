# Event ontology

## Event envelope and time

All `NormalizedEvent` revisions carry stable `event_id`, family/subtype, entities/assets, native source ID, canonical source and contract version, interpreting sources, occurrence/measurement and publication times, public availability and system receipt times, optional processing time, revision/superseded IDs, payload hash, units, quality/confirmation flags, and citation. A headline is not necessarily a distinct event; observable facts and interpretations are separate records.

- `occurred_at`: when the reported development occurred, if known.
- `observed_at`: measurement time where distinct from event occurrence. Optional `ingested_at` records persistence/normalization processing and never replaces actual receipt.
- `published_at`: the publisher's stated timestamp; it does not by itself establish public availability.
- `public_available_at`: when that revision became publicly available, with evidence, precision, and uncertainty. A restricted entitlement may instead require a separately recorded authorised availability time; never equate restricted receipt with public availability.
- `system_received_at`: first actual receipt of that revision by this desk. Preserve later receipt attempts separately.
- `known_at`: earliest durable availability of that specific record/version for system use. It is never earlier than `system_received_at` for source-derived records; normalization, derived analysis, and approval can become available later. Derived records require all dependencies to have been available to that run.

Backfills received today cannot enter yesterday's operational replay. Unknown public availability stays unknown; do not substitute the claimed publication timestamp as fact. Preserve both original and corrected vintages. Replay uses the exact then-active thesis interpretation, source manifest, evidence, context/knowledge, rules, prompts/model identifiers, and assessment versions. Historical source-availability studies are a separately labelled counterfactual, not a reconstruction of actual desk behavior. Modern model knowledge may contaminate historical reasoning even with correctly restricted input retrieval; forward observation is required to assess prospective usefulness.

## Families

| Family | Examples | Record and pilot treatment |
| --- | --- | --- |
| Scheduled macro release | CPI, NFP, FOMC decision/minutes, foreign central-bank release | Agency/central bank calendar and release vintages; pilot sources validated per driver |
| Market/position context | Price/yield/volume, curve, volatility, expectation snapshot | Permitted provider with instrument, venue, entitlement, and timestamps; availability is not assumed |
| Unexpected news | Geopolitics, sudden policy communication, disruption, security incident | Credible permitted feed/official confirmation; confirmation and impact uncertainty kept separate; core pilot |
| Commodity supply/demand | Production, shipping, inventories, policy | Relevant permitted/official sources under pilot contract; global context may matter without full commodity support |
| Source health | Outage, delay, schema drift, entitlement loss | Adapter telemetry; downgrades live coverage and cannot be treated as low event relevance |
| Corporate disclosure | Filings, earnings, guidance, issuer notice | Regulator/exchange/issuer record; individual-equity workflows deferred |
| Regulatory/legislative lifecycle | Proposal, bill action, final rule, effective date | Official process; specialised lifecycle workflow deferred, relevant news can still enter contextual analysis |

## Materiality, evidence accumulation, and briefs

`MaterialityDecision` records screening/investigation/notification disposition, reasons, input and rule/model versions, separate thesis and trade impact candidates, urgency, credibility, uncertainty, and budget/failure status. `unresolved` is distinct from a justified low disposition. Novelty alone is insufficient. Credible plausible significance or broad disruption can justify investigation outside the existing driver graph.

`DriverEvidenceWindow` links distinct developments and their revisions to a driver/horizon, preserving prior assessment, corroboration, offsetting evidence, and window/decay rules. Article duplication cannot increase independent evidence weight. A cumulative shift can produce a multi-event brief.

`IntelligenceBrief` has a stable identity for event/thesis and links attached trades plus immutable `BriefVersion` and assessment revisions. Early qualified notices, completed analysis, and source corrections update the visible brief without rewriting history. A cumulative brief links multiple contributing events. Each material user-facing revision has a stable `NotificationIntent` identity for delivery retries. Facts need support at passage/data-field level; inferred portfolio effects need explicit mechanisms, assumptions, competing explanations, and uncertainty.

## Expectations and later event studies

`ExpectedEvent` records schedule, licensed forecast/consensus source and vintage where available, market-implied expectation where permitted, regime, and pre-event window. `ReleaseObservation` preserves actual, previous, revisions, units, and all relevant timestamps. Absence of reliable expectations prevents a surprise or priced-in claim, while allowing analysis of the release itself and observed reactions.

Collect permitted timestamped inputs prospectively from the paper pilot. Historical inputs require verifiable original vintage. Statistical `EventStudy` machinery is deferred: later records must specify surprise definition, reaction windows, instrument/venue, liquidity, confounders, data availability, sample size, and regime. FOMC, CPI, and NFP remain the intended first study families. Price movement alone does not establish what was priced in or what caused the reaction.

## Later stateful legislation and regulation

Keep `RegulatoryProcess` as a future contract: jurisdiction, authority, instrument, official identifier, stage, procedural uncertainty, affected provisions, signed/published/effective dates, and linked catalysts. Stages include introduced, committee, votes, reconciliation, enacted, rulemaking, effective, implemented, with amended/stalled/vetoed/overturned branches. Official actions or visibly provisional sources establish transitions; a headline alone cannot advance a confirmed state. Future effective dates create catalysts without equating passage with implementation. The specialised graph is unscheduled in the initial pilot.

## Acceptance

- Two articles on one FOMC decision link to one event; independent later developments can accumulate against the same driver.
- A correction retains both vintages. Older analysis is visibly superseded and cannot become the current conclusion without reassessment of the new evidence.
- A receipt backfilled after the replay cutoff stays absent, even if publication predates the cutoff. Missing availability metadata remains a disclosed limit.
- Detail separates established fact, source confirmation, expectation, observed reaction, causal hypothesis, and unresolved impact.
- A credible urgent event can have an early qualified notice without a completed impact conclusion; a duplicate or non-material brief update causes no new interruption.
