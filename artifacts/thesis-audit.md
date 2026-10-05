# Thesis approval audit

Fictional manual interpretation, zero provider calls or spend. Monitoring is not configured.
This sequential service trace does not prove HTTP authentication or concurrency.
The integration tests establish those boundaries separately.

| Transition | Revision | Text version | New approval |
| --- | --- | --- | --- |
| create | 1 | d533ec93-2928-40bf-95af-c01e8a63c45b | none |
| approve | 2 | d533ec93-2928-40bf-95af-c01e8a63c45b | 9e34fc85-b143-4a12-a39d-04813e757b4c |
| propose | 3 | 8037bae2-3b0b-4379-84d5-de841b60ae43 | none |
| approve | 4 | 8037bae2-3b0b-4379-84d5-de841b60ae43 | 2b8a6246-c8d5-4b1d-b5fa-a6cff9edc4ea |

Current approval: 2b8a6246-c8d5-4b1d-b5fa-a6cff9edc4ea.

The revised draft preserved the first approval. An attempted stale approval was rejected.
Retrying the first approval returned its original receipt with `is_current_approval: false`.

Times record protected acceptance and manual preparation. They are not measured durable commit times.
History is capped per category, with truncation visible. No source coverage, attached trades,
model compilation, publication-pin integration, UI, or external delivery is exercised.
