# ADR 015: Inspectable domain rules and publication evidence

Status: Accepted by user review on 2026-10-03. Records agreed auditability requirements, not database or framework selection.

**Decision:** Keep rules in small Python modules. Require a readable rule, executable failure/race cases, and read-only evidence of state changes. Publication compares frozen versions and changes current state in one protected transaction. Every governing-version writer shares its ordering protocol. No model/network call holds the transaction open. Sample the trusted publication clock after acquiring protection.

**Why:** Code explains intent, forced concurrency tests ordering, and persisted evidence explains a particular result. A check followed by an unprotected write leaves a correction race.

**Publication:** Correction-first blocks stale currentness and retains superseded analysis. Publication-first is valid at that instant; subsequent correction supersedes it and cancels pending delivery. Reassessment uses current evidence. Preserve original decisions separately from current disposition, including retries. A late same-context run cannot replace a newer publication.

**Delivery:** A channel may have already accepted an older notice. Do not promise recall. Link materially corrective updates to the same evolving brief. External sends and durable leasing need their own tests.

**Evidence:** Force both orderings through independent connections on the selected database. Local SQLite tests validate their own protocol, not PostgreSQL, global correction propagation, or real delivery. See [IMPLEMENTATION.md](../IMPLEMENTATION.md).

**Consequence:** Every persistence adapter must prove ordering, atomic publication, supersession, retry, and inspection. Fixture setup does not establish authenticated authority or data rights.

**Implementation evidence, 2026-10-05:** [Paper-position integration](../PAPER_POSITIONS.md) extends the same protocol to owner/thesis protection and sorted affected briefs. Actual PostgreSQL waits exercise approval/publication and exposure/publication orderings, including clocks sampled after all brief protection. Context admission stores resolved already committed user inputs with conservative observation witnesses. It does not measure exact admission commit time or establish full operational activation replay; source/macro roles remain fictional.
