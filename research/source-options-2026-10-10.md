# Free research inputs and future wire subscriptions

Reviewed 2026-10-10. Scope: a narrow internal weekly paper workflow with headline-level evidence. This note compares source feasibility; it does not activate a source, approve a thesis or establish complete monitoring coverage. No live news API, model request, account creation or provider contact was used in this review.

## Recommendation

Research both yfinance and GDELT behind replaceable source contracts. Use fictional Yahoo-shaped recordings to test the yfinance parser while its access and processing permissions remain unresolved. A bounded GDELT metadata adapter plus reviewed official feeds is the more defensible initial live experiment. Neither supplies a complete macro trading desk or executable CFD/perpetual prices.

| Input | Useful initial role | Principal boundary |
| --- | --- | --- |
| yfinance ticker news | Research ticker-headline parsing and relevance with recordings | Live automated access, retention and external inference are not established by the library licence or personal-use disclaimer. |
| GDELT DOC metadata | Find and retain a bounded set of reported headlines relevant to a fixed research scope | Query and indexing gaps, duplicate reporting, result saturation and missing correction history remain visible. Linked article bodies are excluded. |
| Official feeds | Retain attributed first-party policy/release statements | Each agency and endpoint needs review. First-party publication establishes attribution, not the truth of forecasts or completeness of market coverage. |
| User-supplied wire access | Later entitlement-scoped API capture and analysis | Credentials establish access, not permission for our server, storage, inference providers or shared reuse. |

## yfinance: technically useful, live permission unresolved

The official API exposes `Ticker.get_news(count=10, tab="news")`, including all-items and press-release alternatives. The current implementation requests a latest ticker stream, returns untyped upstream objects and does not fetch linked article bodies. It has no news pagination/history cursor or correction stream. Nonempty results are cached on the `Ticker` instance; some malformed responses become an empty list when errors are hidden. Polling must refresh and distinguish acquisition/schema failure from an empty valid result. [API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.get_news.html), [implementation](https://github.com/ranaroussi/yfinance/blob/main/yfinance/base.py).

The parser should validate native identity, title, source, link and any claimed publication time without assuming every field exists. Official API documentation does not promise a stable item schema. Ticker association is an upstream selection signal, not a determination of portfolio relevance.

yfinance is unaffiliated with Yahoo and its code is Apache licensed. Its README expressly directs users to Yahoo for data rights. Yahoo's general terms restrict automated collection without express prior permission and commercial reuse. No reviewed grant currently covers this application's unattended capture, immutable retention and external model processing. An internal research label does not itself provide that grant; applicable regional/account terms still need confirmation. [Project README](https://github.com/ranaroussi/yfinance/blob/main/README.md), [Yahoo terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html?ncid=mbr_idnedulnk00000001).

**Current boundary:** fictional recorded adapter only. Public endpoint reachability, a user's Yahoo account or a successful library call cannot change the rights status. No article-body scraping, circumvention or silent fallback to another Yahoo interface.

## Proposed bounded GDELT capture contract

GDELT permits use and redistribution of its released datasets, including commercial use, with attribution and a website link. DOC provides article lists and explicit date queries, with at most 250 results. These statements concern GDELT's dataset; they do not grant a licence to retrieve linked publishers' article bodies. [Terms](https://www.gdeltproject.org/about.html#termsofuse), [DOC reference](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/).

The following is a proposed adapter contract, not a claim about implemented code or an approved operating schedule:

| Contract element | Proposed rule |
| --- | --- |
| Endpoint | Fixed HTTPS host `api.gdeltproject.org`, path `/api/v2/doc/doc`, GET only. No arbitrary URL or redirect following. |
| Scope | Operator-reviewed fixed query, `mode=artlist`, `format=json`, `sort=datedesc`. Query/version enters the source-contract identity; each capture attempt records its request window separately. No model-generated general search loop. |
| Bounds | Reuse the current parser envelope: at most 100 items, 1 MiB response and a 10-second total transport deadline. These are local protections, not GDELT quotas or latency promises. Poll cadence, window and overlap require explicit setup. |
| Retained text | Dataset headline and article URL only; `content` stays empty. Exclude article bodies, thumbnails and fetched publisher pages. Attribute GDELT as the metadata provider and identify the linked publisher separately when supported. |
| Identity | A local SHA-256 identity derived from the exact returned article URL within the versioned source scope. Preserve the original URL; do not silently merge syndication, mobile variants or tracking variants. Changed observed headline payloads create revisions. |
| Time | Local `received_at` and durable post-commit observation remain separate. Keep `published_at=null` unless a separately supported publisher claim exists. Do not treat DOC query bounds or `seendate` as verified publication, first public availability or local receipt. |
| Extra provenance | Preserve the query/window and any accepted upstream metadata with its own schema and semantics. The current five-field `SourceItem` cannot silently absorb `seendate`, domain or language as a publication timestamp or article content. Missing metadata remains explicit. |
| Saturation | A response at the requested cap is possibly incomplete and must carry a visible limitation. Never treat a capped window as exhaustive or silently advance a completeness cursor. No automatic unbounded window splitting or pagination. |
| Failure | Invalid JSON, malformed item, byte/item overflow, transport failure and a valid empty result remain distinct. No immediate automatic retry; subsequent scheduled polls are separately recorded attempts. |
| Rights | Pin the reviewed dataset policy, attribution, scope and permitted internal processing. The payload is metadata evidence, not licensed publisher article text. A permission withdrawal blocks new use. |

Date overlap can reduce misses but cannot establish completeness, timely indexing or authoritative correction order. A missing URL in a later result is not a deletion. Multiple headlines about one development are not independent confirmations or increased conviction. Query selection must preserve relevant overseas drivers; ticker-only or US-only filtering would collapse context.

Before live activation, prove strict parsing, cap handling, repeated-payload deduplication, changed-payload preservation, acquisition failure visibility, request-window provenance and capture/restart recovery with recordings. Then measure one bounded live acquisition separately. No live measurement is claimed here.

## Official feeds and future wire credentials

The Fed explicitly publishes RSS for automated readers, with links, headlines and brief summaries. Board information is generally reusable with attribution unless indicated otherwise; third-party content and protected marks are exceptions. The existing `fed-press` adapter fits that narrow scope. It cannot establish AI infrastructure or copper-news coverage. Other agencies, company investor-relations feeds and linked pages require separate review. [Fed directory](https://www.federalreserve.gov/feeds/feeds.htm), [reuse policy](https://www.federalreserve.gov/disclaimer.htm).

Future user-supplied wire access should bind credentials to the user, dataset, permitted processors, retention/display scope and expiry. Prevent content from entering shared context unless the entitlement permits it. Revocation must block new use while applying the actual contract's historical-retention requirements.

Newsquawk advertises licensed JSON/RSS delivery, while its ordinary terms restrict use and credential sharing. This illustrates why a retail login must not be assumed to include API or third-party inference rights. Keep source credential support separate from deferred customer model-BYOK and subscription billing. [Enterprise delivery](https://www.newsquawk.com/enterprise), [terms](https://www.newsquawk.com/terms).

Unresolved choices are the exact research query, supported source mix, acceptable delay, operating cadence and bounds, rights to live Yahoo use, and later wire entitlement details. These choices do not block deterministic recovery and context-continuity development.
