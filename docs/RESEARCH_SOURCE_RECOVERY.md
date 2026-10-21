# Resume research after source failure

Updated 2026-10-20. This internal path preserves a paid research plan and completed source searches while retrying a failed GDELT lookup. It does not repeat an admitted planning or compilation call.

## Run from the terminal

Complete [question research setup](QUESTION_RESEARCH.md), apply migrations and restart the backend. New terminal research explicitly enables source recovery:

```sh
.venv/bin/python tools/research_question.py --question "Your research question" --wait
```

The terminal shows the exact question, selected model and bounds before confirmation. It follows saved source waits for up to five minutes, then returns with the research ID if work is still pending. Use `--wait-seconds` to choose one to 1,800 seconds. Each local wait is interruptible; stopping the terminal preserves saved work.

Resume later using the same plan and successful searches:

```sh
.venv/bin/python tools/research_question.py --continue-run RESEARCH_UUID --wait
```

Without `--wait`, the command advances eligible work once and displays its next eligible time. Explicit [background enrollment](RESEARCH_BACKGROUND.md) can now delegate remaining work to a separate operator process. `--show-run` and `--recover-command` remain read-only and reject `--wait`. A lost HTTP response stops the client; it does not automatically repeat a request that could have admitted compilation.

Use `--one-shot-sources` only when starting a new run to reproduce the legacy contract. A saved run cannot switch policies. The HTTP start endpoint enables recovery only with strict `source_recovery: true`; omission preserves the old request identity and one-shot behavior.

## Pinned bounds

| Control | Internal value |
| --- | --- |
| Named questions | At most three |
| Source attempts per question | At most three, including the first |
| Complete source-attempt maximum | Nine, with at most twelve selected reports |
| Model admissions | One planning and one compilation, unchanged |
| Per-exchange elapsed deadline | Twenty seconds |
| Minimum spacing | Five seconds across recovery-enabled GDELT admissions |
| Failure backoff | Thirty then sixty seconds before later attempts |
| Source-work deadline | Thirty minutes from the saved run's creation |

These are conservative experiment bounds, not a published GDELT quota or an availability promise. Successful responses end that question's search. Timeouts, unavailable transport/service and rate limits can retry; malformed data, permission withdrawal and other nonretryable failures stop visibly. Failed searches never become evidence that nothing relevant exists.

`Retry-After` can extend cooldown beyond the local backoff or the run's deadline. A long valid delay is never shortened to force a retry. Provider cooldown is durable and monotonic, including late replies from superseded reservations. Concurrent continuation cannot admit a duplicate source attempt. A known cooldown that already makes acquisition impossible stops a new run before paid planning.

The shared coordinator covers recovery-enabled application runs. Legacy one-shot flows, standalone diagnostic commands and traffic outside this application do not participate. Avoid concurrent diagnostics while testing paced recovery. Shared network egress may also be affected by other callers, so application pacing cannot establish upstream availability.

## Saved state and authority

Each source attempt has an immutable outcome and exact capture binding. Reads expose failed attempts, safe cooldown metadata and the next eligible time. Restart adopts retained acquisition receipts and committed captures before considering another GET, including when a lease expired after capture.

Final `retained-source-evidence-v3` packets carry `question-research-context-v2`: the pinned policy, ordered attempt history, original failure digests, complete query outcomes and exact successful selections. This remains untrusted workflow data, separate from trader intent and quotable source claims. The complete packet keeps its byte bound. Contextual prompts and approval bind that exact version. Legacy packets, prompts, hashes and saved-command behavior remain unchanged.

The explicit shared provider reservation precedes source, owner and thesis protection in recovery admission/result paths. The trusted clock is sampled after protection. No database lock spans network or inference work. Leases fence retained authority; they do not prove cancellation at the upstream server.

## Source diagnosis and fallback

A separate diagnostic with a thirty-second deadline received HTTP 429 after 11.76 seconds. Earlier ten-second requests could not expose that slow response. This confirms rate limiting on that request; it does not explain every earlier TLS timeout. GDELT [documents DOC API rate limiting](https://blog.gdeltproject.org/ukraine-api-rate-limiting-web-ngrams-3-0/), without establishing our current effective quota.

The no-model diagnostic can inspect the newer twenty-second policy explicitly:

```sh
.venv/bin/python manage.py research_check_source --query "helium supply" --recovery-policy
```

It remains one uncoordinated operator GET with no database write or model call. It does not run a retry loop. Safe server cooldown seconds are displayed when supplied; remote bodies and header text are not.

Both resumable waiting and explicitly configured fallback are accepted goals. **No alternative discovery provider is configured or activated yet.** Fallback still needs a selected source contract covering acquisition, evidence retention and model processing. The [replacement review](../research/research-source-recheck-2026-10-19.md) records current candidates and constraints. The Fed feed supports a narrow selected-packet test; it cannot automatically replace an unrelated commodity or company search.

The eventual fallback must retain the original failed attempts and exact research plan, identify the chosen source and scope, and admit a separately bounded lookup. It cannot silently replace sources, rerun paid planning, conceal coverage gaps or enable monitoring. Partial synthesis remains a separate open choice rather than an automatic response to missing evidence.

The [recorded restart proof](../artifacts/research-recovery-trace-2026-10-20.md) demonstrates rate limiting, early continuation without a request, capture interruption and later adoption without another lookup. It uses no real model/source calls.

## Approved pilot search budget

Confirmed by the user on 2026-10-20:

| Limit | Amount |
| --- | --- |
| Monthly search API usage | USD 10.00 |
| Search API usage per investigation | USD 0.10 |

These limits cover search API usage only. Model inference, subscription fees and other operating costs are separate. This is permission to use a suitably configured paid fallback within those limits, not approval of a particular provider or plan.

The required budget guard must reserve a known maximum charge before each paid request and enforce both limits atomically across concurrent jobs. Retries and fallback requests consume the same investigation allowance; continuation and restart cannot replenish it. Uncertain charges remain reserved until reconciled. A request without a defensible maximum price cannot be admitted. Exhausted budgets leave saved work paused with a visible reason.

The user clarified on 2026-10-21 that the monthly limit is **one shared pilot pool using UTC calendar months**. An investigation's lifetime limit does not reset at a month boundary.

**Current status:** the [internal ledger and background runner](RESEARCH_BACKGROUND.md) implement reservations and due-work recovery. No paid search transport is connected, so a live end-to-end monetary guarantee remains unverified. Provider price/billing rules, retention/model-processing terms and actual fallback integration still precede paid activation. Existing model-call counts do not cap inference spending. No subscription or paid search request was made by accepting this budget.
