# Review one thesis compilation

Use this exercise to judge whether the compiler preserves your meaning and asks useful questions. It does not measure trading returns, predictive skill or live monitoring. Each invocation handles one thesis and initiates at most one compilation request, with no automatic retry or approval.

## Start

Complete [model setup](THESIS_COMPILATION.md), load your database and `.local/models.env` in the backend terminal, and start the server. Keep your key in that local setup, not in a chat, thesis file or review journal.

List the eight synthetic examples without a server or model key:

```sh
.venv/bin/python tools/evaluate_compilation.py --list
```

Try a deliberately weak thesis:

```sh
.venv/bin/python tools/evaluate_compilation.py --case es-universal-rate-cut
```

Or use your exact UTF-8 text file:

```sh
.venv/bin/python tools/evaluate_compilation.py --thesis-file path/to/thesis.txt
```

The terminal shows the exact input, a deterministic baseline and review questions. Log in, select a model from the current generic catalogue, and type `run` to initiate one request. `--model exact/catalogue-id` can preselect an explicit model. Cancel before `run` to avoid creating a draft or making an inference call.

After a valid current response, type `review` to record feedback. Rate each dimension `good`, `poor` or `uncertain`, then choose whether the model, baseline or neither clearly helped more. Add a concrete failure example where possible. Ratings are your judgments about the output; the tool does not grade your thesis.

No approval, paper trade or recorded-news notice is created. To approve and attach a trade separately, use the existing [happy path](THESIS_COMPILATION.md#set-up-and-run). Each new invocation creates a separate unapproved research draft; it does not silently amend an earlier thesis.

## What the comparison means

| Dimension | Review question |
| --- | --- |
| Intent fidelity | Were the original qualifiers, horizon and missing intent preserved? |
| Facts and assumptions | Were unverified premises and agent additions kept separate from user intent and verified facts? |
| Consequential questions | Could the questions change the mechanism, timing or invalidation, or are they generic? |
| Counter-case | Is the competing path relevant, qualified and distinct from a factual correction? |
| Usefulness | Did review become easier or reasoning become more explicit, even if conviction fell? |

The baseline echoes exact prose and reads only explicit line labels `Driver:`, `Horizon:` and `Invalidation:`. It cannot interpret free prose, verify facts or produce macro analysis. Unknown fields mean the parser could not resolve them, not that the trader omitted them. Conflicting horizon labels remain ambiguous. This transparent, limited and unblinded comparison does not establish model superiority.

The [synthetic pack](../fixtures/compilation_cases.json) covers the seven paper-pilot candidates and an embedded-instruction case. Case instruments are test labels, not verified exposure mappings. Questions are review prompts, not a factual answer key. A useful result on these examples does not pass the full source-backed [thesis engine](THESIS_ENGINE.md) or [roadmap](ROADMAP.md) gates. You can provide your own examples to avoid judging only cases selected by the developers.

## Private record and failure behavior

A new owner-only JSONL journal is created under ignored `.local/` by default. Use `--output .local/my-review.jsonl` for a new explicit filename. Existing files and symlinks are never overwritten. The journal contains exact input, the baseline, canonical pack hash, rubric, request identity, returned result, costs and each completed review dimension. It contains no password or model key. Treat it as private research material.

The file is flushed before transmitting the compilation request. If local journaling fails first, that request is not sent. If a response is lost, its outcome is not established and the saved request identity helps locate the backend admission through owner-scoped internal inspection. No automatic resubmission occurs. A malformed or severed final journal line can be discarded during manual inspection; earlier complete lines remain separate records. This journal is not the authoritative database or exact durable-known-at evidence.

Failed, stale, running and unknown attempts receive no quality grade. A formerly compiled response that is no longer the current draft is also not reviewable as current output. An interrupted review retains the response and completed ratings without manufacturing a completed review. Choosing not to review leaves ratings unset.

Calls use the existing [compilation limits](THESIS_COMPILATION.md#limits-and-failures). Unknown charges stay unknown; one-call and token limits are not guaranteed dollar caps. Reported charges and usage-derived estimates remain distinct. No live inference was used to verify this command; tests and the terminal smoke exercise use recorded responses.

## Next evidence gate

Review representative cases one at a time, keeping model/provider, costs, latency, failures and concrete usefulness observations. The roadmap calls for five to ten representative theses, including your own inputs. This is exploratory calibration; no numeric model ranking, passing threshold or automated learning is selected. Freeze a separate evaluation protocol before making comparative claims. Current macro context, factual verification and monitoring remain unconnected.

The next monitor is described in [MONITORING_SLICE.md](MONITORING_SLICE.md); [SOURCE_OPTIONS.md](SOURCE_OPTIONS.md) compares acquisition options before a provider or licence is chosen.
