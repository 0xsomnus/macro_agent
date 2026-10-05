# ADR 005: Monitor first, Discovery later

Status: Accepted; pilot scope clarified by user review on 2026-10-02.

**Decision:** Ship a minimally usable web MVP for Monitor mode that proves timely monitoring and useful thesis challenge. Architect a separate Discovery branch that could produce research candidates, but do not implement it in MVP.

**Why:** Monitoring an explicit user thesis gives a bounded relevance target and earlier demand signal. Discovery adds broad scanning, ranking, and a larger regulatory surface.

**Rejected:** Building a macro idea generator in the first release; starting with a backend-only prototype that cannot test briefing and thesis interactions.

**Consequence:** Shared event and graph contracts should permit Discovery later without running a dormant Discovery scanner now.

## Review clarification, 2026-10-02

Monitor is a continuous research desk: morning briefs, scheduled and unexpected relevant news, macro-context synthesis, analysis/counter-analysis, and collaborative thesis revision. Thesis impact and attached-open-trade impact are independent escalation routes. Narrowing supported exposures must not restrict relevant global context to US geography or scheduled-release alerts.

Start with a small paper pilot targeting ES, NQ, XAU, DXY-linked actual instruments, EUR/USD, USD/JPY, and USD/CNH, then observe initial external traders' workflows. DXY also serves as shared macro context. The FX mix tests useful exposures; it is not a top-three retail-volume assertion. Coverage promises identify sources, watched drivers, freshness, exclusions, and failures separately from global contextual monitoring.

Individual equities, automated valuation, statistical event studies, user-defined source packs, and automated outcome-learning workflows are deferred from the initial pilot. Preserve timestamped evidence and basic decision/outcome records. Equities remain a planned core capability with validated method-aware valuation considered at relevant thesis compilation. Automated learning must first improve fresh-case performance offline before production use.

Discovery later behaves like an analyst bringing potential opportunities to the trader from macro context. It remains separately approved. The audit clarification did not select an implementation stack. The subsequent [ADR 014](014-python-backend-and-typescript-ui.md) records the user-selected Python backend/TypeScript UI arrangement; frameworks and deployment were still open at that stage.

## Foundation update, 2026-10-04

[ADR 016](016-django-postgresql-foundation.md) selects Django/PostgreSQL with Django ORM and migrations, authentication, sessions, and restricted internal admin. The selected foundation does not change the monitoring-first scope or constitute live-pilot approval.

Amendment 2026-10-05: [ADR 017](017-drf-and-openapi-boundary.md) selects DRF and generated drf-spectacular OpenAPI through delegated judgment. Frontend/client tooling, durable worker/queue, hosting, and providers remain open. The manual draft/approval boundary does not establish continuous desk coverage.
