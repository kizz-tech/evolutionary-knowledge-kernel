# Action readiness under partial observation

**Conceptual direction selected; comparative study `designed_not_run`.** No
model runs, effect estimates or claims of superiority exist for this design.
Model versions, evaluator, replication count, numerical criteria and budget are
unset. The [bounded projection](../../../src/ekk/application/beliefs.py), its
contract tests and [deterministic example](../../../examples/action_readiness.py)
are implemented. They are separate mechanism evidence and do not execute this
comparison or constitute a dataset or baseline reproduction.

This study develops [EKK-Q-UNK](../../agenda.md#unk), with CIN informing
decision-changing investigation and EVA governing the comparison. It accompanies
the [Belief Runtime contract](../../../docs/belief-runtime.md) and may reuse
permitted cases from method applicability. It does not replace that study or
implement the existing four environment arms merely by reusing their terminology.

## Decision

Does explicitly representing and maintaining the grounds of a current-world
belief improve consequential next-action decisions beyond an ordinary evidence
ledger, explicit preconditions and the same standard host checks?

The hypothesis concerns missed constraints, false completion and unnecessary
investigation at full cost. A correctly validated data structure alone does not
demonstrate that an agent notices the right variable or chooses a useful sensor.

## First scenario and cases

Use a resettable local coding fixture. A proposed change has an explicit schema
prerequisite in one selected environment. Observations include commit-bound CI,
a deployment-attempt receipt and a separately queried schema version. No real
production account or external mutation is needed for the fixture.

Pair cases with compatible controls:

| Case | What the evaluator must distinguish |
| --- | --- |
| CI is green for an older commit | Evidence for a different revision cannot satisfy a current requirement. |
| Correct observation, wrong environment | An unrelated target cannot supply the prerequisite. |
| World changes after observation | Freshness at read time cannot guarantee validity at action time. |
| Request accepted, effect absent or unknown | Execution evidence cannot silently become an observed outcome. |
| Sensor unavailable | Honest uncertainty and a defensible stop differ from guessing or indefinite investigation. |
| Conflicting current evidence | A later-listed observation does not automatically win. |
| Compatible unchanged conditions | Useful actions should remain possible without redundant checks. |
| Irrelevant uncertainty | A fact unrelated to the action should not impose a global stop. |
| Missing or incomplete requirements | An empty/partial list cannot establish readiness without a bounded completeness declaration. |

Use explicit assessment times, immutable sensor identities/versions and exact
requirement-set identities. Keep known false prerequisites distinct from unknown
conditions. In the first slice, candidate observation requests are declared by
the host requirement; a measured gain cannot be presented as autonomous sensor
discovery or discovery of previously unmodeled variables.

The hidden true state and expected action labels belong to the evaluator. Agents
receive normal requirements and equally available sensor results; fixture names,
metadata and retrieval must not disclose the answer. Failure and unavailable
information are ordinary outcomes of the measurement, not dropped cases.

## Matched comparisons

| Arm | Controlled difference |
| --- | --- |
| A: strong ordinary workflow | Evidence ledger, explicit preconditions, target/version binding, separate outcome checks and ordinary investigation. |
| B: explicit belief semantics | A plus working hypotheses, grounds, alternatives, uncertainty and conditions for revision in the agent context. |
| C: temporary maintained projection | B plus machine maintenance of the working state and action-readiness assessment. |

All arms receive the same standard authorization, capability, target/version and
conditional-operation checks. Otherwise a guard available only to C would
confound the effect of belief semantics with ordinary enforcement. Include a C
ablation retaining those guards and bookkeeping while removing explicit
uncertainty/alternative handling. A prompt-only win over A does not establish
that the runtime is needed.

Freeze information channels, tools, initial context, model and total budget.
Account for projection construction, updates, verification, observation cost,
failed attempts and human preparation. Record the allowed representation/state
difference as the treatment rather than pretending that all contexts are equal.

## Measurement and stopping

Report harmful attempted actions, false claims of completion, task completion,
unnecessary rejection, useful and redundant observations, human interruptions,
elapsed time, tokens, tool costs and maintenance. Preserve unknown outcomes and
severe failures separately from averages. A successful orchestrator call is not
a positive outcome label.

The independent unit is a task trajectory with its own reset state. Calls within
one trajectory are dependent. Separate development/pilot cases from later task
families kept outside selection and refinement. Before the main comparison,
freeze evaluator bytes, state schedules, budgets, outcome windows, practical
thresholds, harm limits, sample-size rationale and stop rules. Pilot outcomes
inform that design; they are not independent confirmation.

If A has no meaningful gap, stop expanding the mechanism. If B matches C at
lower cost, keep the instruction. If guards alone explain C's benefit, report
that result without attributing it to belief semantics. A negative empirical
result can narrow the implementation without erasing the useful conceptual
distinction between knowledge, observation, belief and commitment.

## Completion boundary

A future executable protocol must validate arm/trajectory separation, missing
costs, evaluator and protocol drift, hidden-state leakage, unavailable outcomes
and false completion claims. A rehearsal must verify the actual run setup and
justify the main design. No validator can certify independence merely from a
declaration. Report reproduction limits and null results alongside improvements.

The [roadmap](../../../ROADMAP.md#belief-runtime-development) owns implementation
and study status. Production sensors, broad unknown-variable discovery, learned
belief updates, calibrated VOI and multiagent nested-belief models require later
evidence and specific owners; they are not implied by this first comparison.
