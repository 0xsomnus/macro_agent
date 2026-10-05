# ADR 009: On-demand, method-aware fundamental valuation

Status: Accepted direction; deferred from the initial paper pilot by user review on 2026-10-02.

**Decision:** Make Fundamental Valuation an on-demand skill. Select DCF, reverse DCF, multiples, residual-income, NAV/AFFO, sum-of-the-parts, or other suitable method by business type and supported data. LLM chooses and explains sourced assumptions; deterministic code computes scenarios and sensitivities. Version the model and link assumptions to thesis drivers.

**Why:** A universal DCF creates false precision, while reproducible calculation makes changing price ranges explainable. Continuous full modeling of the top 100 is wasteful.

**Rejected:** “DCF” as the only skill; prose arithmetic; one correct fair value; a full valuation rebuild on every routine news item.

**Consequence:** Once equity support is enabled, support only validated methods and visibly decline unsupported cases. Full specialized methods and options contract analysis are later modules.

## Review clarification, 2026-10-02

The original direction remains accepted, but its initial MVP sequencing is superseded. Individual equities and automated valuation are excluded from the first paper pilot to prove the continuous macro desk on a bounded exposure set. Equities remain a planned core research capability, subject to measured demand and source feasibility.

For supported equity theses later, consider valuation during initial compilation and document method/data limits before claiming supported equity research. Official filings alone do not guarantee complete usable valuation inputs. Missing inputs or unsupported business methods require a visible limited result, not a universal DCF or an invented target. Relevant approved user assumptions remain distinguishable from agent-proposed assumptions.

The method-aware, deterministic calculation boundary and on-demand refresh policy remain unchanged. No model calculation or contextual update may silently amend the user's thesis or its approved interpretation.
