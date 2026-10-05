# ADR 001: Separate user belief, assessment, and knowledge

Status: Accepted; clarified by user review on 2026-10-02.

**Decision:** Store `UserThesis`, `AgentAssessment`, and `SystemKnowledge` separately. Approved user thesis versions are immutable. The agent surfaces sourced factual conflicts first and may propose, but never apply, amendments. The user can retain a flagged contrarian thesis.

**Why:** A system assessment can change with evidence without rewriting the trader's position or obscuring who believed what. This also makes postmortems fair and traceable.

**Rejected:** A single mutable thesis record; silent correction of objectively false premises; rejecting user theses because the agent disagrees.

**Consequence:** Explicit approval and versioning add UI and persistence work. Test that no system path mutates approved thesis text.

## Review clarification, 2026-10-02

Ownership includes meaning as well as words. User approval covers exact `UserThesisVersion` prose and a concise `CompiledThesisVersion` interpretation of drivers, horizon, and invalidation signposts. Compilation versions are immutable; `CompiledThesisActivation` separately records authority and effective time. Material interpretation changes require approval even when prose is untouched. Equivalent source replacements and technical repairs can activate automatically only with a recorded equivalence basis and audit trail.

The desk distinguishes factual errors, unsupported mechanisms, missing detail, and defensible disagreement. It asks focused questions and may propose a more explicit, supported, falsifiable thesis while identifying agent-added assumptions. Strengthening may reduce conviction or abandon an idea. Retaining a false premise does not make it merely contrarian; factual conflicts stay visible. Declined refinement leaves observable approved elements monitored and gaps unresolved.

The agent may investigate additional drivers under its own assessment immediately and propose incorporation later. This preserves analytical initiative without silently altering the user's reasoning. Assessment snapshots preserve the exact approved interpretation and exposure used at that moment.
