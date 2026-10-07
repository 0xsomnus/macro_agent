# Monitoring capture and recovery evidence

Verified 2026-10-07 against the isolated PostgreSQL 17 development database. This report proves local capture/recovery mechanics. It does not establish a continuous desk, personalised relevance or notification delivery.

## Separate command processes

| Transition | Reports | Revisions | Pending | Completed | Superseded |
| --- | --- | --- | --- | --- | --- |
| Capture two fictional items, exit before work | 2 | 2 | 2 | 0 | 0 |
| New process resumes work without another capture | 2 | 2 | 0 | 2 | 0 |
| Repeat original, capture one changed payload, repeat original again, process | 2 | 3 | 0 | 2 | 1 |

Capture revision counts were `2, 0, 1, 0`. The initial receipt identities survived restart. All retained payload hashes were independently recomputed. The changed report's original result stayed immutable while its current work disposition became superseded. Every completed result remained `unresolved_queue`; no portfolio assessment or notice was produced.

The [complete trace](monitoring-audit.json) contains fictional receipt/work history and live-fetch metadata. Full live content remains in the ignored local database/report. Reproduce the workflow with the [human guide](../docs/MONITORING_PIPELINE.md).

## Live transport check

One capture from the [Fed's official RSS feed](https://www.federalreserve.gov/feeds/feeds.htm) durably saved 20 distinct items. It retained bounded title, link, claimed publication time and feed description fields, without fetching linked articles. The source contract pins the Board's [attributed reuse policy](https://www.federalreserve.gov/disclaimer.htm) and third-party/logo exclusions, checked on 2026-10-07.

That snapshot left 20 pending work records. It proves real transport, parsing and receipt persistence for this endpoint. It does not prove completeness, latency, sustained polling, correction ordering or broad geopolitical coverage. Absence from a later feed is not a deletion signal. Rejected response bytes are not retained for replay.

## Executable verification

All 428 distinct tests passed across the component runs: 227 independent core/client/provider/source tests, the existing 175 PostgreSQL integration tests and 26 new monitoring cases. The monitoring cases cover crash after receipt commit before witness, restart on an independent connection, atomic rollback, duplicate suppression, expired capture and worker fencing, both source-change/completion lock orderings, time sampling after source/work protection, database immutability and scope, pending-row durability and coherent bounded inspection. Lock races observe actual PostgreSQL blocking.

Django system checks and migration-state comparison passed. Monitoring migrations applied successfully to development and fresh test databases. This evidence uses the local adapter and does not establish production supervision, deployment security or another worker adapter.

## Costs and authority

Zero model calls and zero model spend occurred. No subscription, paid feed or provider account was created. Local compute/storage costs were not measured. The news-data ceiling remains undecided.

Receipt time, publisher date claim and first postcommit observation remain separate. The observation is a conservative durability upper bound, never exact earliest known-at time. Source heads record latest observed unseen payloads, with publisher order unverified. No monitoring source head is installed into existing brief publication dependencies.

Next work remains protected source/context admission, broad materiality screening, thesis/trade routing, sourced hypotheses and useful briefs, then continuous worker supervision and delivery. This harness does not choose the production queue or satisfy those gates.
