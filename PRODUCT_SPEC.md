# Product specification

## Initial user and wedge

Macro Agent is a continuous research and monitoring desk for solo/retail discretionary macro and fundamental traders, including traders developing their first fundamental or macro swing theses. It connects incoming developments and the changing macro picture to approved theses and attached open trades, supplies morning briefs, analysis and counter-analysis, and helps the trader revise their view when warranted. The user retains judgment, sizing, and execution. Intraday signals, trade timing, execution, and automated hedging are outside the pilot.

The first build must prove **both** timely, relevant continuous monitoring and useful challenge to the user's reasoning. Strengthening a rough thesis means making its assumptions explicit, supported, and falsifiable; a useful conversation may reduce conviction or cause the trader to abandon it. A thin web application is the minimum usable interface. [ADR 014](ADR/014-python-backend-and-typescript-ui.md) selects a Python API/research backend and TypeScript UI.

Update 2026-10-04: [ADR 016](ADR/016-django-postgresql-foundation.md) selects the Django/PostgreSQL application foundation. API/wire tooling, frontend tooling, durable workers, and deployment remain open. Authentication and internal inspection must preserve private-trader access and the same approval/publication authority across all entry points.

## Initial paper pilot

Follow a small set of real theses and paper trades before observing the first external traders' workflows. Supported exposure targets are ES, NQ, XAU, DXY-linked trades, EUR/USD, USD/JPY, and USD/CNH. Identify actual contracts or products separately from index/underlying context. DXY is both shared macro context and a target for directly attached trade theses; an index reference is not an executable instrument. The three currency pairs are a deliberate pilot exposure mix, not a claim about the top three retail-volume pairs.

Keep global contextual monitoring wherever it can affect those exposures. An overseas policy or supply shock can be relevant without comprehensive coverage of that country or commodity. Supported instruments and contextual monitoring have separate coverage promises.

Individual equities are deferred from this pilot because of issuer coverage and valuation requirements. They remain a planned core research capability. Their proposed contribution to willingness to pay must be validated. Automated valuation, statistical event studies, automated outcome learning, and user-defined source packs are also deferred; basic decision/outcome records and timestamped source collection begin in the pilot.

## Core journeys

1. **Set scope.** User enters positions or watchlist assets, actual instrument details where needed, horizon, thesis, alert sensitivity, and available sources. Instrument exposure is context, not an order instruction. Explain missing exposure detail and the analysis it prevents.
2. **Refine and compile.** Separate factual errors, unsupported mechanisms, missing detail, and defensible disagreement. Explain consequential gaps, ask focused questions, and propose improvements with trader assumptions distinguished from agent additions. User approves exact `UserThesisVersion` text and a concise `CompiledThesisVersion` interpretation covering drivers, horizon, and invalidation signposts. They may retain their text with visible conflicts or unresolved areas. Material changes to interpretation require approval; equivalent source substitutions and technical repairs may proceed automatically with an audit trail.
3. **Monitor continuously.** Source watchers capture scheduled releases and permitted unexpected news independently of LLM availability. Broad screening routes possible thesis impact and open-trade impact separately; either can warrant investigation. Unfamiliar events need credible potential significance or broad disruption, not novelty alone. Ambiguous relevance receives bounded investigation. Independent developments accumulate in macro context, with duplicate reports and offsetting evidence accounted for. A classification failure cannot become a judgment of irrelevance.
4. **Review intelligence.** Morning briefs and material alerts explain what changed, plausible transmission paths to specific exposures, competing hypotheses, uncertainty, and observable next signposts. A credible urgent development can generate a narrower qualified notice while impact is unresolved. Update the same event/thesis brief as evidence and analysis develop; interrupt again only for material change. Keep analytical confidence separate from a trade-success probability. Withhold surprise or priced-in claims when expectation evidence is unavailable.
5. **Revise collaboratively.** The agent may investigate additional drivers immediately under its own assessment and propose thesis improvements. Only the user can approve changed prose or a material change to the active compiled interpretation. Record decisions, feedback, and basic outcomes. Automated postmortems and outcome-derived learning remain later, evidence-gated capabilities.

## Minimum web surfaces

| Surface | Minimum interaction |
| --- | --- |
| Portfolio/watchlist | Add/remove exposure context, identify attached actual instruments, and inspect dated coverage contracts; no broker credentials. |
| Thesis editor | Exact user text, concise interpretation, refinement issues, factual conflicts, source manifest, and separate approval/amendment records. |
| Brief | Morning synthesis and evolving event/thesis briefs explaining relevance to the thesis, attached trades, and macro context. |
| Event detail | Canonical event, public availability and actual system receipt, revision chain, supported expectation evidence, observed reaction, claim-level support, and unresolved impact. |
| Assessment/history | Immutable assessments and context snapshots, changes from prior assessment, brief versions, user feedback, decisions, and basic outcomes. |
| Source settings | Supported packs, sensitivity override, freshness, failures, licensing status, and known exclusions. User-defined packs are later. |

## MVP acceptance scenarios

- A user can add a long gold thesis tied to real yields, approve its exact text and interpreted drivers/horizon/signposts, and inspect what is watched. CPI or unexpected relevant news can trigger analysis; a trade-level catalyst can warrant attention even when the longer-term thesis is intact.
- A new trader can refine a half-formed idea through sourced corrections, questions, and counter-cases. A retained false factual premise remains labelled as a factual conflict, not relabelled as merely contrarian. Monitoring does not invent unspecified horizon or invalidation criteria.
- A scheduled release with no relevant change produces an audit record without an unnecessary user alert. A sequence of independent smaller developments may warrant analysis collectively.
- A credible potentially severe unfamiliar event receives bounded investigation, not automatic dismissal or automatic interruption. A credible urgent event can receive an early qualified notice, then a material update in the same brief.
- An analyst can reconstruct exact evidence revisions, availability/receipt times, approved interpretation activation, exposure, regime, manifest, coverage, knowledge, rules, prompt/model version, and budget used by an assessment. An outdated analysis cannot replace one based on newer evidence.
- A missing premium news feed is shown as a coverage limitation. The system never implies exhaustive unexpected-news awareness.
- An important fact links to the passage or data field that supports it. A source citation alone does not establish the proposed portfolio consequence; causal hypotheses state assumptions and counter-evidence.
- Saving a published assessment and its pending notification together survives a crash. Retry and visible delivery failure prevent silent loss without claiming duplicate-free delivery from unsupported channels.

## Deferred and out of scope

Discovery is a future analyst-like branch that brings potential opportunities to the trader from macro context for research and review. It is not a pilot screen or background scanner. Individual-equity research with validated method-aware valuation at relevant thesis compilation, automated valuation, statistical event studies, user-defined packs, and automated outcome learning are deferred from the initial paper pilot. Outcome learning first requires offline evidence of improvement on fresh cases. Hedge ideas, personalized trade recommendations, short-horizon options analysis, comprehensive geopolitical/social coverage, and institutional terminals are deferred pending validation and legal review. Global developments relevant to supported exposures remain in the monitoring remit. `ROADMAP.md` owns sequencing.
