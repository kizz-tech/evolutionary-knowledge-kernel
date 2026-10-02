# Roadmap

**Next product release: 0.9 — acquire useful observations during work and recall
them when a later decision makes them relevant.**

Product planning updated **2026-09-21**. The [0.9 specification](docs/releases/0.9/spec.md),
[design](docs/releases/0.9/design.md), [tasks](docs/releases/0.9/tasks.md) and
[current status](docs/releases/0.9/status.md) form one working release package.
Implementation and delivery state live there. The first slice establishes actual
host event and recall-delivery capabilities; a post-task log reader alone does not fulfill the
connected outcome. [Release organization](docs/releases/README.md) defines the
shared format and separates implementation, local delivery, publication and benefit.

The research sequence below retains its **2026-09-09** framing unless a section
states a later change. It connects the [open research agenda](research/agenda.md)
to contributor work and remains independent of the 0.9 product release gate.
Ordinary use and selected real episodes guide product improvement; no artificial
agent competition or scientific win is required for local delivery. Research
questions remain open even when an engineering task is complete. Task IDs do not
imply that external issues, assignments or funded runs already exist.

## Starting point

| Area | Evidence state | Remaining limit |
| --- | --- | --- |
| Public runtime | [0.7.0 English research prerelease](https://github.com/kizz-tech/evolutionary-knowledge-kernel/releases/tag/v0.7.0), released 2026-09-09 | Public publication and the owner's installed version are separate facts |
| Continuous work | [0.8 approved specification](docs/plans/v0.8/spec.md), [implementation state](docs/plans/v0.8/implementation.md) | Connected workflow and local installation are checked separately from benefit in ordinary use |
| Observations and contextual recall | [0.9 specification](docs/releases/0.9/spec.md), [working status](docs/releases/0.9/status.md) | Live capture/delivery, implementation, model evaluation and benefit have separate evidence states in the release package |
| Daily reliability increment | 0.6 implemented and included in 0.7 | Exact retention, diagnostics and isolated recovery remain the foundation of the 0.8 outbox |
| Method lifecycle | Deterministic evaluation, local admission, transfer, quarantine and retirement demonstration | No empirical productivity or general transfer result |
| Human/shared/method-transfer study | Existing protocol and contract validator; `designed_not_run`, freeze unset | Actual study design choices, execution and independent analysis are still required |
| Method applicability | [Proposed first comparison](research/studies/method-applicability/README.md) | No dataset, executable protocol, reproduction or run yet |
| Belief Runtime | [Concept selected](docs/belief-runtime.md); pure projection and one manual [coding workflow](docs/coding-readiness.md) implemented for 0.7 | The adapter assesses configured reports for a committed object; autonomous sensing, execution integration and comparative benefit remain unestablished |

The 0.7 candidate includes the 0.6 work on exact result retention/read-back,
private diagnostics, isolated backup/restore, and contestable assertions, alongside
the manual Belief Runtime workflow. Its public release gate below is separate
from local implementation checks and evidence of user benefit.

## Product readiness

### EKK-T-REL: Prepare and release the English 0.7 preview

**State:** 0.7 public release completed on 2026-09-09. The 0.8 reviewed export and local installation follow the approved specification. **Dependency:** none
on an empirical research win.

Prepare a reviewed export against the current English edition, preserving
translation provenance and exact original artifacts. Validate installation,
retention and resume, diagnostic bounds, backup/restore, holds, changed grounds
and the new coding-readiness workflow from the exported installed package.
Run a clean complete suite against frozen runtime/test inputs, plus original-starter,
historical-replay and protocol checks. Document actual platform coverage and
upgrade, recovery and uninstall behavior.

**Done when:** the reviewed English source, wheel, checksums and bounded validation
report are published through the release checkout; a fresh installation from the
published artifact passes the stated smoke checks; published hashes and target
commit match. Local preparation, publication and observed installation are
separate completion facts. Reuse existing evidence only where inputs match.

### EKK-T-USE: Verify one complete recurring workflow

**State:** proposed. **Dependency:** a selected workflow and its owner; local
checks may start before the public release is complete.

Choose one real, permitted use case such as continuing a software investigation
across participants. Observe entry, recovery of grounds, useful work, retained
results, fresh-session continuation, correction, appropriate method reuse,
authorized handoff and recovery or exit. State the workflow's success criteria
before evaluation; record friction, interruption and recovery cost.

**Done when:** another authorized participant can complete the declared cycle
from documented artifacts, including its failure and recovery cases, with an
account of what still required author assistance. A selected-case observation
does not establish an average reliability or productivity rate. Operational
attempt counts are not a denominator for all human tasks.

## Measurement and the first comparison

The following tasks are ordered research deliverables. REL and USE can progress
alongside measurement; publication of a package is not a scientific prerequisite
for developing synthetic cases.

| Task | State | Depends on | Deliverable and completion criterion |
| --- | --- | --- | --- |
| **EKK-T-CASE**: Build distinguishing cases | Proposed | Agreed narrow prerequisite contrast | Synthetic compatible/incompatible cases, independent expected outcomes, resettable state and a strong ordinary workflow. Demonstrate both harmful reuse and unnecessary rejection can be detected; keep a separate family outside tuning. If no practical baseline gap appears, record that finding. |
| **EKK-T-BASE**: Establish the strongest feasible comparison | Proposed | CASE for local comparison; artifact inventory can start earlier | Exact versions, licenses, configurations and reproduction limits for ordinary work, frozen-method retrieval and SkillAxe. Label a reimplementation honestly; select alternatives before observing a convenient loss. |
| **EKK-T-PROTO**: Implement the applicability protocol | Proposed | CASE and BASE specifications | Separate protocol, run-data contract and validator for the proposed arms. Reject answer leakage, mixed replicas, changed evaluator/protocol inputs, hidden setup/failure costs and invalid observed claims. Leave unknown study parameters unset. |
| **EKK-T-CAND**: Implement a bounded applicability candidate | Conditional; not started | A meaningful need established by CASE/BASE, plus PROTO | Smallest mechanism that preserves a method where P holds and restricts it where P fails. Supply the matched ablation, permitted evidence inventory and reversal behavior. No test labels may enter the candidate. |
| **EKK-T-PILOT**: Run a bounded rehearsal and freeze the main design | Not run | PROTO; CAND if evaluating EKK; named owner, executor and cost authority | Isolated rehearsal with complete costs and failures; estimate variability, resolve measurement defects, justify replication count and practical thresholds. Freeze a new main-study protocol against untouched later tasks. Rehearsal observations are not confirmation. |
| **EKK-T-RESULT**: Execute and report the independent comparison | Not run | Frozen design, baseline fidelity, isolation proof and run authorization | Versioned observations, independent analysis with trajectory-level uncertainty, all costs, harmful transfer, unnecessary rejection, failures and limitations. State the decision the result changes; release only authorized data and artifacts. |

The [study design](research/studies/method-applicability/README.md) specifies
fairness controls, units and unresolved fields. Models, evaluator, dataset rights,
sample size, budget, numerical thresholds and executor have not been selected.
Do not fill these with demonstration values to make a validator accept a run.

If ordinary retrieval or an existing adaptive method is equally useful at lower
total cost, use that smaller solution. If the cases do not distinguish an unmet
need, stop expanding the candidate and publish the measurement limit. If a benefit
appears, test its scope and reproduce it before making broader claims.

## Belief Runtime development

The owner selected this conceptual development on 2026-09-09. It makes the
observation/belief/action loop explicit alongside method evolution and preserves
`ekk.record/0.1`, realm ownership and host execution authority. This development
track may proceed alongside applicability; its empirical comparison remains
separate from package release and the existing studies.

| Task | State | Completion criterion |
| --- | --- | --- |
| **EKK-T-BELIEF-CONTRACT**: Integrate the concept and boundary | Implemented in concept, architecture, assurance and agent-entry guidance | World, observation, working belief, knowledge and commitment remain distinct; snapshots are historical; readiness cannot grant authority; attempt, effect and outcome remain separate. |
| **EKK-T-BELIEF-PROTO**: Implement a bounded working projection | Implemented; validation recorded with the change | Pure action-scoped assessment with exact targets, grounded observations, currentness, relevant alternatives and host-declared missing observations; focused checks and a resettable local coding example. No automatic production sensing, capability wiring or new canonical store. |
| **EKK-T-BELIEF-HOST**: Make one manual coding workflow usable | Implemented and validated for the 0.7 candidate | Bound `ekk assess`, fixed Git/report observations, invalidation on observed changes, failed/missing evidence, explicit exit codes and a disposable installed-CLI failure/repair cycle. Assessment does not execute the proposed action. |
| **EKK-T-BELIEF-EVAL**: Establish incremental usefulness | Design documented; not run | Three matched arms and guard-preserving ablation in the [action-readiness comparison](research/studies/action-readiness/README.md); frozen later tasks, full costs, harm limits and independent outcomes. Keep the smaller alternative when it suffices. |

Implementing the projection tests the selected contract, not the hypothesis that
it improves agent decisions. Expansion beyond the bounded prototype should
follow a reproduced baseline gap and comparative evidence. Existing CASE/BASE
work can supply relevant situations without relabeling the applicability arms.

## Follow-on choices

These are conditional directions, not simultaneous commitments.

| Direction | Evidence that should move it forward |
| --- | --- |
| **REP: Repair consequences** | Important errors persist in materialized outputs after their premise is corrected. Build a separate causal-history fixture with incomplete links and valid independent grounds. |
| **CIN / UNK: Broader intervention and investigation** | Beyond the selected Belief Runtime track, observed diagnostic mistakes justify wider sensor or intervention choices. Add tool-failure and no-change controls before broadening. |
| **LIF / XFR: Longer horizons and model/tool changes** | A bounded transfer effect survives independent comparison. Vary horizon, participant, model and tool separately and count maintenance growth. |
| **CMP: Method interaction** | Two individually useful methods conflict. Compare independent admission, full re-evaluation and targeted interaction checks with compatible controls. |
| **COL: Collaboration under different rights** | A specific permitted transfer has value. Start with synthetic owners and an explicit threat model; real organizational studies require named owners and rights. |
| **HUM: Chosen human capability** | Volunteers identify a skill and a useful joint workflow. Design delayed independent checks and mistaken-advice cases with an appropriate research partner. |

Downstream repair can move ahead of applicability if observed consequence costs
make it the more important user problem. Human participation and organizational
data are not required for the initial synthetic study.

## What would justify 1.0

1.0 should promise a supported workflow in a stated environment. It requires a
repeatable install, connection, upgrade and exit path; documented reading, error,
migration and recovery contracts; and independent continuation with exact grounds
and appropriate local authority. A second contrasting use case should test that
the boundaries are useful beyond the original demonstration.

The complete declared cycle is entry, recovery of grounds, useful work,
continuation, challenge and correction, suitable method reuse, reconsideration,
authorized transfer, recovery and exit. Publish its success and failure evidence
and remaining support limits. Product version 1.0 does not itself require changing
`ekk.record/0.1`, and releasing 1.0 would not establish universal scientific benefit.

Add retrieval complexity only after important selection failures are reproduced;
an SDK after an independent consumer needs it; another domain after its owner and
quality criteria are known; and organizational scale after a concrete operating
need and access model are established.

## Updating progress and contributing

Keep product-release status and dependencies in the linked release package;
keep research sequencing here and exact protocols/results with their study. Do
not maintain duplicate task states in the roadmap. When a result arrives, link
its artifacts, summarize what changed in the decision, and preserve the earlier
interpretation in version history. No results currently exist for the
applicability comparison.

Useful first contributions are a CASE fixture, a BASE reproduction inventory, a
stronger comparison proposal or a counterexample tied to an EKK-Q ID. See
[contributing](CONTRIBUTING.md) for the small evidence outline to include. A
negative result or a cheaper workable alternative can complete a useful task.
