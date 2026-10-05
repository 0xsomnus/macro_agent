# Paper desk audit

Real persisted manual approvals and paper declarations with fictional news inputs.
Zero model/provider calls or spend. Monitoring and external delivery are not configured.
This sequential trace illustrates state changes; independent PostgreSQL tests prove concurrency.

| Recorded stage | Binding | Current assessment | Pending notices |
| --- | --- | --- | --- |
| paper-desk-initial | ready | paper-desk-initial | 1 |
| position_changed | pending | none | 0 |
| paper-desk-resized | ready | paper-desk-resized | 1 |
| approval_changed | pending | none | 0 |
| paper-desk-amended | ready | paper-desk-amended | 1 |
| position_closed | pending | none | 0 |
| paper-desk-closed-history | ready | paper-desk-closed-history | 1 |

The approved thesis text and interpretation remain separate from source facts and agent assessments.
A draft proposal preserves the approval. Position changes, closure and explicit thesis approval clear
obsolete current briefs and cancel pending notices atomically. Fresh committed inputs must be admitted
before publication resumes. Historical retries cannot restore an obsolete approval or assessment.

| Paper transition | Revision | Quantity | Status |
| --- | --- | --- | --- |
| create | 1 | 1.00 | open |
| revise | 2 | 2.00 | open |
| close | 3 | 2.00 | closed |

Current brief: paper-desk-closed-history.
Input admissions: 4.

Input-observed timestamps conservatively witness already committed user context. Approval/preparation
times and admission effective times do not measure exact durable admission commit time.
The twelve source/macro/runtime roles remain synthetic. Instrument mapping is user-declared and unverified;
missing venue, product and quote currency remain explicit. Quantity is not exposure arithmetic or P&L.
Closed positions remain in history. Portfolio consequences remain unresolved; this is a factual-notice
mechanics trace, not continuous coverage, investment analysis or a complete operational replay.
