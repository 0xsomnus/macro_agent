# Paper positions and publication context

Implemented 2026-10-05 under the existing authority and publication rules in [ADR 015](ADR/015-auditable-publication.md) and [ADR 017](ADR/017-drf-and-openapi-boundary.md). The trader confirmed instrument, direction, optional quantity/unit and horizon. This increment stores those declarations and connects committed approved context to fictional event briefs. It does not configure continuous monitoring.

## Declaration and authority

The required declaration is `underlying` and `direction` (`long` or `short`). Product ID, venue, expiry, quote currency, horizon, quantity and quantity unit may be null. Every field is present in the wire object; null means absent, without an inferred value. Quantity and unit are supplied together or both null. Quantity is an exact positive fixed decimal string with at most 28 digits and 12 fractional places, preserving trailing zeroes. No arithmetic, price, P&L, leverage or risk calculation is implied.

`mapping_status: user_declared_unverified` is permanent in this slice. An asset label is not proof of a validated tradable instrument or source coverage. `missing_fields` exposes missing product, venue, quote currency, horizon and sizing. Null expiry is permitted without declaring it a gap, because the product type is unvalidated. Later product validation must distinguish a missing futures expiry from an inapplicable spot expiry.

A position belongs to the thesis aggregate. Its original and each subsequently reviewed approval are recorded separately. New commands require the exact current approval; revising or closing additionally compares the displayed position revision. Approval amendments preserve the existing position declaration and its earlier review provenance. They do not silently reapprove the position or rewrite its recorded attachment. A closed position is terminal; a new paper entry needs a new position record.

The session supplies the actor. Missing and foreign IDs share an opaque 404, including for superusers. Duplicate JSON keys, unknown fields and type coercion are rejected. Exact command retries return the immutable receipt and current disposition, without reopening a closed position or reactivating old state. Position command identities are unique per owner within the position-command namespace, separate from thesis commands.

## Routes and request

Use the [session/CSRF runbook](API_DEVELOPMENT.md). The [current desk schema](../artifacts/desk-openapi.yaml) is generated from the explicit serializers.

| Method | Route | Purpose |
| --- | --- | --- |
| GET, POST | `/api/v1/theses/{id}/positions/` | List or attach private paper declarations |
| GET | `/api/v1/positions/{id}/` | Current declaration and review provenance |
| POST | `/api/v1/positions/{id}/revisions/` | Complete replacement declaration, preserving history |
| POST | `/api/v1/positions/{id}/close/` | Explicit terminal closure |
| GET | `/api/v1/positions/{id}/history/` | Consistent read-only effective-time history |

Example attachment, replacing command and approval UUIDs with actual reviewed values:

```json
{
  "command_id": "c7120c74-5325-42b4-b6af-0fe66a874af8",
  "expected_approval_id": "901280fa-cb62-4243-8d9d-cdfe63cb4ac2",
  "position": {
    "underlying": "XAU",
    "direction": "long",
    "product_id": null,
    "venue": null,
    "expiry": null,
    "quote_currency": null,
    "horizon": "Several weeks",
    "quantity": "1.00",
    "quantity_unit": "declared units"
  }
}
```

A revision uses the same shape plus `expected_revision`. Closure uses only `command_id`, `expected_revision` and `expected_approval_id`. Lists cap pages at 100. History caps transitions at 100, preserves accepted audit order even when timestamps tie, and reports truncation. The internal thesis limit is 200 lifetime position records, including closed records. It bounds complete exposure-book reads rather than silently dropping older exposure. Retention and cursor-based exports require review before external use.

## Protected publication and time

Bound publication operations acquire owner, thesis and brief protection. Exposure commands acquire owner, thesis, position and all bound briefs in sorted order. Approval changes acquire owner, thesis and all bound briefs. The trusted clock is sampled only after those protections. Model and network calls remain outside the transactions.

An approval or accepted exposure change atomically marks every bound brief `pending`, clears its current assessment, cancels pending notification intents and supersedes old pending reassessment work. Original assessments and command decisions remain immutable. Publication and local delivery acknowledgement fail closed while context is pending. Draft proposals preserve the current approval and its brief.

[context_binding.py](../src/macro_agent/persistence/context_binding.py) admits already committed approved text, interpretation, approval and the complete exposure book. It verifies their hashes and stores resolved content with four governing pins. Admission requires its own outermost transaction; a caller's uncommitted thesis cannot be admitted. A separate refresh observes current committed state and durably queues reassessment. Future workers must reconcile pending bindings; no queue implementation is selected here.

`input_observed_at` conservatively witnesses that user inputs were already committed when read under protection. The approved interpretation's original hash and preparation timestamp are preserved. Approval/position effective times and `admission_effective_at` do not measure the exact admission commit instant. First observations remain pinned when an immutable input is reused. This evidence does not establish full operational activation replay or complete source receipt capture.

Enrollment is explicitly gated local synthetic setup. It accepts exactly twelve non-user-context fixture roles; real user context cannot be supplied as arbitrary hashes. An existing unbound brief cannot be rebound into another lock protocol. Ordinary fixture registration cannot pre-empt any of the four bound user-context identities. Production source ingestion, entitlements and enrollment remain future boundaries.

## Inspect and verify

The [readable trace](../artifacts/paper-desk-audit.md) and [complete records](../artifacts/paper-desk-audit.json) show attachment, resizing, approved amendment, old retries and closure. The fictional factual notices leave portfolio consequences unresolved. Closed declarations remain in the complete exposure book with their status visible. Tests independently force publication/approval/exposure orderings through actual PostgreSQL lock waits, atomic rollback, coherent inspection and protected clock sampling.

After loading a gated development environment:

```sh
.venv/bin/python tools/paper_desk_demo.py --output artifacts/paper-desk-audit.json --report artifacts/paper-desk-audit.md
.venv/bin/python tools/paper_desk_demo.py --inspect-only --output .local/paper-desk-inspection.json
```

The write trace refuses existing demo state; inspect-only reads the persisted final state without reconstructing intermediate snapshots. The fixture owner has an unusable password. Source, macro and runtime inputs remain fictional, with zero provider calls or spend. Continuous permitted news, agent compilation/challenge, portfolio hypotheses, the trader UI, source health and external notification delivery remain required for a usable desk.
