# Documentation

Start with [Getting started](GETTING_STARTED.md) to run the current prototype. The [project README](../README.md) explains what is available today. All shell commands in these guides run from the repository root.

## Run and inspect

| Guide | Use it for |
| --- | --- |
| [Getting started](GETTING_STARTED.md) | Install dependencies, create a local database and test your own inputs with recorded news |
| [Thesis compilation](THESIS_COMPILATION.md) | Configure a provider, review a structured thesis card, answer questions and explicitly recompile |
| [Compilation review](COMPILATION_REVIEW.md) | Compare one model response with a literal baseline and record private feedback |
| [Monitoring pipeline proof](MONITORING_PIPELINE.md) | Capture updates, restart and recover durable work; inspect source revisions and failures |
| [News analysis](NEWS_ANALYSIS.md) | Analyse the next captured report against approved meaning and paper trades, then review separate thesis and trade effects |
| [Internal continuous runner](CONTINUOUS_RUNNER.md) | Configure separate capture/analysis processes, inspect daily evidence and recover saved work |
| [Blocked-job recovery](JOB_RECOVERY.md) | Read saved failure explanations and explicitly retry deterministic/unstarted work or reconcile a saved model result |
| [Weekly workflow test](WEEKLY_WORKFLOW_TEST.md) | Narrow headline-based durability target and remaining source, continuity, runner and daily-brief prerequisites |
| [API guide](API_DEVELOPMENT.md) | Log in, save drafts and refinement answers, approve exact versions, and recover private commands |
| [Paper positions](PAPER_POSITIONS.md) | Attach, revise and close a paper trade; understand brief invalidation |
| [Django development](DJANGO_DEVELOPMENT.md) | Database operations, tests, migration SQL and internal inspection |
| [Implementation](IMPLEMENTATION.md) | Verified modules, test evidence and remaining limitations |

## Product and scope

| Document | What it explains |
| --- | --- |
| [Product doctrine](PRODUCT_DOCTRINE.md) | User authority, evidence standards and non-negotiable behavior |
| [Product specification](PRODUCT_SPEC.md) | Intended trader journeys and pilot acceptance scenarios |
| [Roadmap](ROADMAP.md) | Current work, pilot gates, expansion and deferred capabilities |
| [Thesis engine](THESIS_ENGINE.md) | Refinement, factual challenge, interpretation and user approval |
| [Monitoring and sources](MONITORING_AND_SOURCES.md) | Continuous capture, source rights, coverage and costs |
| [Source options](SOURCE_OPTIONS.md) | Compare initial news feeds, published access and unresolved usage rights |
| [First monitoring slice](MONITORING_SLICE.md) | Review capture-to-brief work, recovery and the remaining implementation choices |
| [Learning and evaluations](LEARNING_AND_EVALS.md) | Quality measurement and why automated learning is deferred |
| [Safety boundaries](SAFETY_AND_REGULATORY_BOUNDARIES.md) | Product authority, execution exclusions and legal review boundaries |

## Engineering reference

| Document | What it explains |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | System components, persistence, authority and reliability |
| [Context continuity](CONTEXT_CONTINUITY.md) | Accepted internal runtime and daily-review directions, evidence/context contracts and remaining implementation choices |
| [Domain model](DOMAIN_MODEL.md) | Theses, positions, events, knowledge, assessments and history |
| [Event ontology](EVENT_ONTOLOGY.md) | Event families, revision semantics and provenance |
| [Agent runtime](AGENT_RUNTIME.md) | Context assembly, specialist roles and bounded work |
| [Execution graphs](EXECUTION_GRAPHS.md) | Node contracts, budgets, failure paths and authority gates |
| [Decision records](ADR/README.md) | Accepted decisions and their rationale |
| [Stack comparison](STACK_OPTIONS.md) | Alternatives considered before selecting the application foundation |

## Project history and evidence

[Audit resolutions](AUDIT_RESOLUTION.md) and [development start](DEVELOPMENT_START.md) preserve the earlier design discussion and reference experiments. [Implementation](IMPLEMENTATION.md) is the source for current verified status; historical milestones are not promises of present coverage.

The [paper desk trace](../artifacts/paper-desk-audit.md) shows the synthetic workflow. The [daily-review trace](../artifacts/daily-review-domain-audit.md) illustrates retained analyses, stale history and deferred evidence in pure domain assembly. The [job-recovery trace](../artifacts/job-recovery-audit.md) shows a retained daily failure, reviewed repair and inert replay. The [AI infrastructure research pack](../research/ai-infrastructure/2026-10-09/README.md) records the first user-led market question, primary evidence and narrow paper-instrument feasibility. It is manual research, not approved trading authority or an automated source feed. The [free-source research](../research/source-options-2026-10-10.md) compares GDELT metadata, yfinance rights and future wire credentials.

[Earlier PostgreSQL](../artifacts/postgresql-audit.md), [thesis approval](../artifacts/thesis-audit.md) and [SQLite](../artifacts/publication-audit.md) reports preserve prior evidence. Complete records, generated schemas and migration SQL remain in `artifacts/`; executable code and fixtures remain outside the documentation folder.
