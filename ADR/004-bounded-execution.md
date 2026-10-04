# ADR 004: Explicit execution graphs and bounded workers

Status: Accepted.

Updated 2026-10-02. Initial scope, aggregate budgets, and reliable publication clarified.

**Decision:** Model compilation/refinement, monitoring, analysis/counter-analysis, research escalation, morning briefs, and delivery as versioned execution graphs with conditional transitions, permissions, failure paths, and stop rules. Valuation, Discovery, automated postmortems, and outcome-learning review remain future inactive graphs. Invoke specialists on demand. Context engineering selects inputs; loop engineering bounds iteration; execution graph engineering controls routing. The knowledge graph is separate.

**Why:** Clear authority and cost boundaries make the system testable and auditable while preserving useful specialist work for hard cases.

**Rejected:** A permanent agent swarm; one open-ended autonomous loop; conflating knowledge graph design with agent workflow design.

**Consequence:** Node traces and per-run plus aggregate budget metrics are required. Unknown relevance, feed/model failures, and budget exhaustion remain visible; they cannot become irrelevance. Credible urgency can produce a qualified early notice without a supported portfolio conclusion. Persist assessments and notification intents transactionally; leased retries reuse stable identities and channel-specific dedupe. Publication guards prevent stale input revisions from replacing current analysis. Exactly-once external delivery is not assumed.
