# ADR 012: Defer automated outcome learning and separate evaluation claims

Status: Accepted 2026-10-02. Revises early learning scope in ADR 007.

**Decision:** Keep basic outcome/decision records, immutable assessment inputs, evidence, and approvals. Defer automated postmortems, candidate-learning generation/retrieval, outcome-derived regime evidence accumulation, and the learned-relationship promotion pipeline. Current-source updates and named-human-reviewed canonical corrections remain available. Learning is not automatically activated in Phase 1B.

**Why:** Early pilots provide little evidence for generalisation and invite overfitting, recency bias, and narrative reinforcement. The pipeline adds cost and governance before the core desk proves useful. Record preservation keeps the future option open.

**Evaluation:** Use a calibration period followed by a separate evaluation period with frozen acceptance criteria and relevant configuration. Material changes begin a new evaluation. Independently review all feeds in sampled scope to find missed events absent from system output, preserving disputed labels. Blindly compare against a simpler brief with the same sources/cutoff and retain a deterministic monitoring baseline.

Distinguish deterministic replay of mechanics, historical reasoning with possible model hindsight, and forward usefulness from contemporary inputs. Store public availability separately from actual receipt and durable known-at time; freeze approved interpretation, exposure, source/coverage contracts, evidence, macro/graph versions, prompts, and model configuration for each assessment. Historical backfills cannot establish that the desk knew information before it acquired it.

**Later gate:** Run learning offline on fresh cases, including counterexamples and failure cases. Require measured benefit beyond the current desk before any provisional outcome-derived retrieval or promotion enters production. Trader agreement and one profitable call are insufficient. Canonical changes still need human review; a different future governance model requires explicit review.

**Rejected:** Outcome learning as a prerequisite for the initial desk; changing behavior through provisional retrieval while claiming canonical review protects it; evaluating only surfaced alerts; retuning and judging on the same cases; treating historical model reasoning or a small pilot as proof of predictive skill or full-universe coverage.

**Consequence:** The pilot tests monitoring, reasoning quality, authority, costs, failure handling, and trader usefulness. Research effort saved, clearer invalidation, or abandoning a weak thesis can be good results. Acceptance values and sample sizes remain decisions for pilot design, not numbers hidden in code. Statistical event studies remain later capabilities gated by verified point-in-time inputs.
