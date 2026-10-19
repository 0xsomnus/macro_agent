# Compile against retained sources

You can now give thesis compilation a selected packet of captured evidence. The model still preserves your exact text and separates your intent from its own proposals. It can quote retained reports, identify a possible factual conflict, and ask which premise, date or series you meant. A quotation proves attribution, not that the source is true or that its statement supports the model's conclusion.

This selected-packet workflow is a bounded research step. For automatic named-question discovery without hand-picking reports, use [question-led research](QUESTION_RESEARCH.md). The compiler itself fetches no source; the separate orchestrator retains discovery before compilation. Neither path establishes a verified macro regime.

## Terminal workflow

Complete [model setup](THESIS_COMPILATION.md) and enable the local monitoring proof for capture. Run migrations and restart the backend after loading its configuration.

1. Create a thesis with the existing `happy-path` flow, leave manual drivers/signposts empty if needed, then leave it unapproved. This requires no model call. Keep its thesis UUID. Alternatively use an existing draft.
2. Capture a permitted source, then inspect its current revision UUIDs with `manage.py monitor_inspect --source SOURCE_ID`. The [monitoring guide](MONITORING_PIPELINE.md) explains capture. The selected reports must have a durable availability witness.
3. Freeze one to sixteen selected current revisions through the authenticated session API:

```sh
.venv/bin/python tools/review_evidence.py --thesis-id THESIS_UUID --revision-id CURRENT_REVISION_UUID
```

Repeat `--revision-id` for more reports. Inspect the returned exact packet, source links, receipt and witness times, permission versions and coverage gaps. This step makes no model call or approval.

4. Compile the existing thesis using the saved evidence-context UUID:

```sh
.venv/bin/python tools/desk_cli.py compile --thesis-id THESIS_UUID --evidence-context EVIDENCE_CONTEXT_UUID
```

Add `--driver-review` for individually evidence-linked proposed drivers and exploratory exposure candidates. Research is not restricted to the pilot instruments. Each proposed driver records transmission, support/counter claim IDs, assumptions, uncertainty and why it could matter. Each exposure candidate records its relationship, basis risks and verification questions; instrument availability stays `unverified`. An importer can be hurt by rising input costs, so a related equity is not automatically a beneficiary or equivalent commodity exposure. This request starts no monitoring or paper position.

Choose a model from the configured provider's catalogue and confirm the request. Inspect model-identified factual conflicts before its assessment. Extracted intent must still quote your own text or saved answers; source passages cannot stand in for your intent. Refinement and exact approval use the existing terminal flow. The full sourced review card is included in the interpretation hash.

The initial manual flow needs no model call. The [question-led terminal flow](QUESTION_RESEARCH.md) can now begin directly from a rough question without this manual packet preparation. Each displayed factual conflict also has a matching retained refinement question, so you can answer it before explicitly recompiling.

## Recovery and changes

The evidence tool writes a private command journal before saving a packet. Recover it without preparation, capture or inference:

```sh
.venv/bin/python tools/review_evidence.py --thesis-id THESIS_UUID --command-id SAVED_COMMAND_UUID --recover
```

Recover compilation using `desk_cli.py recover --thesis-id THESIS_UUID --command-id SAVED_COMMAND_UUID --kind compilation`. A lookup never sends a replacement paid request. Keep the IDs printed before transmission if the response is lost.

Source corrections or permission changes make the packet stale. Compilation checks protected source state at admission and completion. New approval checks it again. A stale result remains history and cannot install a new interpretation. A correction after approval does not rewrite or revoke your approved words; the saved packet's observed disposition becomes stale separately.

## Contracts and limits

`ResearchEvidenceContext` is independent of approved private monitoring context, so evidence can be selected before approval. It retains exact report text, revision identities, source contracts, current heads and conservative availability witnesses. Sources are protected before owner, thesis and affected briefs; model admission additionally protects the shared private-call budget. Database locks are released during inference.

The complete packet is limited to 65,536 encoded bytes, sixteen reports, 4,096 characters per title/URL and 16,384 per content field. Overflow rejects visibly without truncation. Current revisions only are supported in this first selection flow. Historical selection, automated evidence discovery, verified causal edges, consensus and pricing are separate work.

Question-led research now prepares `retained-source-evidence-v2` with a server-built `question_research` context. It pins the exact retained plan, discovery receipts/results and complete query-to-revision mapping, including empty searches and selection limits. This is workflow context, not quotable evidence or trader intent. The HTTP selection endpoint does not accept it. Selected packets without that context retain their v1 identities; new contextual prompts carry a distinct version suffix, and approval binds the full retained card.

The strict session/CSRF endpoints are:

- `POST /api/v1/theses/{thesis_id}/evidence/`, exactly `command_id` and `revision_ids`.
- `GET /api/v1/theses/{thesis_id}/evidence/{context_id}/`.
- `GET /api/v1/theses/{thesis_id}/evidence-commands/{command_id}/`.
- Existing `POST /api/v1/theses/{thesis_id}/compile/`, with optional `evidence_context_id` and strict boolean `driver_review`. The latter requires retained evidence when true.

Legacy text-only requests retain their card version and hashes. New sourced cards use `thesis-review-card-v2`; factual conflicts remain `model_identified`, never verified corrections. Costs, unknown outcomes and explicit paid retries follow [compilation](THESIS_COMPILATION.md).

The opted-in profile uses `source-backed-thesis-compilation-v2`, prompt v2 and `thesis-review-card-v3`. It requires `proposed_drivers` and `exposure_candidates`, including empty arrays when evidence is insufficient. The old unlinked `agent_hypotheses` array must be empty in this profile. Proposals do not enter extracted intent merely because the card is approved. Incorporation requires exact trader input and another explicit approval. Omitting the flag preserves the previous request identity and card format; a saved command cannot switch profiles.

## Remaining rough-thesis research gap

The accepted interaction is to propose evidence-qualified omitted drivers, explain why they matter and then ask consequential questions, as described in [the thesis engine](THESIS_ENGINE.md#collaborative-refinement-of-rough-theses). The opted-in compiler requires evidence references on each proposed driver. The separate [research orchestrator](QUESTION_RESEARCH.md) now plans and gathers bounded headline metadata from a rough prompt. Automatic primary-source investigation and independent semantic source-fit selection remain unimplemented. A structurally valid citation proves attribution, not that the claim supports the proposed mechanism. Recorded tests do not establish research quality or instrument availability.
