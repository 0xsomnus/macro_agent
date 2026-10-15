# Fresh morning synthesis

A retained daily review can now receive one fresh model interpretation: an overview, effect on the approved thesis, separate effects on every open paper position, counter-case, watch questions and gaps. Exact source quotations and earlier analysis references remain distinguishable. News can support the thesis while creating near-term trade risk.

The deterministic digest remains independently usable. Synthesis does not replace its publication, change the approved thesis, create another notification intent or establish a verified macro regime.

## Try one review

Complete [model setup](THESIS_COMPILATION.md), enable the continuous desk and model-compilation gates, run migrations and restart the backend. Obtain a retained review UUID through the [daily review API](API_DEVELOPMENT.md#internal-daily-review-inspection) or runner inspection.

```sh
.venv/bin/python tools/review_morning.py --review-id REVIEW_UUID
```

Add `--driver-review` for explicit reassessment of every exact approved driver. Premise and mechanism support are separate, with evidence-linked competing/amplifying/offsetting hypotheses and a distinct thesis-progression assessment. Verified price observations remain unavailable and prospective entry remains `not_assessed` in this profile. It cannot infer causal correctness from direction or invent an entry plan. See [driver review](DRIVER_REVIEW.md).

The terminal displays the exact review before model selection. Choose a catalogue model and type `synthesise` to initiate one call. It writes a private journal and prints the command UUID before transmission. Review the source quotations, thesis/trade effects, uncertainty and counter-case. Price, consensus, venue mapping and current macro context remain explicit gaps unless present in the retained inputs.

Recover after interruption with a read-only lookup:

```sh
.venv/bin/python tools/review_morning.py --review-id REVIEW_UUID --command-id SAVED_COMMAND_UUID --recover
```

Recovery needs no provider key or catalogue, performs no POST fallback and never retries an uncertain call. A missing receipt is not evidence that the provider did no work. A new deliberate request requires a new command UUID and confirmation.

## Enable on a reviewed watch

Existing watches keep their current behavior. To add automatic synthesis, first enable [daily publication](DAILY_PUBLICATION.md), then pin the exact current synthesis configuration in the watch:

```python
from macro_agent.desk.synthesis import model_configuration
# Add these fields to the complete, explicitly reviewed watch configuration.
watch_configuration["daily_publication"] = {"fanout_limit": reviewed_fanout_limit}
watch_configuration["daily_synthesis"] = {
    "model_configuration": model_configuration(watch_configuration["provider"], driver_review=True)
}
```

Provider and model come from that watch's explicitly selected catalogue entry. Review the returned limits before versioned enrollment. An empty option or changed configuration is rejected. No implicit activation or model selection occurs.

The example opts into `driver-reviewed-daily-synthesis-v1`. Omit `driver_review=True` to retain the original synthesis profile. The exact schema/prompt pair pins the profile; its immutable context saves `driver_review: true`. Omission preserves old request hashes. Recovery uses the saved profile.

The daily worker saves and publishes the digest first, then uses the same fixed daily command identity for synthesis. Admission checks the live scheduler fence under protection. An expired/replaced lease cannot admit a fresh paid call. Recovery reads an existing attempt before catalogue, credentials or fresh admission. A failed or unknown result never triggers an automatic second call. Preflight failure retains a labelled digest fallback and completes that daily slot; the next day's slot is independent.

Compilation, news analysis and morning synthesis share the existing rolling owner/application admission limits and unfinished-attempt guard. The watch's `allowances.analysis_dispatches` continues to count news dispatches only. Call/token caps do not guarantee a dollar ceiling or prove remote cancellation. Capture has no dependency on synthesis availability. The operator job summary surfaces synthesis fallback and unresolved outcomes even when the daily digest slot completed.

## Currentness and authority

The immutable model context contains the exact review, original approved inputs, complete paper book and original report-head labels. Eligible retained reports can support exact citations; deferred reports cannot. Earlier completed analyses remain labelled model opinions, including stale dispositions. Every open position must appear exactly once. Historical closed positions remain context.

Sources, owner, thesis and briefs are protected before shared-budget admission and the trusted clock. No transaction spans catalogue or inference calls. Completion rechecks the approval, exposure, source contracts, included corrections and newer retained reviews. Changes preserve the original result while making its current disposition stale.

`GET /api/v1/theses/{thesis_id}/daily-brief/` exposes `current_synthesis` only for a successful, current synthesis of that exact protected published review. A null publication returns null synthesis. It does not fall back to historical output or make synthesis publication authority.

The model context is limited to 65,536 encoded bytes and output to 131,072 bytes. Oversized reviews reject without silent compaction. This may reject a digest that the larger deterministic review contract can retain. Limits are visible rather than assuming every retained review fits every model role.

## API and failures

All endpoints use authenticated owner scope. Writes require CSRF and strict JSON.

- `POST /api/v1/daily-reviews/{review_id}/synthesise/`, `command_id`, `expected_review_digest`, `provider_id`, `model_id`, and optional strict boolean `driver_review`.
- `GET /api/v1/daily-reviews/{review_id}/synthesis-commands/{command_id}/`.
- `GET /api/v1/daily-syntheses/{synthesis_id}/`.

Original outcomes are `synthesised`, `stale`, `failed`, or `outcome_unknown`; an admitted unfinished request reads as `running` until its deadline. Current disposition is separately `current`, `stale`, or `unresolved`. Unknown provider charges stay null. Failed synthesis leaves the digest independently available, unless its own governing dependencies have changed.

Recorded providers test mechanics and recovery, not live reasoning quality, source rights, external delivery or production readiness. The [weekly test](WEEKLY_WORKFLOW_TEST.md) still needs a reviewed real thesis, suitable permitted feeds and supervised live operation.

## Immediate attention remains outstanding

The opted-in profile implements structured driver reassessment. Its attention recommendation adds no publication or notification authority. Material explanation changes still need an immediate live publication route; a morning assessment alone does not meet that requirement. Verified instrument-price observations and numerical entry assessment also remain outstanding.
