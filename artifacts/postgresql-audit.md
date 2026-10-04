# PostgreSQL publication audit demonstration

Fictional recorded inputs, zero provider calls and spend. These snapshots
illustrate the Django/PostgreSQL adapter's persisted results. Separate
integration tests prove concurrency; this report is sequential.

## Correction first

Brief: postgres-demo-correction-first.

| Assessment | Initial decision | Current before reassessment |
| --- | --- | --- |
| analysis-r1 | superseded | False |

Old-analysis disposition: superseded.

Current persisted assessment: analysis-r2.
Generation: 1.

| Recorded transition | Result |
| --- | --- |
| bootstrap | fixture setup |
| synthetic_dependency_registered | fictional-release@2 |
| dependency_advanced | fictional-release@2 |
| publication | superseded |
| publication | current |

| Notification assessment | Persisted local state |
| --- | --- |
| analysis-r2 | pending |

Reassessment work: completed.

## Publication first

Brief: postgres-demo-publication-first.

| Assessment | Initial decision | Current before reassessment |
| --- | --- | --- |
| analysis-r1 | current | False |

Old-analysis disposition: superseded.

Current persisted assessment: analysis-r2.
Generation: 2.

| Recorded transition | Result |
| --- | --- |
| bootstrap | fixture setup |
| publication | current |
| synthetic_dependency_registered | fictional-release@2 |
| dependency_advanced | fictional-release@2 |
| publication | current |

| Notification assessment | Persisted local state |
| --- | --- |
| analysis-r1 | canceled |
| analysis-r2 | pending |

Reassessment work: completed.

## Limits

No live feed, model analysis, trader onboarding, global correction fan-out,
durable worker leasing, or external notification channel is exercised.
The fixture owner's unusable password prevents interactive login. Synthetic
bootstrap is not durable approval of a real trader's thesis.
