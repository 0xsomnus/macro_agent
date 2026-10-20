# Research source recheck

Reviewed 2026-10-19. Scope: unblock one supervised sourced-research test. No provider account, subscription, model request, continuous watch or external notification was created.

## Observed acquisition

The application's actual bounded adapters produced:

| Source | Observation | Limit |
| --- | --- | --- |
| GDELT DOC metadata | Ten-second timeout | No usable response or evidence captured |
| Federal Reserve press RSS | Twenty items parsed in 663 ms | One rolling snapshot, no coverage or freshness guarantee |

The [probe record](../artifacts/research-source-probe-2026-10-19.json) contains counts, timing and the successful transport digest. It made no database writes, model calls or article fetches. Earlier diagnostics established TCP connection followed by a GDELT API TLS timeout; the same environment reached the Fed and GDELT's main website. The evidence cannot distinguish an API outage from host-specific path blocking. Disabling certificate verification, downgrading transport or lengthening every client deadline is not justified.

Run `manage.py research_check_source --query "helium supply"` before spending on the question-led graph. This is an independent check, not an automatic retry or a source-health/coverage guarantee.

## Practical next test

The existing [selected-packet workflow](../docs/SOURCED_RESEARCH.md) can capture `fed-press` and compile a rough question that its retained statements can actually answer. Leave the draft unapproved and inspect its quotations and gaps. This can test live acquisition with sourced compilation once local model credentials are configured. It cannot answer a broad commodity, company or global-risk question simply because the transport works. [The Fed's reuse policy](https://www.federalreserve.gov/disclaimer.htm) supports attributed Board information subject to its stated exceptions.

## Broad-search replacement

Brave is a plausible candidate for bounded user-initiated discovery, separate from continuous monitoring. Its [API documentation](https://api-dashboard.search.brave.com/documentation) provides web, news and LLM context endpoints. However, the [standard terms](https://api-dashboard.search.brave.com/terms-of-service) limit result storage to transient use and require deletion at termination absent an overriding order form. Its [storage FAQ](https://brave.com/search/api/) calls for a plan that expressly grants storage rights. LLM grounding support is not sufficient evidence of durable audit-retention permission.

Before implementation or activation, resolve a plan/order form covering retained responses and quotations, selected external inference providers, and retention after termination. Do not treat an API key or price as that grant. No Brave adapter is selected here.

Tavily's [current platform terms](https://www.tavily.com/terms), section 6.4, restrict use of AI functionality or outputs for financial investment decisions. That unresolved fit makes it unsuitable as a silent replacement. This is a source-contract screening finding, not a conclusion about negotiated terms.

GDELT remains the implemented metadata experiment. Its failed acquisition is visible; the system must not manufacture research from model memory or quietly change sources.

## Recovery follow-up, 2026-10-20

A later thirty-second diagnostic returned HTTP 429 after 11.76 seconds. This establishes rate limiting on that request, while the earlier ten-second deadline hid its response. It does not prove every earlier TLS timeout had the same cause. GDELT [documents rate limiting on the DOC API](https://blog.gdeltproject.org/ukraine-api-rate-limiting-web-ngrams-3-0/); no current per-client quota was established.

The [implemented recovery mode](../docs/RESEARCH_SOURCE_RECOVERY.md) uses a versioned twenty-second exchange budget, bounded source-only attempts and shared cooldown across opted-in runs. It preserves the paid plan and complete failure history, and respects server delays even when they exceed the run budget. This fixes terminal workflow behavior without proving upstream availability. Alternate-source fallback remains dependent on selecting and configuring a suitable provider; none was activated.
