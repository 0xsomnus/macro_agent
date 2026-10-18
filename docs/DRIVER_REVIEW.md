# Review the explanation as well as the direction

Status, 2026-10-18: the user accepted immediate attention for material driver changes, even when the directional view remains intact. An optional structured profile now implements evidence-linked research proposals and driver reassessment in retained news and morning synthesis. A separate [qualified internal publication route](DRIVER_ATTENTION.md) now exists; external delivery and live materiality calibration remain outstanding.

A favorable price observation does not validate the trader's proposed mechanism. Compilation should expose unsupported premises and transmission assumptions; monitoring should reassess them as evidence arrives. The agent may find support for the original mechanism, a stronger competing explanation, an amplifier, an offset, or insufficient evidence to distinguish them.

## Required review content

| Review element | Requirement |
| --- | --- |
| Approved explanation | Reference the exact approved interpretation and driver. Preserve its text, version and authority. Do not replace it with a retrospective paraphrase. |
| Premise | Separate whether the underlying event occurred from whether it had the claimed price effect. Announcements, implementation and delivered quantities are different observations. |
| Transmission | Explain support, counter-evidence and unresolved links between the premise and the affected asset. A quote, favorable direction or temporal coincidence does not prove causation. |
| Other drivers | Distinguish competing explanations from amplification and offsets. New pathways remain labelled agent hypotheses. |
| Price observation | Retain benchmark/symbol, period, provenance and observation status separately. Trader-reported prices cannot become verified market data; a proxy cannot silently replace the observed instrument. |
| Change from predecessor | State what new evidence changed the assessment and what remained intact. Retain the prior assessment and its actual inputs. |
| Discriminating evidence | Name the unresolved material question, relevant signposts and coverage gaps. Attribution may remain unresolved. No numeric causal contribution or probability is invented. |

The current profile binds a driver by its zero-based index and exact text within the pinned approved interpretation. Every approved driver must appear exactly once. Support is `supports`, `challenges`, `mixed` or `unresolved`, separately for premise and mechanism. References name exact current-output quotations and eligible earlier labelled model analyses, not newly verified facts. An assessment can remain unresolved.

## Helping a rough thesis

Accepted 2026-10-14: propose and explain evidence-qualified missing drivers before asking consequential clarification questions. The initial idea may reflect only a few headlines. The agent must investigate more important drivers, their transmission, counter-evidence and interactions rather than require the trader to know the complete framework or curate every source in advance. A result of insufficient evidence or no defensible thesis is valid.

Link each proposed driver to its supporting and counter-evidence, assumptions and limitations, and explain why it could matter more than the original explanation. A verified event does not make its proposed market effect a fact. Unavailable current context stays unavailable. Search remains a bounded investigation of a named unresolved material question, with source rights, provenance and cost recorded. User-initiated refinement is distinct from deferred proactive Discovery.

Ask the trader about intent and consequential unknowns; do not turn clarification into an exhaustive input form. New explanations can be investigated and surfaced immediately as agent hypotheses. They enter approved trader reasoning only through explicit incorporation and approval, and cannot promote themselves to canonical knowledge.

Research is not restricted by the pilot instrument list. An exploratory request can investigate an unfamiliar commodity, affected firms and ways to obtain exposure. It does not request monitoring, create a position or initiate a coverage-review workflow. Exposure candidates must explain their relationship and basis risks, including possible adverse effects on related businesses. Availability remains unverified until suitable instrument evidence is checked. The [question-led workflow](QUESTION_RESEARCH.md) can now gather bounded headline metadata automatically. Primary-source investigation and semantic source-fit evaluation remain ahead.

## Thesis progression and entry conditions

| Question | Separate conclusion |
| --- | --- |
| Is the explanation still supported? | Evidence may strengthen, weaken or leave the original mechanism unresolved even when direction is favorable. |
| Is the thesis progressing? | Expected conditions may be occurring. This does not imply the idea is invalidated or the original causal attribution is proven. |
| Is a prospective entry still attractive? | Progression can leave an entry less attractive under the contemplated scenario. This requires a separate assessment and may remain unavailable. |

Preserve fundamental conditions, user-declared technical abandonment criteria and entry constraints as distinct inputs. A trader may choose a price condition for abandoning an idea; that choice does not establish that the underlying causal mechanism was false. A qualitative conditional horizon is valid input. Do not invent a date, target, stop, risk/reward ratio, position or execution.

A proposed deterioration in entry attractiveness is conditional on the contemplated entry and scenario. Without suitable prices, horizon and loss/upside assumptions, no numerical risk/reward comparison or claim of a missed profitable trade is justified. The trader retains entry planning and execution.

## Immediate material attention

A material weakening, displacement or amplification of a central approved explanation is a thesis-impact route. It can warrant prompt attention when the price direction remains favorable or no position is attached. It must not wait for the morning brief merely because the trade has not visibly deteriorated.

The explanation must say why the evidence changes a consequential premise, transmission, horizon or invalidation assessment. Novelty, a new model wording, a favorable candle or an unsupported alternative is insufficient. Credible consequential uncertainty can justify a qualified review or bounded investigation; missing evidence cannot be silently classified as no impact.

Repeated reports about one development do not create independent signal weight. Update the stable thesis/driver brief. Further interruption requires a material evidence or assessment change. Morning synthesis should retain earlier labelled reviews without implying another delivery. Numeric thresholds, latency targets and interruption criteria remain open; this clarification sets no hidden operating defaults.

## Authority and time

A driver assessment can change immediately; approved trader reasoning changes only through explicit approval. Do not promote a new canonical causal edge or infer trader skill from one observed move. Current evidence review does not enable automated postmortems, outcome-derived lessons or retrieval, per [ADR 012](ADR/012-pilot-learning-and-evaluation.md).

Pin the approved interpretation, source revisions, observation status, predecessor and reporting cutoff. Historical research obtained later is not evidence that the desk knew it earlier. A modern model may already know subsequent events, so a historical reasoning exercise cannot establish forecasting skill. Source corrections and permission changes must participate in the existing protected ordering before any current analytical publication or atomic notification intent is added.

## Acceptance cases

- A trader supplies a headline-led explanation X and does not know driver Y exists. Investigate and propose Y with evidence, transmission and limits, then ask only consequential clarification. Preserve X as trader intent and Y as agent-proposed.
- The original condition persists while a new event advances the thesis. Explain progression separately from a potentially less attractive prospective entry; do not equate playing out with invalidation.
- Timing is conditional on the absence of a resolution. Preserve that condition without assigning a calendar deadline.

- Price rises as expected, but evidence weakens the original mechanism. Surface the material explanation change without asserting that the directional thesis failed.
- The original mechanism has evidence and another development plausibly amplifies it. Explain both and the limit of the attribution.
- An event occurred, but its marginal price effect is unresolved. Do not mark its mechanism validated from event confirmation alone.
- Evidence changes a central thesis driver with no attached position. Preserve the thesis-impact route and an empty exposure book.
- A future publication explains earlier data. It may inform today's review but cannot enter an earlier information set.
- Duplicate headlines, unsupported alternatives and wording changes alone do not produce repeated attention.
- No verified price data or expectation vintage exists. Keep these gaps visible and make no claim that direction, surprise or causation was verified.

## Try the implemented profile

Use existing setup and retain an exact source packet, then opt into research proposals:

```sh
.venv/bin/python tools/desk_cli.py compile --thesis-id THESIS_UUID --evidence-context EVIDENCE_CONTEXT_UUID --driver-review
.venv/bin/python tools/review_news.py --thesis-id THESIS_UUID --driver-review
.venv/bin/python tools/review_morning.py --review-id REVIEW_UUID --driver-review
```

These commands perform their existing separately initiated model requests. Research compilation needs a draft and selected evidence; news review needs an approved thesis; morning synthesis needs a retained daily review. Research proposals alone change none of those prerequisites or authorities. No command automatically adopts a proposed driver.

For a watch, preview its new news configuration with `manage.py desk_watch --owner OWNER_UUID --thesis-id THESIS_UUID --preview --cumulative --driver-review`, then enroll the complete explicitly reviewed configuration. Morning synthesis separately pins `model_configuration(provider, driver_review=True)` from `macro_agent.desk.synthesis`. Existing watches stay on their saved profiles.

The shared `driver_assessment` contains complete `approved_drivers`, separate `other_drivers`, `progression`, `price_observation`, `entry_assessment` and `attention`. Other drivers remain agent hypotheses and require current source-claim references. A material-review recommendation requires current attributed evidence. Generic relevance routes and cumulative comparisons remain separately visible. Current inputs contain no verified market-price history, so price status is `unavailable` and entry status is `not_assessed`, with nonempty gaps.

Opt-in admissions pin new schema/prompt versions and context before inference. Saved-command reads recover that exact profile without keys, catalogue calls or paid retries. Source corrections, permission changes and governing inputs keep their existing protected comparisons. Old schemas and omitted-flag command hashes remain valid.

## Remaining implementation gaps

The profile requires explicit driver reviews and separates progression from unavailable entry analysis. It validates structure, exact driver identity and eligible references. It cannot prove that a cited passage supports a conclusion, that the model found the most important driver or that a reported event caused a price move. Supervised live evaluation remains necessary.

Manual source selection remains available. Automatic named-question headline discovery now exists; primary-source investigation, independent source-fit checks and verified price/provenance inputs remain unimplemented. Broad research capability does not establish broad monitoring coverage.

Captured-news model analysis has no publication authority itself. A separate [driver publication contract](DRIVER_ATTENTION.md) now installs a protected current brief and qualified internal review intent for eligible cumulative analyses. External delivery, calibrated materiality and measured attention latency remain gates, independently of retained daily publication. [News analysis](NEWS_ANALYSIS.md), [morning synthesis](MORNING_SYNTHESIS.md) and the [weekly test](WEEKLY_WORKFLOW_TEST.md) must continue to report that limitation honestly.
