# Monitoring runtime repair evidence

Date: 2026-10-09. Baseline: `b8f9e40a9c61de854fa279e7569d579abce0b7ca`. Scope: confirmed transaction, scheduling and wait-limit defects before the narrow internal [weekly workflow test](../docs/WEEKLY_WORKFLOW_TEST.md). This report describes verified local repairs, not continuous monitoring readiness.

## Findings and repairs

| Risk at the baseline | Repair | Verification |
| --- | --- | --- |
| Capture and compilation rejected caller atomic blocks but allowed manually disabled autocommit. Admission could remain uncommitted during external work, and a supposed postcommit observation could later roll back. | Require autocommit and no caller atomic block before capture admission/disposition/observation, compilation and work claim/completion. Each operation owns its transaction. | Rejection before queries, loader or provider calls; independent connections see committed model admissions, capture receipts and recovered observations. |
| Source-order traversal could wait on one source or repeatedly favor it. A fixed candidate cutoff could hide eligible work behind live leases. | Select oldest work globally; acquire source then work with skipped locked rows, and recheck state, lease and source head after protection. Scan the finite queue in chunks without a first-N eligibility cutoff. | Locked empty/busy sources and locked work do not block other progress; newer replenishment cannot take priority over older eligible work; more than 100 live leases do not hide pending work; token/head fencing still passes. |
| Socket-operation timeouts allowed a slowly arriving response to exceed the intended HTTP budget. | Shared HTTP transport uses a total deadline for connection and response reads, explicit asynchronous DNS and scoped resource cleanup. Public request middleware prevents an automatic second exchange after disconnect. | Real local GET/POST servers stall headers or body; each call times out. Real local DNS queries receive no response and cancel without executor threads or retained resolver objects. Disconnect tests observe one request. |
| PostgreSQL lock and statement waits had no project-level upper limit. | Configure positive connection, lock and statement limits. Defaults are 5 seconds to connect, 5 seconds per lock wait and 15 seconds per statement. Validate overrides and require lock timeout shorter than statement timeout. | Actual application settings are observed through PostgreSQL; independently blocked locks and running queries cancel under shorter test limits, then rollback leaves connections usable. |

## Regression traces

The traces below are exercised by integration tests with independent connections or real local sockets. They are not a new live desk demonstration.

1. A caller disables autocommit, then requests capture or compilation. The service rejects before database work or transport. Normal execution instead commits admission, then an independent connection observes it before the external callback runs. Capture commits a receipt, and a separate postcommit observation witnesses availability without claiming an exact commit timestamp.
2. One connection holds a source/work lock. A claim skips it and protects another eligible source/work pair, samples time after both locks, and commits a lease. Expired or replaced tokens and changed source heads cannot install a current result. Release of the held lock allows a later pass to claim that work.
3. A local server sends headers or body slowly. A 0.25-second transport budget interrupts the complete exchange within the test's 0.8-second tolerance. For a model POST, the adapter records `outcome_unknown`, retaining only safe response identifiers. There is no automatic replacement call. This does not prove remote cancellation or zero billing.
4. An independent database connection waits on a held lock or runs a deliberately slow query. PostgreSQL aborts that transaction at its configured limit; rollback allows a subsequent query. Earlier committed model admissions are not erased by a later completion failure.

See [capture transaction tests](../src/macro_agent/monitoring/tests/test_capture_transactions.py), [compilation tests](../src/macro_agent/theses/tests/test_compilation.py), [scheduling tests](../src/macro_agent/monitoring/tests/test_work_scheduling.py), [transport tests](../tests/test_http_transport.py) and [database deadline tests](../src/macro_agent/monitoring/tests/test_db_deadlines.py).

## Results and costs

- All 535 tests passed: 273 core/client/provider/transport and 262 PostgreSQL integration tests.
- Django checks, migration comparison, dependency compatibility and generated OpenAPI validation passed. No migrations or API schema changes were required.
- Two independent code reviews found no material issue in the repairs. The transport/provider/source subset also passed an independent 53-test run.
- Verification used recorded model responses, local HTTP/DNS servers and a disposable local PostgreSQL test database. No live provider calls, paid subscription or real model spend occurred. Local compute/storage cost was not measured.

New transport dependencies are hash-locked `aiohttp` 3.14.4 and `aiodns` 3.6.1 with their transitive dependencies. Existing locked dependency versions were preserved. The implementation uses the documented [total client timeout](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientTimeout), explicit [asynchronous resolver](https://docs.aiohttp.org/en/stable/client_advanced.html#resolving-using-custom-nameservers) and [middleware retry boundary](https://docs.aiohttp.org/en/stable/client_advanced.html#middleware-chaining).

## Limits and remaining work

The transport is synchronous at its calling boundary and owns a session/connection per request. Connection pooling and catalogue caching remain possible later efficiency work. Local cancellation and resource cleanup do not establish remote cancellation, provider charging behavior or live-source reliability.

Database limits apply per wait/statement, not to an entire application operation. Queue selection can scan a finite current snapshot linearly; its processing limit does not bound that scan. A skipped locked candidate requires a later pass, so an empty claim result is not proof that the durable queue is empty. Unattended runner backoff and timeout disposition still need implementation.

The fuller thesis pack, guided answer/refinement loop, source-fit review, cumulative context, sourced daily publication and continuous runner remain outstanding. Existing one-report results cannot be relabeled as daily briefs or current portfolio advice. The repair does not select production queue/hosting, a new data provider, materiality thresholds or detection targets. [Implementation status](../docs/IMPLEMENTATION.md) and the [weekly test plan](../docs/WEEKLY_WORKFLOW_TEST.md) retain these boundaries.
