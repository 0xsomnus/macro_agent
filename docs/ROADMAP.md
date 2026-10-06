# Roadmap

The internal CLI checkpoint lets a trader enter their own thesis and paper trade against recorded example news. [Text-grounded compilation](THESIS_COMPILATION.md) now adds model-proposed interpretation, questions about weak assumptions, generic router catalogues and explicit model switching. Its mechanics are verified with recorded model responses; live model usefulness, factual verification and current macro context remain to be evaluated. [Getting started](GETTING_STARTED.md) is the runnable journey. No monitoring daemon exists yet, and this checkpoint does not satisfy the continuous monitoring, analysis or web-interface gates below.

Updated 2026-10-05 after the delegated DRF/generated OpenAPI selection in [ADR 017](ADR/017-drf-and-openapi-boundary.md). Order work by evidence gates. Continuous monitoring and useful thesis challenge are the core desk promise; scheduled releases alone cannot satisfy the pilot. The broader v1 universe is a future coverage target.

## Phase 0: reviewed contracts and internal research

- Validate 5 to 10 representative theses within the pilot universe, including incomplete theses, factual conflicts, and attached trades. This sample tests onboarding and usefulness, not broad recall or regime reliability.
- Pilot candidates: ES, NQ, XAU, DXY-linked trades, EUR/USD, USD/JPY, USD/CNH. DXY is also shared macro context. Validate actual venue, contract, and exposure mapping before calling a trade supported. USD/CNH is selected for China-related macro context, not asserted to rank third in standalone retail spot volume. GBP/USD is an expansion candidate.
- Preserve global contextual monitoring: a relevant foreign policy change or supply disruption is in scope without implying complete coverage of that economy.
- Define portable event, approved-interpretation, exposure, coverage, assessment, and notification contracts with synthetic point-in-time fixtures. See [DEVELOPMENT_START.md](DEVELOPMENT_START.md).
- Review source timeliness, allowed uses, historical vintages, failure behavior, and coverage exclusions. Continuous permitted news is mandatory for the live pilot. Historical consensus gates later studies rather than basic qualified analysis.
- Language and application foundation selected: Python API/domain/research workers, TypeScript web UI, Django/PostgreSQL, and explicit DRF serializers/APIViews with generated drf-spectacular OpenAPI, per [ADR 014](ADR/014-python-backend-and-typescript-ui.md), [ADR 016](ADR/016-django-postgresql-foundation.md), and [ADR 017](ADR/017-drf-and-openapi-boundary.md). Verify authority, atomic publication, correction races, and inspection through PostgreSQL. Frontend/client tooling, workers, and deployment choices remain open. Existing internal keys and configured provider adapters support research without adaptive routing, customer BYOK, or a credit-billing system.

**Gate:** contracts and authority/time invariants are executable; representative thesis refinement is useful; source feasibility and rights are documented; numeric pilot criteria and required data are identified. Contract tests do not establish live coverage or satisfy this full gate by themselves.

## Phase 1: thin Monitor web application and paper pilot

- Capture exact user text, approved concise interpretation, attached paper trades, source/coverage contracts, factual conflicts, and explicit amendments.
- Integrate Django authentication, sessions, and restricted internal inspection. Verify private-row isolation and approval authority across API, admin, and worker entry points; built-in account tooling alone does not establish those invariants.
- Authenticated boundaries persist exact draft text and manual or model-proposed interpretation, approve their hashes with protected current-version comparison, and attach/revise/close paper declarations. [API_DEVELOPMENT.md](API_DEVELOPMENT.md) and [PAPER_POSITIONS.md](PAPER_POSITIONS.md) document the journey. Real committed approval/exposure inputs enter protected synthetic event briefs; their changes atomically invalidate obsolete current briefs and pending notices. Mapping remains user-declared and unverified. Text-only model compilation does not establish factual verification, macro context, live source capture or a desk UI. Conservative input observations do not measure exact admission commit time or establish full operational replay.
- Run continuous permitted news monitoring alongside relevant official scheduled releases and permitted market context. Implement shared source capture, broad triage, unresolved-impact investigation, independent thesis/trade routing, and accumulation of distinct developments with offsets.
- Provide morning briefs, material-event analysis and counter-analysis, urgent qualified notices, and stable evolving briefs. Verify citations support factual claims; label causal pathways and portfolio consequences as hypotheses.
- Maintain source-health and coverage views, immutable history, basic decision/outcome records, and atomic notification intents with retry and supersession behavior.
- Separate calibration from evaluation. Independently review sampled source flow for misses, compare a simpler brief using the same available sources, and test deterministic mechanics separately from forward analytical usefulness.
- Measure shared acquisition, reusable analysis, private work, retries, latency, and aggregate spend. Compare shared versus private context construction before selecting a production policy or allocation formula.

**Gate:** freeze numeric criteria before the evaluation period; show material recall, disputed labels, noise, unsupported claims, latency, cost, source gaps, and trader usefulness. Passing a small pilot justifies the next increment, not the full future universe. Observe the first traders' actual workflows only after the paper pilot's source, product, and privacy boundaries pass review.

## Phase 1B: evidence-led coverage and equity expansion

- Expand validated packs toward nine currencies including CNH; SPX/NDX families; U.S. rates; gold, WTI, copper, silver; BTC/ETH; and a reviewed dynamic top-100 U.S. equity recipe. INR and natural gas remain context or later packs.
- Individual equities are a planned core commercial capability. Add supported deterministic valuation at relevant equity thesis compilation and material-input changes only after company classification, method, and data contracts pass validation.
- Add declarative user packs and additional event families only after their separate safety, rights, identity, and coverage review. Regulatory lifecycle machinery is introduced when a validated pack requires it.

**Gate:** measure coverage by driver/source contract and representative cases, preserve authority and replay boundaries, and validate usefulness. An asset label never promises exhaustive news awareness.

## Later, separately approved

- Statistical event studies start narrowly with FOMC/CPI/NFP only when historical expectations, reaction data, and original vintages are verified.
- Automated outcome learning, including provisional retrieval and promotion workflows, begins as an offline fresh-case experiment. Production use requires measured benefit and a new rollout review. Basic records already exist; learning is not automatically included in Phase 1B.
- Discovery presents analyst research candidates to the trader. Other later branches include richer options-horizon analysis, institutional entitlements/BYO Bloomberg, public community packs, additional jurisdictions, and a graph database only after measured need.
- Customer BYOK, adaptive model routing, subscription research-credit billing, and shared subscription cost allocation follow evidence of need and unit economics. Internal BYOK remains supported for research.
- Congressional-trading monitoring remains subject to separate legal/data review. Execution and autonomous trading remain outside the product direction.

## Open decisions

Frontend and TypeScript client/validator tooling, durable worker/queue and hosting; actual pilot instruments and venues; source/provider contracts and rights; numeric materiality, accumulation, severity, latency, and evaluation thresholds; pilot shared/private macro-context policy; costs and subscription allocation; initial jurisdiction; retention; future equity membership formula. Resolve choices through short reviews with concrete options; do not hide them in implementation.
