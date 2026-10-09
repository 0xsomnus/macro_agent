# Structured thesis review and restart continuation

Verified 2026-10-09. This is workflow evidence with recorded model responses, not an analytical-quality result.

## Actual HTTP trace

An ephemeral loopback Django server, real session/CSRF requests, the terminal client and the local PostgreSQL 17 database exercised this sequence:

1. Save synthetic thesis text with leading spaces, CRLF and Unicode. Compile one recorded proposal containing the complete review-card structure and a horizon question.
2. Save an exact answer against that retained question. Stop without recompiling or approving. The original text, draft revision and approved authority remain unchanged by answer storage.
3. Open a new client and recover the saved command from its private journal. Provider credentials are absent and provider construction is forbidden during recovery. The recovered answer and original context match the saved records.
4. Explicitly resume compilation on the same thesis with the saved refinement ID. Review and approve the new exact card. Its horizon quotes the retained answer; original text is unchanged.
5. Read the approved news context. The full card survives with agent proposals still labelled as proposals and external evidence explicitly unavailable. Reconstructed interpretation digest matches the approved digest.

The [complete synthetic trace](compilation-refinement-audit.json) contains the records, exact inputs and hashes. Both private journals have mode `0600`; credentials, cookies and CSRF tokens are absent from the public trace. The temporary account was disabled afterward.

The adapter handled four recorded catalogue requests and two recorded completions. Real provider calls and model spend were zero. Local compute/storage costs were not measured. No paper position, notification or research source was created. This illustrative gold sentence is not the jointly selected real weekly-test thesis.

## Verification

All **588 tests pass**: 305 core/client/provider/transport tests and 283 PostgreSQL/API tests. Django system checks, migration comparison, dependency compatibility and generated OpenAPI validation pass. Migration 0003 applied to the development database; its [generated SQL](thesis-0003.sql) is retained for review.

Tests cover exact answer attribution, cumulative lineage, immutable database guards, owner scope and CSRF, stale input rejection before provider calls, historical recovery without credentials, legacy interpretation hashes, complete-card approval hashes and proposal labels in news context. Existing separate-connection publication, approval and exposure tests also pass. New journal regressions preserve a complete saved request when a crash leaves partial JSON or a partial Unicode codepoint in the final response frame. Complete malformed records are rejected; recovery never repairs the file or repeats inference.

## Authority and failure behavior

- Saving answers is provider-free and does not change approved meaning. Recompilation is a separate explicit model request. Stale or foreign submissions cannot enter fresh inference.
- The admission commits before inference; database locks are released for the call. Completion rechecks protected governing state. Uncertain attempts remain visible without automatic paid retries.
- Approval binds the entire validated review card as well as exact original text and concise interpretation. Proposed drivers, catalysts and counter-cases remain agent hypotheses after review; approval does not establish factual verification.
- Historical interpretations without a card retain their original hashes. Current model output must satisfy the new schema, including explicit gaps where inputs are absent.
- The full-card bound is 524,288 bytes; the complete news-context bound remains 65,536 bytes. A valid compiler proposal may exceed the latter. News admission rejects overflow before inference rather than truncating the card or exposure.

## Remaining gates

The compiler uses original text and saved trader answers only. It has no verified facts, current macro regime, sourced catalysts or researched asset mapping. Quotations establish attribution, not semantic fidelity. Human review and live model testing remain necessary.

The [weekly test plan](../docs/WEEKLY_WORKFLOW_TEST.md) still requires jointly researched thesis-specific sources, cumulative context, sourced daily briefs and continuous dispatch/recovery. This increment establishes none of those capabilities. Clock samples and postcommit observations do not measure exact durable commit time or prove full operational replay.
