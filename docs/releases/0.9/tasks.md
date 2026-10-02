# Implementation slices

Task state is authoritative here. [status.md](status.md) owns release/delivery
state. `Pending` means not implemented for this release, even when an existing
mechanism can be reused. Dependencies order work; they do not grant authority.

| ID | State / owner | Dependency | Deliverable and completion evidence |
| --- | --- | --- | --- |
| T00 | Complete — planning | None | Connected spec, design, owners, tasks, decisions, sources and release index. Local link/traceability checks recorded in the private planning handoff. No runtime changes. |
| T01 | Pending — host + EKK | T00 | Inspect available ongoing event/focus/recall channels and current installation. Identify one supported real path, permissions/coverage, measured baseline and finite proposed budgets for capture, processing and recall. Record unavailable surfaces. Preserve an owned source/runtime baseline. If live capture or delivery is unavailable, make that gap explicit before claiming the target is achievable. |
| T02 | Pending — EKK model/application | T01 boundary findings | Specify/implement additive experience profile and neutral ports, episode identity, grounds, independent-case grouping, applicability and correction relations. Verify old-reader behavior and the distinction from `observation_gap`; map O04–O07, O10–O12, O18 to contracts. |
| T03 | Pending — host + EKK adapters | T01, T02 | Bounded durable candidate buffer, checkpoint/replay, expiry/overflow diagnostics, backpressure and manual finding input. Model work off the critical path. Verify logical-key recovery, coverage, zero-record path and operational-state namespace. Covers O01–O03, O13–O14. |
| T04 | Pending — EKK adapters | T02, T03 | Candidate/source retention through current routing, writer and queue; exact evidence read-back, permitted work association and discoverability. Verify revoked access, lost responses and same-key retry without duplicate records. Covers O04–O07. |
| T05 | Pending — EKK application/adapters | T02, T04 | Recall for current intention/object/focus, explanation cards, current applicability, independent exact/lexical path and bounded optional budget. Read beyond only the latest work events. Verify mandatory-context preservation, empty result, failure fallback and repeated-delivery suppression. Covers O08–O10, O13. |
| T06 | Pending — EKK application/adapters | T04, T05 | Challenge/correction/retirement and derived-index refresh; bounded consolidation without losing origins; selected use/outcome linkage to `improve`/methods. Verify stale advice does not reappear through a summary/cache and unrelated valid knowledge remains usable. Covers O06, O11–O12, O17. |
| T07 | Pending — host + Gateway | T03–T06 | Wire the proven capture and in-work recall path; expose only needed CLI/MCP operations, coverage, disable controls and recovery. Observe capture during one actual authorized implementation/work episode and recall at an appropriate later focus. Fixture injection alone is not live evidence. Covers O01–O02, O08–O10, O13–O14. |
| T08 | Pending — observer adapter | T01, T02 | Usable optional Laya shadow adapter with pinned runtime/checkpoint, token-aware bounded input, typed advice and explicit uncertainty/failure output. Preserve every baseline candidate/order and all authority. Test missing/slow/malformed/truncated input paths. Covers O15; shares principles, not labels, with the existing search-advice spec. |
| T09 | Pending — observer evaluation | T08 | Versioned selection rubric and permitted episode corpus, data-rights record, grouped splits and simple/base-model reference comparison. Record actual misses, unsupported generalizations, language/option-order/truncation behavior, calibration and end-to-end costs. Inspect some rejected/ordinary episodes. Public/declassified material is sufficient for the bounded experiment; do not silently harvest private logs. Covers O16. |
| T10 | Conditional, not started — training | T09; eligible data and resource scope | Train a candidate when the prerequisites justify it; document training code, input provenance, exact checkpoint, separate calibration and untouched comparison. Negative results can complete the experiment; missing data cannot. Initial deployment remains shadow. Applied filtering/reranking is a separate evidence-backed decision and is not required by 0.9. |
| T11 | Pending — docs + host owner | T05–T09 | Concise user/operator guide, ordinary-work examples, coverage/defaults, privacy and disable/recovery instructions; targeted shared-skill changes only where integration needs them. Document zero-call/zero-record behavior. No new universal reflection instruction. |
| T12 | Pending — EKK + Gateway release owners | T02–T09, T11 | Freeze reviewed source and matching packages; update the explicit public inventory for selected English documents/modules. Run relevant focused checks, required compatibility/starter/replay/protocol checks and installed integration against exact inputs. Record all O01–O19 evidence and known limits. Do not rerun unchanged checks without a changed input or uncovered risk. |
| T13 | Pending — local host delivery | T12; local installation authority | Install/activate the reviewed composition on declared surfaces; observe process/routes, enrolled profiles and baseline fallback, preserve unrelated configuration, prepare/verify disable/rollback and reconcile actual version receipts. Mark local delivery only after observed integration. Public publication remains separate. Covers O19. |
| T14 | Ongoing-use follow-up, not started — product owner | T13 and ordinary use | Use selected real episodes and natural feedback to revise missed/false/stale findings and cost. Track retrieval/delivery/use/helpfulness separately. No fixed trial period, mandatory diary, automatic scheduled monitor or scientific-win gate for delivery. |
| T15 | Conditional, not started — public observer project | Stable neutral interface and useful permitted artifacts | Prepare an independently useful OSS package, license/provenance and model/data cards if extraction is justified. Record repository owner/name and publication authority before external creation. Do not publish private source or assume EKK release authority covers a new account/project. |

## Acceptance ownership

| Criteria | Primary completion slices |
| --- | --- |
| O01–O03 | T01, T03, T07 |
| O04–O07 | T02, T04, T06 |
| O08–O10 | T05, T07 |
| O11–O12 | T06 |
| O13–O14 | T01, T03, T07, T11 |
| O15–O16 | T08, T09; T10 only for a trained candidate claim |
| O17 | T06, T11; later benefit evidence in T14 |
| O18–O19 | T12, T13 |

T10, T14 and T15 are separate lanes, not hidden prerequisites for core delivery.
Their result states remain visible in the release handoff.

## Order and safe independence

Critical path: T01 -> T02 -> T03 -> T04 -> T05/T06 -> T07 -> T11 -> T12 -> T13.
T08/T09 can progress beside T04–T07 after the input/owner contracts are stable.
T05 and T06 share revision/index behavior and need an agreed interface before
independent edits. Host and Gateway work can be separated after T02, with explicit
file ownership. Parallel execution is a dependency property, not an instruction
to spawn agents; follow current user/host delegation preferences.

At handoff, record the next incomplete task, its actual blockers and the exact
last evidence. Complete means the deliverable and its checkable receipt exist,
not that a file or placeholder API has been created.
