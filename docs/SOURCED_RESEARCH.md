# Compile against retained sources

You can now give thesis compilation a selected packet of captured evidence. The model still preserves your exact text and separates your intent from its own proposals. It can quote retained reports, identify a possible factual conflict, and ask which premise, date or series you meant. A quotation proves attribution, not that the source is true or that its statement supports the model's conclusion.

This is a bounded research step, not an autonomous investigation or a verified macro regime. Source selection is currently manual. No source is fetched by the compiler.

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

Choose a model from the configured provider's catalogue and confirm the request. Inspect model-identified factual conflicts before its assessment. Extracted intent must still quote your own text or saved answers; source passages cannot stand in for your intent. Refinement and exact approval use the existing terminal flow. The full sourced review card is included in the interpretation hash.

The initial manual flow needs no model call. A single-screen research onboarding flow remains future work. Each displayed factual conflict also has a matching retained refinement question, so you can answer it before explicitly recompiling.

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

The strict session/CSRF endpoints are:

- `POST /api/v1/theses/{thesis_id}/evidence/`, exactly `command_id` and `revision_ids`.
- `GET /api/v1/theses/{thesis_id}/evidence/{context_id}/`.
- `GET /api/v1/theses/{thesis_id}/evidence-commands/{command_id}/`.
- Existing `POST /api/v1/theses/{thesis_id}/compile/`, with optional `evidence_context_id`.

Legacy text-only requests retain their card version and hashes. New sourced cards use `thesis-review-card-v2`; factual conflicts remain `model_identified`, never verified corrections. Costs, unknown outcomes and explicit paid retries follow [compilation](THESIS_COMPILATION.md).
