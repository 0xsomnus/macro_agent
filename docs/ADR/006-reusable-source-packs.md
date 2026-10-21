# ADR 006: Reusable source packs and inspectable coverage

Status: Accepted; scope revised 2026-10-02. User packs are deferred from the initial pilot.

**Decision:** Reuse economy/currency, index-underlying, and commodity source packs with explicit instrument mappings. The pilot targets ES, NQ, XAU, DXY-linked trades, EUR/USD, USD/JPY, and USD/CNH, while keeping relevant global context. DXY is both context and a direct exposure; identify its actual traded instrument. GBP/USD follows later. Broader currencies, rates, crypto, equities/valuation, and declarative user packs remain reviewed expansion targets.

**Why:** Shared acquisition avoids bespoke watchers per symbol while a bounded instrument promise remains testable. Narrow exposure support must not become a geographic filter that discards global macro drivers.

**Rejected:** One adapter per ticker; unqualified `fully monitored` labels; technical access treated as a licence; user submissions creating canonical facts/edges; customer BYOK complexity driving the pilot design.

**Consequence:** Each driver/exposure has a dated coverage contract listing event families, sources, freshness, exclusions, and verification, plus live health that downgrades on outage/entitlement loss. Provider interfaces remain replaceable. Internal BYOK is available for research; customer-facing BYOK and public community packs are deferred. Shared work respects entitlements and private-data boundaries. Bloomberg/OpenBB/Yahoo access confers no assumed production rights.

**History:** Accepted 2026-09-28 with reusable packs and user-defined coverage. Revised after user review on 2026-10-02 to bound pilot instruments, preserve global context, defer user packs, and replace exhaustive-sounding labels with inspectable contracts.

## Agent-led source setup clarification, 2026-10-21

Accepted direction: the agent should find relevant sources, inspect their documentation and configure reusable connection methods, rather than require a bespoke integration for every asset. Pilot coverage limits constrain validated monitoring promises, not which assets a trader may research. Source packs are reusable defaults, not an exhaustive source or asset allowlist.

Source setup approval is a user preference: review each new connection, or delegate approval within a versioned policy. Delegation can cover research acquisition and source additions within an existing monitoring mandate, subject to permitted endpoints, credentials, processing rights, cadence and spending limits. It cannot create a monitoring mandate from a research request, change approved thesis meaning, promote canonical knowledge or authorize execution. The initial setting and exact UI remain open.

An eligible new feed or API using a supported connection method need not wait for an engineering release. The agent can configure, probe and admit it under the applicable policy; successful parsing alone does not establish source suitability or monitoring coverage. Unknown rights or costs remain unresolved. For a genuinely unsupported protocol, the agent may develop and test a new adapter in an isolated environment before code review and release admission. Delegated source approval does not authorize arbitrary live code installation.

This is intended architecture, not current functionality. The current research path uses the configured GDELT adapter; dynamic source setup, the approval setting and its enforcement remain unimplemented. See [agent runtime](../AGENT_RUNTIME.md#agent-led-source-setup-and-approval-preferences) and [the setup graph](../EXECUTION_GRAPHS.md#source-discovery-and-setup-branch-planned).
