# Frontend exploration

Status: Proposal, 2026-10-10. Pending the user's answers about testing priorities and the decisions each visual should improve. This note does not select client tooling, visual design, data vendors or a delivery phase.

## First testing surface, proposed

The audience is the solo trader testing one weekly paper workflow. The first interface should make it easy to understand what changed, inspect why, and deliberately refine a thesis.

1. Enter exact thesis text; inspect the compiled interpretation, assumptions, counter-case, invalidation and gaps.
2. Save clarification answers, explicitly request recompilation, then approve the exact text and versioned interpretation.
3. Attach or update a manual paper position with instrument, direction, optional quantity/unit and horizon; show mapping gaps.
4. Review new evidence and cumulative changes against the approved thesis and attached trades.
5. Read the current daily brief, inspect its source passages and predecessor, and identify stale or missing inputs.
6. Inspect source health, last successful work and blocked jobs without treating a technical retry as a new investment decision.

These are proposed acceptance criteria, not claims of implemented browser capabilities:

- A trader can complete the flow without editing a database or reconstructing relationships from command output.
- Facts, user beliefs and agent hypotheses remain distinguishable; missing macro context and headline-only evidence remain visible.
- Every material assessment opens its retained source revision and relevant times, approved interpretation and exposure snapshot.
- Stale approvals are rejected clearly. A lost response can recover the saved command result without silently repeating model calls.
- Empty, loading, failed, stale, permission-denied and oversized-result states are explicit; partial coverage never looks complete.
- Keyboard operation and readable evidence work without a map or WebGL. A panel failure does not hide the thesis or brief.

The existing Django session/CSRF API and Python domain authority remain governing constraints under [ADR 014](ADR/014-python-backend-and-typescript-ui.md) and [ADR 017](ADR/017-drf-and-openapi-boundary.md). Frontend types do not replace server validation.

## One terminal, independent evidence

Proposed organization: a shared thesis, asset and time selection links brief, investigation, geographic, positioning and price views. Their visibility, permissions and refresh cadence remain independent.

Each panel needs its own source, entitlement, as-of time, delay and completeness indicators. Selecting a historical assessment must not silently replace its evidence with today's prices or positioning. A shared selection does not establish that separately timed datasets are synchronized.

Price data, instrument identity and venue contract specifications are separate from news-source data. A copper reference price does not establish an Exness CFD's carry or executable price; a stock price does not establish a venue's equity-perpetual exposure. Charts should display the actual series identity and mapping uncertainty.

## Geography: map before globe, proposed

Use a geographic view only when it helps locate a shock, inspect supply exposure or trace transmission. Keep the relevant evidence list and thesis links accessible alongside it.

- Distinguish event location, mentioned location, publisher location, company headquarters and affected exposure. One headline may have several places or no defensible point location.
- Preserve the geolocation source, precision, uncertainty and revision. Do not turn a country-level observation into a precise mine marker.
- A 2D map supports scanning many regions together. A globe may help understand routes and global relationships, but hides the far side and requires navigation. This is a design hypothesis to test.
- Define a heatmap's metric and time window. Article count measures source coverage; deduplicated event count measures a different thing. Neither alone measures severity or portfolio risk.
- Any relevance or severity weighting needs a visible definition, confidence and coverage limits. Missing coverage must not look like a quiet region.

[MapLibre GL JS](https://maplibre.org/maplibre-gl-js/docs/examples/) supports maps, globe projection, clustering and heatmap layers under a [BSD licence](https://github.com/maplibre/maplibre-gl-js/blob/main/LICENSE.txt). This makes it a candidate for exploring both projections without choosing separate engines. Basemap, imagery, tiles and geocoding rights require their own review.

[CesiumJS](https://cesium.com/platform/cesiumjs/) is Apache 2.0 and supports precision globes, terrain, 3D Tiles and time-dynamic visualization. It is an alternative if physical infrastructure or routes justify those capabilities. [Cesium ion and third-party content conditions](https://cesium.com/learn/ion/content-usage-and-attribution-guide/) are separate from the library licence.

## Positioning and GEX, later proposal

Options flow and estimated gamma exposure could help plan an already articulated view. They need a separate data and methodology contract before being treated as supported decision context.

[OCC/OIC explains](https://www.optionseducation.org/referencelibrary/faq/general-information) that open interest counts outstanding contracts, does not establish direction, and is updated after end-of-day clearing. It does not identify the dealer side. [Cboe explains](https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options/) why gross volume differs from net dealer risk and why outside positioning estimates depend on assumptions.

A GEX view should expose:

- Observed inputs versus estimated participant positions; dealer-sign assumptions and alternative scenarios.
- Instrument and venue coverage, expiry, settlement, contract multiplier and session conventions.
- OI date, trade/quote/IV timestamps, capture time, pricing model and calculation version.
- Sensitivity to price, volatility, time decay and sign assumptions; missing or stale contracts.
- Conditional hedging implications, rather than deterministic support, resistance or price forecasts.

[Research using Cboe records](https://cdn.cboe.com/resources/education/research_publications/gammasqueezes.pdf) used participant-tagged trades and modelled greeks to construct aggregate market-maker gamma. A public OI calculation should not imply equivalent observation. [Cboe Open-Close terms](https://datashop.cboe.com/cboe-options-open-close-volume-summary) separately restrict raw redistribution and require approval/fees for external derived-data distribution. User credentials alone do not establish those rights.

## Investigation and valuation views, later proposal

An investigation view should connect claims, supporting and opposing evidence, causal paths, assumptions and unresolved questions. Visual prominence must not convert an LLM's confidence or prose into verified evidence.

For valuation, deterministic code should calculate the reviewed business-appropriate method, assumptions, scenarios and sensitivities. LLM prose can explain or challenge inputs; it is not the arithmetic authority. Unsupported methods and absent inputs remain explicit, consistent with [ADR 009](ADR/009-fundamental-valuation.md).

## Chart candidates

- [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts#license): Apache 2.0; retain its NOTICE attribution and TradingView link. It renders data supplied by us, with no included market feed or built-in indicators. This is a candidate for the light testing surface, not a selected dependency.
- [Advanced Charts](https://www.tradingview.com/free-charting-libraries/): proprietary; current access rules target companies/public projects and exclude personal hobbies, studies and testing. The library does not include market data.
- TradingView Trading Platform adds broker/order integration and requires separate access; it does not justify adding execution to this product.
- [Hosted widgets](https://www.tradingview.com/charting-library-docs/latest/getting_started/product-comparison/) display TradingView data with fewer customization options and cannot accept our own data. They could be a separate reference view, but their display is not automatically an ingestible research feed.

## Decisions still open

1. Which testing action should the first surface make easiest: thesis refinement, cumulative evidence review, daily briefing or operational inspection?
2. What trader decision should geography improve, and what measurable improvement would justify a globe?
3. Should positioning condition entry planning, create a separate hypothesis, or serve only as optional context?
4. TypeScript framework/build tooling, client/schema generation, component approach, refresh strategy, layout, accessibility targets and deployment remain unselected.

The proposed first surface does not add broker execution, proactive Discovery, automated outcome learning, customer BYOK or commercial data entitlements. Maps, GEX and valuation workspaces are discussion candidates, not newly committed roadmap scope.
