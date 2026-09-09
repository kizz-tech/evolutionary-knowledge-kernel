# Method applicability under changed conditions

**Status: proposed design; no executable protocol, dataset, baseline reproduction
or empirical run yet.** Study owner, model versions, evaluator, sample size, numeric
decision thresholds and budget are unassigned. This document does not schedule
runs or recruit participants.

This is the first proposed experiment in the [open agenda](../../agenda.md).
It addresses EKK-Q-XFR and a bounded part of LIF and CIN; EVA and UNK shape the
measurement. [Roadmap tasks](../../../ROADMAP.md#measurement-and-the-first-comparison)
describe the work needed to make it executable.

## Decision and hypothesis

A method was useful under a prerequisite P. Can a new participant preserve that
benefit where P still holds and restrict the method where P is violated?

The hypothesis is that evaluating applicability improves later work at a defensible
total cost. Repeating the method everywhere and deleting it everywhere are both
important failure modes. The decision is whether an EKK mechanism is warranted
beyond ordinary work, retrieval and an existing adaptive alternative.

The first experiment holds the model fixed and changes one relevant condition.
Replacement, retirement, model changes and ambiguous tool failures are later
extensions. Repairing already created consequences, method composition, general
causal diagnosis, organizational privacy and human learning require separate tests.

## Relationship to the existing protocol

The existing [human/shared/method-transfer protocol](../human-shared-method-transfer/README.md)
compares ordinary, personal-only, shared-only and combined environments. Its
empirical status remains `designed_not_run` with `freeze: null`.

Those four environments are different from the algorithmic comparisons below.
The existing harness does not automatically support this design. Implement a
separate protocol and matching validator before execution; preserve the existing
protocol and its history. Reusing its cost-accounting principles does not make a
new experiment executable or observed.

## Establish measurement before a new mechanism

First build small reproducible cases with an independent outcome check and a
strong ordinary workflow. Demonstrate that the cases distinguish useful action,
harmful transfer and unnecessary rejection. A legitimate outcome of this stage
is that the ordinary workflow has no meaningful gap to justify an extension.

Proposed synthetic families are caching under a changed freshness requirement
and completion checks when an API changes from synchronous completion to an
asynchronous receipt. Each needs a compatible control and an independent family
kept outside tuning. These are candidate designs, not existing datasets.

The hidden truth of P and labels for the correct intervention belong to the
evaluator. Agents receive ordinary task requirements and equally available
diagnostic observations. Do not reveal the answer through labels, fixture names,
retrieval metadata or a curator-selected method. Surface similarity must not
determine which condition changed.

## Proposed sequence

1. **Acquire.** Develop a method on acquisition tasks and record its useful
   history. Account for generation, unsuccessful attempts and human preparation.
2. **Transfer.** A new authorized participant receives permitted experience and
   works on related, nonidentical tasks. Future answers and private archives are
   excluded.
3. **Change one prerequisite.** Present paired later cases where P holds or
   fails. The agent can investigate, use the method or restrict its use. The
   method must remain available on compatible cases.
4. **Evaluate later behavior.** Use new tasks whose answers were not available
   during selection or refinement. An observation used to adapt a method belongs
   to its adaptation budget, not its independent confirmation.

Preserve the causal order of acquisition and later tasks. Randomize independent
replicas, arm assignment and permissible schedules. Pairing is a diagnostic
distribution; it does not estimate how often violations occur in ordinary work.

## Comparisons to freeze

| Proposed arm | Controlled difference |
| --- | --- |
| Strong ordinary workflow without a carried method | Same current requirements, tools, observations and checks; no carried experience |
| Frozen prior method with ordinary retrieval | Same initial method and available acquisition evidence; ordinary use of experience |
| Reproduced SkillAxe | An existing diagnostic/refinement alternative, configured and reproduced with stated limits |
| EKK applicability candidate | Same initial method, acquisition evidence and feedback; the proposed conditional-use mechanism |

The [related-work review](../../related-work.md) explains the proposed baseline.
Artifact availability and reproduction fidelity remain to be established. A
smaller rehearsal may test measurement, but its findings only support the arms
actually compared. Add a matched EKK ablation without the applicability mechanism
before attributing an effect to that mechanism.

List allowed differences in accumulated state as the treatment. Tools, initial
requirements and diagnostic access stay comparable. No arm receives hidden
prerequisite labels or free expert attention. Human-authored methods must have
their provenance and labor counted equally across comparable arms; such a study
tests handling a supplied method, not autonomous method creation. An oracle with
curator annotations can be an explicitly separate reference, never an ordinary
automatic baseline.

## Outcomes and costs

The independent unit is a trajectory with its own state. Tasks and calls within
one trajectory are dependent; account for task family or project in analysis.
Keep denominators, observation windows, failures, missing data and stop reasons.

| Outcome | Denominator or accounting boundary |
| --- | --- |
| Later-task quality | All assigned later tasks under the independent criterion, including failure and stopping |
| Harmful transfer | Incompatible cases where using prior experience worsens the required result |
| Unnecessary rejection or change | Compatible controls where a useful method is unjustifiably stopped or damaged |
| Missed necessary revision | Cases known to the evaluator to require a change in application |
| Diagnostic and recovery cost | Resources and time from the first available signal to useful later behavior |
| Complete lifecycle cost | Acquisition, execution, context, maintenance, failed candidates, evaluation and human attention |

Report currency, tokens, elapsed time and human minutes separately. Analyze quality
under equal total budgets and cost to reach a frozen quality target as distinct
views. Preserve outcome distributions and uncertainty, including rare severe harm.
Tool failure, inappropriate method use and exhausted budget remain different
observations.

**Proposed continuation rule:** later independent benefit exceeds a predeclared
practically meaningful difference, respects separate harm limits and survives
full cost accounting. Numeric thresholds have not been selected. They must follow
the target user's need and tolerable harm. Choose independent replication count
from pilot variability and an explicit precision rationale; do not treat an
arbitrary round number as statistical justification.

## Gates before the main study

Freeze the task rights and versions, models, tools, comparison configurations,
evaluator bytes, outcome and harm criteria, observation window, independent unit
and sample-size rationale, lifecycle caps, attempt budget and stopping rules.
Name the study owner and executor. Pin the exact protocol outside candidate
write access and demonstrate isolation of arms, replicas and future answers on
the actual run host. A validator cannot establish that isolation by declaration.

First use fixed product code with different experience and handling policies.
A later experiment may start from the same code and let environments evolve
independently. That measures a different effect; requiring identical final code
would remove the treatment. Keep the conclusions separate.

Publish failures, reproduction limits and null or negative results alongside
positive findings. If an ordinary or existing method performs as well at lower
cost, prefer it for the target workflow and reconsider the EKK extension. Do not
weaken the task or evaluator to manufacture a reason for a new mechanism.
