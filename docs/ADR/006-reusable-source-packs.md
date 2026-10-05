# ADR 006: Reusable source packs and inspectable coverage

Status: Accepted; scope revised 2026-10-02. User packs are deferred from the initial pilot.

**Decision:** Reuse economy/currency, index-underlying, and commodity source packs with explicit instrument mappings. The pilot targets ES, NQ, XAU, DXY-linked trades, EUR/USD, USD/JPY, and USD/CNH, while keeping relevant global context. DXY is both context and a direct exposure; identify its actual traded instrument. GBP/USD follows later. Broader currencies, rates, crypto, equities/valuation, and declarative user packs remain reviewed expansion targets.

**Why:** Shared acquisition avoids bespoke watchers per symbol while a bounded instrument promise remains testable. Narrow exposure support must not become a geographic filter that discards global macro drivers.

**Rejected:** One adapter per ticker; unqualified `fully monitored` labels; technical access treated as a licence; user submissions creating canonical facts/edges; customer BYOK complexity driving the pilot design.

**Consequence:** Each driver/exposure has a dated coverage contract listing event families, sources, freshness, exclusions, and verification, plus live health that downgrades on outage/entitlement loss. Provider interfaces remain replaceable. Internal BYOK is available for research; customer-facing BYOK and public community packs are deferred. Shared work respects entitlements and private-data boundaries. Bloomberg/OpenBB/Yahoo access confers no assumed production rights.

**History:** Accepted 2026-09-28 with reusable packs and user-defined coverage. Revised after user review on 2026-10-02 to bound pilot instruments, preserve global context, defer user packs, and replace exhaustive-sounding labels with inspectable contracts.
