# Monitoring and sources

## Continuous desk contract

Continuous permitted news monitoring, scheduled releases, morning briefs, analysis, and counter-analysis form the initial desk experience. A calendar-only implementation does not satisfy the pilot. The desk connects developments to approved theses and attached open trades, explains competing transmission hypotheses, and proposes revisions for user approval.

Capture is independent of models. Interpretation may use bounded model calls. Macro context remains global even when supported instruments are narrow: overseas policy, supply disruption, and geopolitical developments can affect pilot exposures. Contextual investigation does not imply comprehensive monitoring of every country or asset.

## Source hierarchy and contracts

1. Canonical issuer, agency, regulator, central bank, exchange, or official process for observable facts.
2. Permitted market/consensus providers for price, expectations, and reactions, with entitlement and vintage recorded.
3. Reputable licensed or otherwise permitted news feeds for continuous unexpected-event detection and interpretation.
4. Targeted web search for a named unresolved material question. Search output remains provisional until verified; broad search is not the watcher.

Each `SourceContractVersion` specifies covered content/event families, acquisition method, timeliness and freshness targets, rate limits, ownership, permitted storage/model processing/redistribution, entitlement boundaries, known exclusions, failure behavior, and fallback. Validate the contract before depending on the capability. Technical access establishes neither completeness nor permission. News coverage is a pilot gate; historical consensus is a gate for later statistical event studies.

At thesis compilation, create a versioned `SourceManifest` per driver and exposure: source IDs and contract versions, endpoint/feed, event types, cadence/calendar, freshness target, expected latency, change detector, threshold candidate, fallback, rights status, owner, and health. Initial activation includes approval of the interpretation. Changes to drivers, horizons, or signposts require user approval. Equivalent source replacement and technical repairs may happen automatically with an audit trail and coverage disclosure; they cannot silently change the approved interpretation.

## Screening, investigation, and interruption

- **Tier 0, independent capture:** schedules and subscriptions, conditional fetch, hashes/native IDs, lawful raw receipt retention, normalization, identity resolution, dedupe, revision tracking, source health, and deterministic urgency rules. No model call is required for acquisition or preservation.
- **Tier 1, broad screening:** deterministic routes plus bounded low-cost classification where useful. Record input versions, reason/features, route, threshold/model version, sensitivity, and audit sample. Possible relevance is separate from the threshold for interrupting the user. Failed classification, an unknown entity, or uncertain relevance enters an unresolved queue rather than becoming `low`.
- **Tier 2, investigation and synthesis:** evaluate thesis impact and open-trade impact independently; either may justify escalation. Examine mechanism, horizon, instrument exposure, counter-case, and missing inputs. Use specialists/search only for named gaps and within individual and aggregate budgets.

An unfamiliar event can enter bounded investigation when credible evidence supports a plausible significant exposure path or potentially severe broad disruption, including paths absent from the existing driver graph. Novelty alone triggers neither escalation nor notification. Investigation does not require a user interruption.

A credible, potentially urgent development with unresolved portfolio effect may generate an early qualified notice: established facts, provisional relevance, uncertainty, and the next question. Later analysis updates the same brief. Supported facts require exact passage/data-field support checks. Consequences and causal links remain qualified hypotheses. Missing expectation data blocks claims about surprise or what was priced in, while allowing narrower analysis of facts, plausible mechanisms, and observed reactions.

Maintain `DriverEvidenceWindow` records for distinct developments over configurable windows. Compare accumulated evidence with the previous macro/driver assessment, including offsetting evidence and decay/horizon assumptions. Multiple reports of one event add corroboration or interpretation, not independent signal weight. A sequence may trigger a cumulative brief even when no single event crosses the interruption threshold.

Per-thesis sensitivity changes triage, never raw capture. Coverage failures and exhausted budgets are operational states, not evidence of irrelevance. Urgent qualified notices remain possible without completed model analysis; deeper work can queue with a visible status.

## Shared evidence and cost

Acquire each source receipt once and fan out through entitlement-aware routes. Shared facts and reusable event analysis feed private thesis/exposure analysis; private trader context cannot leak into shared work. Shared interpretations remain versioned hypotheses that the private analyst can challenge.

During internal research, existing BYOK credentials can fund either shared or private experiments through the same provider-neutral adapter. Customer-facing BYOK is deferred from external pilots. No vendor or automated routing engine is selected. Record shared acquisition/analysis and private context/investigation costs separately, with individual and aggregate limits. The extent of shared model-generated macro context and subscription cost allocation remain measurement-driven decisions.

## Pilot and expansion coverage

| Paper pilot supported targets, after source-contract validation | Later expansion | Context or default unsupported |
| --- | --- | --- |
| ES, NQ, XAU, DXY-linked theses and trades, EUR/USD, USD/JPY, USD/CNH | GBP/USD; additional currencies, rates, commodities, crypto; individual U.S. equities with supported valuation | Global developments relevant to pilot drivers remain contextual; unvalidated instruments have no supported-coverage promise |

DXY is both shared macro context and a direct thesis/trade exposure. Identify the actual traded instrument separately from the index. Underlying packs can share catalysts across valid futures/ETF/CFD mappings, but venue, expiry, basis, and instrument-specific notices need explicit contracts. Selecting USD/CNH serves China-related macro exposure; do not claim it is a separately verified top-three retail spot ranking.

The broader destination includes USD, EUR, JPY, GBP, CHF, AUD, CAD, NZD, CNH; SPX/NDX families; U.S. rates; gold, WTI, copper, silver; BTC/ETH; and dynamic top-100 U.S. equities selected using market cap and dollar volume. Exact equity membership methodology, provider, lookback, liquidity floor, corporate-action handling, refresh versions, and tie-breakers remain open. Do not interpret this destination as pilot support. INR and natural gas can remain context until their packs are validated.

## Inspectable coverage

Use a dated `CoverageContractVersion` per thesis driver and exposure, referencing the source manifest: covered event families, sources, freshness targets, exclusions, unresolved observability, and last verification. Show supported/partial/unsupported scope together with live healthy/degraded/unavailable status. Provider outage, entitlement loss, delayed receipt, or missing driver data visibly downgrades current coverage.

Retire unqualified `fully monitored` labels. Passing specified pack tests establishes coverage against that contract, not exhaustive global awareness. Context-only investigation and future user packs must be visibly distinguished from validated supported monitoring.

## User packs and licensing

Declarative user packs are deferred from the initial pilot, with public community sharing later still. Future packs identify assets, official references, permitted feeds, event types, cadence, expected units, and proposed driver mappings. Activation requires schema, source identity, safety, rights, rate-limit, and coverage review. Submissions cannot create trusted facts or canonical graph edges directly.

Keep provider contracts replaceable. Bloomberg Desktop/API, server redistribution, storage, and third-party model processing require contract-specific confirmation. OpenBB is a routing tool, not a data licence. Do not make Yahoo/yfinance a production promise without rights review. Retain a rights matrix per provider, user entitlement, and deployment context.

Official source examples to validate: [Federal Reserve FOMC releases](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm), [BLS schedules](https://www.bls.gov/schedule/), [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [Congress.gov API](https://api.congress.gov/), and [EIA open data](https://www.eia.gov/opendata/). These illustrate source classes; SEC and regulatory lifecycles are future integrations, and links do not establish production SLAs or data rights.

## Acceptance

- Scheduled releases and unexpected permitted news both reach relevant pilot theses/trades. An unfamiliar credible severe disruption can enter investigation outside existing graph paths; novelty alone cannot interrupt.
- Uncertain/failed classification stays unresolved and recoverable. Quiet feeds do not require research-model calls. Capture and qualified urgent notices continue when models are unavailable.
- Duplicate reporting does not inflate accumulated evidence. Independent gradual developments and offsetting evidence are compared against prior macro context.
- One event/thesis brief evolves across early notice, completed analysis, and correction; only material changes generate a new interruption. Cumulative briefs retain links to all contributing events.
- Important factual claims pass exact source support checks; unsupported consequences become unresolved questions. Missing expectations prevent priced-in/surprise claims.
- The dashboard exposes the dated coverage contract, last receipt/check, freshness, current failures, and unsupported context. Every search and private investigation has a trigger, budget, and trace.
