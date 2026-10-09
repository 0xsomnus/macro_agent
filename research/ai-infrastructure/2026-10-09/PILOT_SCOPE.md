# Candidate paper-pilot scope

Status: research proposals as of 2026-10-09, awaiting asset-specific thesis refinement and explicit approval. The user has asked to explore inclusion, not approved the hypotheses below or opened a paper position.

## Exact conversational inputs

Initial question, preserved verbatim:

> The AI boom is still very much in swing driving up valuation of semi-conductor and memory companies and associated commodities (copper?). We should research what assets are affected (aside from the indices and stocks like nvidia). Is it too late to start positioning?

Horizon and instrument follow-up, preserved verbatim:

> Horizon is fine. Right now, what comes to mind is copper CfDs and semi-conductor stock perps i.e AMD, NVIDIA etc. Think we can include these for the pilot?

Venue follow-up, preserved verbatim:

> Exness. Hyperliquid, blofin, even binance. What's the relevance?

The accepted research horizon is **a few weeks to a few months**, from the preceding horizon clarification. These conversational inputs are not an approved `UserThesisVersion`, compiled interpretation or active monitoring mandate. Research may conclude that no defensible trade thesis exists.

## Unapproved candidate hypotheses

The following are agent proposals to discuss. They introduce possible mechanisms and observable tests, not trader intent, predictions or recommended positions. Numeric thresholds and probabilities remain unset.

| Candidate | Conditional hypothesis and evidence | Countercase | Proposed challenge or invalidation signposts |
| --- | --- | --- | --- |
| Copper | AI electrical demand could tighten the relevant copper balance or expectations within the holding period, if incremental demand exceeds supply response. E1/E6 support the longer-run channel. | E7 forecasts near-term refined surpluses; China, construction, scrap, dollar/rates and supply disruption may dominate AI. Long-run shortage need not affect this period. | Evidence of accumulating inventories, weaker usage or project delays challenges tightening. Supply news requires comparison with actual refined availability. No approved balance, time or price threshold exists. |
| AMD | Instinct and EPYC deployments could produce revenue/margin revisions above expectations. E10 reports current Data Center growth; E15 supplies a dated results review. | Customer execution, software adoption, competing accelerators, exports and non-AI businesses can offset growth. Conditional customer warrants create potential dilution (E10a); revenue growth is not per-share value growth. | Delayed deployments, weaker conversion to sales/cash or deteriorating margin/outlook challenge the operating case. The price thesis also fails if the plausible outcome is already embedded in valuation. |
| NVIDIA | Continuing infrastructure deployment could sustain cash generation above the expectations embedded in its valuation. E11 reports current growth and next-quarter guidance. | Customer concentration, custom silicon, export controls, architecture transitions, power constraints and weaker customer economics can interrupt growth or reduce margins. | Verified cancellations/delays, weaker cash conversion or revisions to growth/margins challenge the case. Current growth alone cannot rebut an expectations-based countercase. |

Evidence IDs refer to [the source register](EVIDENCE.md). A price stop, liquidation event or adverse funding outcome is an instrument/trade condition, not automatically fundamental thesis invalidation. Positive fundamental news can support a thesis while worsening a crowded or expensive attached trade's economics.

## Venue feasibility, without an execution connector

The current paper-position API records instrument, direction, optional quantity/unit and horizon. The checklist below is retained research, not newly required or supported API fields. Unresolved contract terms, carry and quote/time details can remain external research gaps for this workflow test.

| Candidate declaration | Confirmed feasibility | External research checklist |
| --- | --- | --- |
| Exness XCUUSD CFD | Official specifications list copper with tonne-based lot sizing. | Account/entity, precise unit, entry quote/time, direction, optional quantity and horizon, swap/admin-fee applicability, spreads and sessions. Conditional overnight fees can materially affect multiweek holding costs. |
| Hyperliquid XYZ `xyz:AMD` or `xyz:NVDA` | Builder specifications and one public metadata response confirm these exact contracts. | Builder identity, share-reference quantity, margin mode, oracle/mark distinction, funding, collateral and corporate-action gaps. Do not generalize XYZ's terms to every Hyperliquid builder. |
| Binance AMDUSDT or NVDAUSDT | Official launch notices confirm both contracts. | Region/account availability, current contract revision, funding, price/index mode and corporate actions. Launch specifications are not guaranteed current parameters. |
| BloFin AMDUSDT or NVDAUSDT | Official launch notices confirm both contracts. | Current specifications, funding, external-data freeze behavior and restrictions on opening outside regular market hours. |

Venue matters because the same company can have different funding, collateral, reference prices, hours, corporate-action handling and margin conditions. A perp references an underlying company; it does not remove the need to evaluate that company's value. This review does not select a venue or imply that copper should be replaced with a different instrument.

## Durable-workflow test boundary

The immediate objective is to test compilation/refinement, approved-context continuity, capture/restart recovery, headline relevance, independent thesis/trade impact and daily review. [The weekly test plan](../../../docs/WEEKLY_WORKFLOW_TEST.md) defines the broader prerequisites.

- Use a named, suitable source and explicitly bounded coverage. Manual research links do not become a licensed automated feed by inclusion here.
- Pin exact approved text/interpretation, exposure declaration, source revision, context and model/rule dependencies for each assessment.
- Accumulate previous-period analyses with contrary evidence and visible stale, failed or unavailable work. Preserve source publication, actual receipt and durable observation distinctions.
- Keep proposed amendments separate; only explicit approval activates a new thesis or material interpretation.
- Venue integration and full economic modelling are not prerequisites for the headline-level durability exercise. Unknown carry, missing market prices and incomplete valuation must prevent claims of complete performance or investment readiness.
- Preserve global context around this narrow candidate universe. This internal extension does not certify supported copper or individual-equity production packs.

Individual-equity valuation remains required for supported AMD/NVIDIA investment analysis under [ADR009](../../../docs/ADR/009-fundamental-valuation.md). No approved exception, validated calculation or price target is created here. The application remains a research tool with manual paper declarations, no broker execution.

## Consequential questions for joint refinement

1. Which candidate has a testable development over this horizon that current prices may not reflect, and what would count as contrary evidence?
2. For that candidate, which assumptions can we verify now, and which must remain unresolved before a supported investment conclusion?
3. Which exact instrument should the trader declare for the paper exercise, with any unknown costs and contract mechanics visibly retained?
