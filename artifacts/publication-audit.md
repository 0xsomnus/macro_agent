# Publication audit demonstration

Fictional inputs, no provider calls or spend. Separate-connection tests prove
the local SQLite ordering behavior. This report illustrates recorded results.

## Correction first

| Assessment | Original decision | Current before reassessment |
| --- | --- | --- |
| analysis-r1 | superseded | False |

Retry/late-completion result: superseded.
Current after fresh evidence: analysis-r2.

| Recorded transition | Result |
| --- | --- |
| bootstrap | fixture setup |
| dependency_advanced | fictional-release@2 |
| publication | superseded |
| publication | current |

| Notification assessment | Final local state |
| --- | --- |
| analysis-r2 | pending |

## Publication first

| Assessment | Original decision | Current before reassessment |
| --- | --- | --- |
| analysis-r1 | current | False |

Retry/late-completion result: superseded.
Current after fresh evidence: analysis-r2.

| Recorded transition | Result |
| --- | --- |
| bootstrap | fixture setup |
| publication | current |
| dependency_advanced | fictional-release@2 |
| publication | current |

| Notification assessment | Final local state |
| --- | --- |
| analysis-r1 | canceled |
| analysis-r2 | pending |

## Limits

No live feed, model analysis, authenticated service, global correction fan-out,
durable worker leasing, or external notification channel is exercised.
These results do not establish the behavior of another database adapter.
