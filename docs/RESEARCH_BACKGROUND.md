# Background research and search budgets

Updated 2026-10-21. This internal increment lets an owner delegate the remaining work of one already-planned investigation. A separate operator process resumes due source work and the one remaining compilation call. Research does not enroll monitoring or create an approved thesis, position or notification.

## Enroll one saved investigation

Complete [question research setup](QUESTION_RESEARCH.md) and [model setup](THESIS_COMPILATION.md). In the configured backend and worker terminals, enable:

```sh
export MACRO_ENABLE_MODEL_COMPILATION=1
export MACRO_ENABLE_MONITORING_PROOF=1
export MACRO_ENABLE_RESEARCH_DISCOVERY=1
export MACRO_ENABLE_RESEARCH_BACKGROUND=1
.venv/bin/python manage.py migrate --noinput
```

Restart the backend after setting its environment. Start research through the existing terminal flow. If a recovery-enabled investigation has a saved plan and unfinished eligible work, use its displayed ID:

```sh
.venv/bin/python tools/research_background.py --run-id RESEARCH_UUID --enroll
```

The session client shows the exact saved question, plan, selected model and limits before asking for background consent. It saves a command ID in a private journal before sending the request. This delegation permits the remaining compilation call, which may incur a model charge. It cannot change the plan, model, source policy or private-model allowance. Already admitted uncertain model calls are never resent.

Enrollment is durable, but does not install or launch an operating-system service. In a separate terminal with the database/model environment loaded, run one bounded tick:

```sh
.venv/bin/python manage.py research_run --owner OWNER_UUID --run-id RESEARCH_UUID --once
```

For repeated due checks, omit `--once` and set an explicit local idle interval:

```sh
.venv/bin/python manage.py research_run --owner OWNER_UUID --run-id RESEARCH_UUID --idle-seconds 5
```

Optional `--max-ticks` limits the process. Idle checks inspect durable state; a source request is admitted only when eligible. Stopping the process preserves enrollment and research. Restart uses the same command/admission identities. Terminal states stop the loop. No production queue, supervisor or machine-start service is selected here.

## Inspect or revoke

```sh
.venv/bin/python tools/research_background.py --run-id RESEARCH_UUID --status
.venv/bin/python tools/research_background.py --run-id RESEARCH_UUID --revoke
```

Inspection makes no catalogue, source or model request and needs no model key. Revocation prevents new worker admissions and fresh dispatches. It does not prove upstream cancellation, erase returned results or revoke the trader's ability to inspect or explicitly continue the saved investigation. A retained enrollment cannot be silently reset or replaced. Saved command retries do not resume work.

The session API exposes owner-scoped `GET` and `POST /api/v1/research/{run_id}/background/`, plus `POST /api/v1/research/{run_id}/background/revoke/`. Enrollment accepts exactly `command_id` and `expected_request_digest`; revocation accepts exactly `command_id`. Writes require CSRF and reject duplicate keys, unknown fields and coercion. No HTTP endpoint runs a worker tick. Saved reads and revocation remain available when the separate background flag is disabled, within the existing internal research gates.

## Execution boundaries

- Initial planning stays synchronous. Enrollment requires its retained successful plan and explicit source recovery.
- The pinned internal policy uses a 180-second lease and at most twelve lease claims. Exhaustion blocks visibly and preserves complete history. These are experiment bounds, not a production service guarantee.
- The original thirty-minute acquisition deadline and source-attempt limits remain fixed. Captures already committed can still be adopted afterward; enrollment does not replenish any allowance.
- Protect provider, sorted sources, owner, thesis and job in that order for source admission. Compilation protects sources, owner, thesis, shared model budget and job. Control operations protect owner, thesis and job. Sample the trusted clock after the complete protection set; no lock spans remote work.
- Each worker source/compilation admission has immutable exact lease provenance. Check the live lease inside admission and immediately before a fresh remote call. These checks authorize local work at observed instants; they cannot atomically fence an upstream API or prove remote cancellation. Late receipts remain history; an old worker cannot replace newer scheduling state.
- The selected model configuration is pinned at enrollment. Configuration changes, withdrawn permissions, stale inputs, failed/uncertain paid work and exhausted bounds stop visibly. There is no silent substitution, new plan or paid retry.

## Search spending

The user approved **one shared USD 10 budget per UTC calendar month**, plus **USD 0.10 per investigation** for its lifetime across resumes, providers and month changes. Model inference, subscription fees and other operating costs are separate.

The internal ledger stores exact integer USD millionths. A named active staff operator can retain a bounded price contract; it proves a reviewed price record, not source rights or activation. No price contract is seeded. Before a paid lookup, its stable call ID reserves the known maximum charge against both ceilings atomically. Concurrent owners and providers share the same monthly pool. Settled actual charges and the full value of unresolved reservations count toward capacity.

An uncertain charge keeps its reservation, including across restart and month changes. Explicit named-operator reconciliation requires retained charge evidence; zero requires explicit provider confirmation. Immutable retries cannot reset amounts or move an old reservation into a new month. Budget exhaustion preserves saved work and blocks another reservation.

A replayed reservation is saved accounting evidence, not permission for another remote request. Its month is the UTC reservation month; provider invoice timing is not established by that field. Future paid transport must bind each unique dispatch and its accounting period to the reservation before making an end-to-end spending claim.

**No paid search adapter is connected to this ledger yet.** The reservation invariants can be tested independently, but an operational end-to-end spending guarantee still requires a suitable provider contract, pinned maximum pricing and transport integration. GDELT remains the existing free metadata experiment. Background execution adds neither a paid fallback nor live availability.

## Remaining validation

Recorded tests and an isolated trace verify mechanics, including capture restart and no resend of paid admissions. They do not establish GDELT availability, source completeness, model usefulness or continuous desk coverage. Suitable fallback rights, actual paid transport integration, supervised live research and production supervision remain outstanding.

See the [readable proof](../artifacts/research-background-trace-2026-10-21.md), [exact records](../artifacts/research-background-trace-2026-10-21.json) and [API schema](../artifacts/research-background-openapi-2026-10-21.yaml).
