# Test thesis compilation

The internal compiler turns your exact thesis into a suggested interpretation and separate challenge questions. It proposes drivers, preserves missing horizon and signposts, highlights unsupported mechanisms and checkable premises, and offers unverified counter-cases. It does not strengthen a claim simply by rewriting it fluently.

This is the text-grounded part of the [thesis engine](THESIS_ENGINE.md). Fact verification, current macro context, source manifests and investment analysis remain outstanding. Monitoring is not configured.

## Set up and run

Complete [local setup](GETTING_STARTED.md), including your account and database. From the repository root:

```sh
.venv/bin/python tools/desk_cli.py configure-models
```

Choose `nanogpt`, `openrouter` or `cheaperinference`, then enter its key at the hidden prompt. Setup creates `.local/models.env` with owner-only permissions and refuses to overwrite an existing credential file. It makes no provider request. Keys stay in the backend environment, outside API requests and audit records.

In the backend terminal, load your database configuration and the model configuration, then start the server:

```sh
set -a
source .local/native-db.env
source .local/models.env
set +a
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

For a fresh installation, substitute `.local/db.env` for the prepared checkout's database file. Restart an already running server after changing its environment.

In a second terminal:

```sh
.venv/bin/python tools/desk_cli.py happy-path --compile
```

Optional exact file input and private trace:

```sh
.venv/bin/python tools/desk_cli.py happy-path --compile \
  --thesis-file path/to/thesis.txt --output .local/compilation-trace.json
```

Search the fetched catalogue with `/search words`, choose a model number or exact ID, and review its output. Type `switch` to choose another model and initiate another call. Type `approve` only when the displayed text and interpretation represent your intent. Enter leaves the draft unapproved. You can also specify `--model exact/catalogue-id`; membership is still checked against the current catalogue.

After approval, the same walkthrough attaches your paper declaration and publishes a fictional recorded-news notice. That news is separate from compilation and receives no model analysis.

## Switch providers

Stop the backend. Preserve the existing ignored configuration under a new name, for example `.local/models-nanogpt.env`, then rerun `configure-models` for another router. Load its new file and restart the backend. Previously saved results retain the original provider, model, prompt, usage and interpretation.

The selection flow uses one normalized catalogue interface. Each adapter handles its own endpoints, credentials and price units. A model ID belongs to its provider's catalogue; identical-looking IDs across routers are not assumed interchangeable. The request pins both provider and model, and a changed provider requires refreshed selection.

## What to inspect

- Exact text remains unchanged, including file whitespace, Unicode and line endings.
- Each extracted driver, horizon or signpost has an exact quotation from your thesis. This proves attribution, not semantic fidelity.
- Missing intent remains empty or null. Agent additions, introduced assumptions, questions and counter-cases appear separately.
- Checkable premises are verification questions. Model knowledge alone cannot create a sourced factual conflict.
- The proposal is labelled `model_compilation`. The current approval remains active until you explicitly approve the new interpretation's exact hashes.

Try an incomplete gold thesis, a conditional currency thesis, and a claim such as "Rate cuts always lift stocks." Judge whether the interpretation preserves your meaning, the questions expose consequential gaps, and the counter-case helps you reason. Successful parsing and contract tests do not establish analytical usefulness.

For a focused one-thesis exercise with a literal baseline and private feedback journal, follow [compilation review](COMPILATION_REVIEW.md). It makes no approval, position or news request.

## Limits and failures

One explicitly initiated attempt makes at most one model POST, with no automatic retries or model fallback. Configurable research defaults are 3,000 output tokens, a 45-second transport timeout, 20 admissions per account per rolling day and 100 across the local application. Compilation and [news analysis](NEWS_ANALYSIS.md) share that allowance. These are operating limits, not market-materiality thresholds or guaranteed dollar caps. Failed calls and uncertain admissions count toward the limits. Only one unfinished, unexpired attempt per account is admitted across both roles at a time. Deadline expiry does not prove remote cancellation.

Server settings are `MACRO_COMPILATION_MAX_OUTPUT_TOKENS`, `MACRO_COMPILATION_TIMEOUT_SECONDS`, `MACRO_COMPILATION_OWNER_ATTEMPTS_PER_DAY` and `MACRO_COMPILATION_ATTEMPTS_PER_DAY`. Each attempt records the settings used. The request deadline additionally prevents late installation; a transport timeout cannot prove the upstream request was cancelled or unbilled.

| State | Meaning |
| --- | --- |
| `compiled` | Validated model document saved, with a suggested draft interpretation. Check its current disposition before approval. |
| `stale` | Thesis state changed during inference. Retain the result as history without replacing the draft. |
| `failed` | Provider failure, unsupported response or invalid model document. Existing text and approval remain intact. |
| `running` | Admission exists without a recorded result, before its deadline. Reading it makes no call. |
| `outcome_unknown` | Timeout, expired admission or missing response. Provider processing and cost may have occurred. Repeating the same command makes no further call. |

The internal admin exposes owner-scoped, read-only attempts and results. Original dispositions remain immutable; a formerly compiled result can cease to be the current draft. A new attempt requires a new explicit command. Crash recovery does not silently issue another paid request.

Advertised catalogue rates and usage-derived estimates are separate from reported charges. Missing prices, usage or charges remain null. Estimates can differ because of caching, reasoning, provider routing or pricing changes. Provider capabilities and workspace processing are advertised behavior, not locally proved guarantees. We do not opt into web search, tools, experiment routing or prompt optimizers.

## Adapter references and verification

The adapters use the documented [NanoGPT catalogue](https://docs.nano-gpt.com/api-reference/endpoint/models) and [chat API](https://docs.nano-gpt.com/api-reference/endpoint/chat-completion), [OpenRouter catalogue](https://openrouter.ai/docs/api/api-reference/models/get-models) and [chat API](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request), and [Cheaper Inference API](https://www.cheaperinference.com/docs). NanoGPT catalogue rates use USD per million tokens; OpenRouter token rates are converted to that unit; Cheaper Inference rates name the per-million fields. Missing units are never guessed.

Internal configured credentials follow [ADR 013](ADR/013-internal-byok-and-cost-boundaries.md). External BYOK, adaptive routing and subscription accounting remain deferred. Development-only enablement requires local settings, a development/test database and `MACRO_ENABLE_MODEL_COMPILATION=1`. The strict session/CSRF API follows [ADR 017](ADR/017-drf-and-openapi-boundary.md). [Implementation evidence](IMPLEMENTATION.md) distinguishes fixture verification, public catalogue checks and live inference.
