# ADR 007: Outcome learning without online model training

Status: Revised 2026-10-02. Record capture accepted; automated outcome learning deferred by ADR 012.

**Original direction:** Capture inspectable outcome memory rather than train model weights online. This remains a future possibility, not an early feature commitment.

**Decision:** Preserve basic outcome observations, decisions, exact assessment/context snapshots, evidence, and approvals now. Defer automated postmortem generation, candidate-learning generation/retrieval, outcome-derived regime accumulation, and the learning-to-edge-promotion pipeline. Updating current assessments from incoming evidence and manually correcting sourced knowledge remain allowed. Named human review governs canonical corrections during the pilot. Online fine-tuning and opaque model-weight updates remain deferred.

**Why:** A small early sample is especially vulnerable to recency bias and overfitting; an automated learning pipeline adds cost before the desk proves useful. Raw records preserve future research options. A correct thesis may still have poor timing or trade expression.

**Rejected:** Scoring only next-day direction or P&L; retraining or changing canonical relationships after each failed prediction.

**Consequence:** Outcome learning begins later offline, requiring improvement on fresh cases against the existing desk before production use. Provisional retrieval cannot alter current behavior in the pilot. Point-in-time records and deterministic replay are required now; historical LLM performance alone cannot establish foresight.
