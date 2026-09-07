# Preserved foundation and current 0.5 implementation

The source Architecture 0.1 is preserved in v0.4.0. This edition translates its
prose and starter fixtures into English; the four schemas remain unchanged.
The product direction is defined in [final-architecture.md](final-architecture.md).
Runtime status is separate: [public validation report](release-validation.md). Format conformance,
local functional evidence and empirical effectiveness are different claims.

| Architecture section | Current implementation | Evidence and limits |
| --- | --- | --- |
| 1 Owners and stores | Independent owner realms and a contained project realm | Explicit realm IDs/profiles; independent synthetic restore cases; same OS user is not isolation |
| 2 Dependency direction | Pure model and application; Markdown/Git/CLI/process/index adapters | Application/execution dependency guard; independent store and application tests |
| 3 Layout and governance | Exact realm schema, default deny, trusted owner, scoped grants, pack pins | Exact schema/identity tests; local authority is not cryptographic proof against OS owner |
| 4 Records and sources | Exact schema, immutable assets, stable IDs, qualified refs and history | Schema/migration tests; full original bytes retained; unknown origin time remains unknown |
| 5 Acceptance | Exact receipt/content/governance, pinned consequential closure, explicit replacement/conflict | Authorization, transitive pinning, historical horizon, forged receipt and conflict regressions |
| 6 Owning systems and packs | Passive exact base/research/software artifacts pinned by manifest hash | Installed wheel verifies all pack bytes; no source/pack execution on read |
| 7 Product binding | Portable workspace declarations, role-local paths, published identity, nested Git boundary | Portable bindings; repeated contained resolve and denied identity tests |
| 8 Runtime and cache | Durable journals/evidence outside repo; SQLite cache of authorized projection | Recovery/idempotency tests; cache deletion/rebuild and permission-key tests |
| 9 Context and writer | Constraints before ranking, closed dependencies, budget/incompleteness, propose/apply exact base | Application/CLI regressions; synthetic context→verified outcome→reuse |
| 10 Federation | References retain realm identity; explicit authorized export; no implicit cross-owner read or adoption | Foreign-ID/grant tests; no cross-realm atomicity or server projection claimed |
| 11 Work and outcomes | Registered commands and independent verifier; separate execution/retention/observed steps | Synthetic routing/execution tests, independent verifier, outcome reconciliation tests |
| 12 Review | Registered due/expiry/changed-basis/failed-outcome signals; human conditions reported separately | Review regressions; zero mutation, no automatic task creation or scheduler |
| 13 EKK self-change | Contained realm shares code history; evaluator/command files pinned; pure experiment orchestration | Contained-store and execution cases; same-user separation is not hostile-process sandbox |
| 14 Research | Current human/shared/method four-arm protocol; historical studies preserved separately | Two-participant deterministic method demo; empirical protocol remains designed_not_run |
| 15 Migration | Full backup, owner-resolved map, immutable originals, forward revisions, restore, cutover | Source-preserving migration and restore checks; adoption remains separate; private migration records excluded |
| 16 Implementation | Local runtime, package and data integration implemented | Full suite, starter tests, replay, fresh wheel install, synthetic restore and execution cases |
| 17 Future backends | Ports allow replacing storage/transport with explicit identity-preserving migration | No deployed server/backend or future migration guarantee claimed without conformance tests |
| 18 Non-goals | No universal task manager, magical self-authority, swarm or compulsory record per edit | Agent guidance and methods remain bounded to user task and owning systems |
| 19 Source limits | Supplied architecture/starter/source hashes preserved | No fresh verification of every external paper or factual claim in supplied research |

Original starter tests are a separate suite under
`examples/starter/ekk-blueprint/ekk/tests`. Runtime extensions do not replace the
four supplied schemas. Publication uses Apache-2.0; empirical effectiveness remains untested.

## Current product contracts

| Contract | Implementation | Evidence |
| --- | --- | --- |
| Personal entry and exact resume | WorkspaceService and authorized profile home | Scoped historical focus and refusal tests; no inferred personality |
| Shared continuity | Existing realm records and explicit owner exports | Fresh-process two-participant demonstration |
| Method transfer and revision | MethodService, RealmMethodRepository and fixed host executor | Local acceptance, current basis, exact artifact, independent evidence and quarantine tests |
| Unlearning | Adverse outcome, host quarantine, accepted retirement, forward revision | Demo retains old bytes and uses a replacement |
| Research claims | Frozen four-arm observation validator | Incomplete or contaminated observations rejected; empirical study not run |

Legacy runtime code lives under `archive/runtime-0.4`; it is absent from the
installed package and ordinary CLI routing.
