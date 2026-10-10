# Review one captured report against your thesis

This internal terminal exercise connects retained news to your exact approved thesis and attached paper trades. You choose a source and model; the backend selects one report, makes at most one inference call, then stops for your review. It does not run continuously, amend your thesis, change trades or publish an alert.

The [continuous runner](CONTINUOUS_RUNNER.md) separately supports explicit [cumulative context](CUMULATIVE_CONTEXT.md) opt-in. This manual terminal/HTTP flow remains v1 single-report analysis; saved reads preserve v2 results produced by cumulative watches.

The initial example is fictional: policy easing may support a medium-term equity thesis, while reported funding stress could create a separate near-term risk for an attached NQ long. The purpose is to test whether the model considers the view and the trade independently, with assumptions and counter-cases visible.

## Prepare the backend

Complete [local setup](GETTING_STARTED.md) and [model configuration](THESIS_COMPILATION.md). If a provider is not configured yet, run:

```sh
.venv/bin/python tools/desk_cli.py configure-models
```

Choose your provider and enter its key through the hidden prompt. Restart the backend after loading its configuration. In the prepared checkout, run these commands from the repository root:

```sh
set -a
source .local/native-db.env
source .local/models.env
set +a
export MACRO_ENABLE_NEWS_ANALYSIS=1
export MACRO_ENABLE_MONITORING_PROOF=1
export MACRO_ALLOW_SYNTHETIC_SETUP=1
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
.venv/bin/python manage.py monitor_capture --fixture fixtures/news_analysis_case.json --fixture-source fixture-divergence
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

Use `.local/db.env` instead for a separately configured development checkout. Model setup writes `MACRO_ENABLE_MODEL_COMPILATION=1` into `.local/models.env`, which enables the existing catalogue route. The news-review gate also requires local settings and a database ending in `_dev` or starting with `test_`. The synthetic gate is required for fictional sources.

## Approve a thesis, then review one report

An existing approved thesis is sufficient. To create one with an attached trade, open another terminal and run:

```sh
.venv/bin/python tools/desk_cli.py happy-path
```

For the fictional example, try your own version of "Policy easing may support equities over six months", a matching driver and thesis horizon, then attach a paper NQ long. Position quantity/unit and horizon can remain missing. The walkthrough shows the exact approval preview and prints a thesis UUID after `Draft saved:`. Its separate recorded-news notice remains a fictional mechanics example.

Copy that thesis UUID into:

```sh
.venv/bin/python tools/review_news.py --thesis-id YOUR_THESIS_UUID --source fixture-divergence
```

Log in and inspect the approved text, interpretation and complete attached-thesis paper book. Choose an explicit model from the provider-independent catalogue. Type `run` to initiate one request. The selected provider receives those private inputs and one retained source report; the call may incur a charge.

The backend selects the oldest received current report not previously attempted for this approval and exposure book. You do not need to select an article manually. Selection is a test-queue ordering, not a materiality ranking. Each invocation stops after one result; another invocation may advance to another unattempted report.

After a valid current response, type `review` to record whether attribution, independent routes, uncertainty and usefulness are `good`, `poor` or `uncertain`. These are your judgments, not an automated quality score. `--model exact/catalogue-id` preselects a model. `--output .local/my-news-review.jsonl` chooses a new owner-only journal; existing files are not overwritten. The default journal also stays under ignored `.local/`.

## Read the result

| Output | Meaning and limit |
| --- | --- |
| Attributed report claims | Exact quotations from the retained title or content, pinned to a source revision. Attribution does not establish truth or completeness. |
| Thesis route | A possible connection to approved meaning, considered separately from open-trade effects. |
| Trade route | A possible connection to supplied open declarations. Closed declarations remain historical input and cannot be referenced as open exposure. |
| Hypotheses | Proposed transmission, introduced assumptions, horizon or explicit absence, uncertainty, counter-case and observable signposts. Causal correctness remains unverified. |
| Trader questions | Consequential missing intent or context to discuss before drawing stronger conclusions. |
| `not_identified` | No connection identified within this limited report and input. It does not establish non-materiality or resolve monitoring work. |

The context includes the complete latest attached-thesis book, including closed declarations, within the existing 200-record bound. This is not the user's whole portfolio. Where present, it also preserves the exact approved review card, including original text, attributable answers, extracted intent, proposals and gaps. Review approval does not turn proposed assets, causal paths or scenarios into trader belief or verified facts. The compiler's own evidence remains explicitly unavailable; retained report quotations are separate inputs.

The 65,536-byte prompt-context limit covers the whole news context and rejects oversized input before paid admission. The compiler permits cards up to 524,288 bytes, so a valid compilation may be too large for this news workflow. Inputs and the exposure book are never silently truncated. Instrument mapping remains user-declared and unverified.

There is no verified current macro regime, broad news coverage, consensus or market-reaction context. The model must keep unsupported portfolio effects and causal paths hypothetical. Quotation validation proves exact attribution and valid identities, not semantic fidelity, investment usefulness or absence of unsupported reasoning. Review the explanation as well as its citations.

## Recovery, currentness and costs

Permission withdrawal blocks new source use. If inference was already admitted and dispatched, completion retains its returned document and provider metadata under the source lock, with stale disposition when permission changed. Completion cannot backdate the permission observation. A failed or uncertain result remains failed or uncertain; withdrawal and saved-command replay never authorize another model call. Retention of already admitted history is separate from permission to fetch or process new source inputs.

Admission is committed before inference, and network calls run outside database locks. The saved attempt pins approved meaning, the complete exposure book, source revision/contract, prompt/schema versions and provider/model metadata. Protected operations acquire source, owner, thesis and budget protection in that order. Input observations are conservative preparation evidence, not exact admission commit times.

The original result and its current disposition remain separate. A changed source revision, source contract/permission, approved meaning or paper book makes earlier analysis stale. A draft-only change leaves unchanged approved meaning in force. Current disposition is read from a coherent snapshot, so historical success cannot reactivate obsolete inputs. Completion cannot be recorded before protected source or exposure state it has observed.

| State | What to do |
| --- | --- |
| `analysed` and current | Review the response and its retained context. This creates no alert or thesis amendment. |
| `stale` | Inspect the changed dependencies; keep the old result as history. |
| `failed`, `running` or `outcome_unknown` | Inspect the attempt. Missing or invalid output leaves relevance unresolved and receives no quality grade. |
| `queue_empty` | No unattempted current report exists for these inputs. Earlier failures, unresolved work and coverage gaps may remain. |

Failed, unknown or interrupted attempts are not automatically issued again for the same pinned inputs, even when you choose another model. A changed source revision, approval or exposure book may admit a new investigation. Replaying a saved request, including an earlier empty-queue response, cannot spend again or select later news. Identical recapture does not create a new source revision.

The journal saves request identity before sending the POST. If a response is lost, find `command_id` inside the journal's `analysis_requested.request` record and inspect it:

```sh
.venv/bin/python tools/review_news.py --thesis-id YOUR_THESIS_UUID --recover-command SAVED_COMMAND_UUID
```

Recovery logs in, reads the saved receipt and displays historical context with current disposition. It does not fetch a model catalogue, make an inference call or fall back to POST. It works without a configured model key. An absent or inaccessible receipt is opaque; it does not establish the earlier outcome or cost. Save a new private journal with `--output` if desired. The journal contains private context and responses, but no key or password. Inspection uses the authenticated HTTP API, and the client does not access the database directly.

Compilation and news analysis share defaults of 20 owner admissions and 100 aggregate admissions per rolling 24 hours. Only one unexpired admitted attempt per owner is allowed across both roles. Deadline expiry does not prove a remote call stopped. The default output cap is 3,000 tokens and provider timeout 45 seconds, subject to the existing [configured limits](THESIS_COMPILATION.md#limits-and-failures). Reported charges and usage-derived estimates remain distinct; absent costs stay unknown. Call and token limits are not a guaranteed dollar ceiling. Capture remains independent of this analytical allowance.

Provider transport applies a total HTTP deadline, including slowly arriving headers/body, and prevents automatic reconnect retries. An ambiguous model POST remains `outcome_unknown`. Database wait limits can also abort completion after admission; read-only recovery by command ID remains the safe first step. Neither local timeout proves remote cancellation or zero billing. See [runtime repair evidence](../artifacts/monitoring-runtime-repair-2026-10-09.md).

## Try the official source later

Capture the narrow [reviewed Fed feed](MONITORING_PIPELINE.md#try-the-narrow-official-feed), then use `--source fed-press` instead. Only retained permitted feed fields are sent; linked articles are not fetched. A successful snapshot or analysis does not prove timely continuous coverage. Fictional sources and the reviewed official feed are the currently permitted internal inputs; broader sources require their own rights review.

Recorded responses establish mechanics only. Live model quality, recurring operation, broad materiality screening, global macro context, correction protection for published briefs and external delivery remain ahead. See the [monitoring plan](MONITORING_SLICE.md) and [roadmap](ROADMAP.md).

For inspection, the relevant code is the [domain contract](../src/macro_agent/domain/news_analysis.py), [protected context](../src/macro_agent/monitoring/news_context.py), [analysis service](../src/macro_agent/monitoring/analysis.py), [API views](../src/macro_agent/api/news_analysis_views.py) and [terminal review](../tools/review_news.py).
