# Research protocol v0.1

Date: 2026-09-05. Status: draft, before the empirical run. Basis and source-text fingerprints: [README](README.md). No numerical results are available. This protocol is neither a completed experiment nor a public preregistration.

## Question and testable expectation

With model M held fixed, does evolution of the external project environment improve the quality and cost of solving subsequent tasks relative to memory and ordinary project context?

H1: condition D outperforms B on a criterion selected in advance that accounts for full cost; C allows assessment of the contribution of provenance, expectations, and reconsideration. A provides a baseline. Before running, select the primary contrast, the minimum useful effect, and the priority of quality relative to cost. Comparing late tasks with early tasks within one project does not by itself test H1.

Operationally, “fixed model” means a pinned model identifier and available version, identical generation parameters, and the same base agent harness. An available alias without a guarantee that the backend remains unchanged limits the strength of the conclusion. A model change starts a separate block/experiment; results from different models are not pooled under H1 without a separate analysis.

## 1. Functional smoke test and recursive use

The minimal scenario uses the kernel itself as its subject: a source/event, an initial interpretation, a commitment with an expected consequence, an observed result, and a decision to retain, reconsider, or remove a mechanism. A negative result is valid. Record references, temporal applicability, and the boundary of what was known at the time of the decision; reconsideration does not destroy the old grounds.

Smoke checks must answer specific questions: can context be reconstructed from canonical materials; is future information kept distinct from what was known earlier; are affected dependencies reached; can a proposed change be distinguished from an active commitment; are the previous version and source preserved? Report specific coverage after running implementation tests.

Recursive research uses the same mechanism to investigate the mechanism itself. For example: “Do explicit provenance links help reconsider a decision more accurately?” The expectation, experience, and protocol revision are addressable in the EKK store, while the original experimental data remain with their owner, with a reference and fingerprint. A new protocol version does not retroactively change the success criterion for earlier experience.

Smoke status in this document: **unconfirmed**; the integrator reports actual checks separately. H1 status: **pending**, regardless of the smoke result.

## 2. Future longitudinal A/B/C/D design

The original dialogue proposes several long-lived software projects and a tentative range of 50–200 sequential tasks per project. This is a design idea, not a justified sample size. The size and number of independent repetitions are determined after estimating variance, cost, and power.

| Condition | Available environment | Permitted accumulation |
| --- | --- | --- |
| A — stateless baseline | Current code and the same initial ordinary docs | Code changes through tasks; there is no agent memory across sessions |
| B — memory | A + history and retrieval | Experience may be stored and retrieved; a separate reconsideration/evolution mechanism is disabled |
| C — evolutionary knowledge | B + provenance, commitments, expected and actual outcomes, reconsideration | Semantic state evolves; automatic harness evolution is prohibited |
| D — full evolutionary environment | C + changes to policies, tools, invariants, and the context compiler | Environment changes are verified and versioned, including removal of what is no longer needed |

For each condition, define in advance exactly what counts as ordinary docs, memory, a tool, and an application change; otherwise A can quietly acquire C, and B can become D. Ordinary code changes required by a task are available to all conditions; changes to the tooling used to solve tasks belong to D. The initial harness, access to external tools, and base budget are identical; D's adaptations are the intervention under study and are included in its cost.

The unit of condition assignment is an independent project trajectory, not an individual task: accumulated state makes sequential tasks dependent. Initial snapshots are identical within a project. Use multiple replicas/seeds and projects, balanced assignment, and an identical task sequence or prespecified comparable sequences. Task order respects real dependencies rather than being shuffled arbitrarily.

Tasks include requirements changes, returns to familiar components, violations of past assumptions, and architectural changes. Early and late checkpoint evaluations are comparable in difficulty. Training tasks, pilot data, and the evaluation holdout are separated before the run.

## 3. Leakage and independent evaluation

Holdout solutions, hidden tests, and evaluation rubrics are unavailable to the agent and context compiler. Memories, fixes, derived tools, and evaluator experience are not copied between conditions. Isolation covers file directories, retrieval indexes, and the agent's external memory. Permitted feedback on training tasks is identical and specified in advance.

Do not repeatedly use the hidden holdout to tune the protocol. Pilot work and tuning use separate data. If adaptive evaluation is needed, reserve a new holdout and mark the previous one as exposed. Generator and evaluator metrics must not be editable by the kernel under study; improvement in self-evaluation without external verification does not count as improved quality.

Evaluation relies on independent tests and a rubric applied blind to condition where tests are insufficient. An additional LLM review does not by itself guarantee independence. Subjective human convenience is retained as a subjective assessment, without substituting it for a correctness metric.

## 4. Metrics and cost

Before the main run, select one primary metric, the primary contrast, checkpoints, aggregation rules, and a stopping criterion. One candidate is the proportion of tasks whose results are independently confirmed under a fixed full budget. The confirmatory experiment does not begin until these parameters are fixed.

| Dimension | What to retain |
| --- | --- |
| Result | Success under independent verification; partial success under a specified rubric; failures and omissions |
| Regressions | New defects, severity, recurrence of a known error; a uniform detection method |
| Cost | Tokens/requests, actual price, wall-clock and active time, compute/tool costs |
| Context handling | Navigation time and tokens, amount of supplied context, compilation/storage cost |
| Environment evolution | Time to create, verify, and maintain tools/policies/invariants; removal and the number of unnecessary interventions |
| Human | Number of escalations, work minutes, reason for assistance, intervention content, decision author |
| Project change | Change coupling under a prespecified measure; changed modules; task complexity |
| Explainability and reconsideration | Fidelity to the reasons for an earlier decision; detection of obsolete commitments; false alarms |
| Calibration | Agreement between expectations recorded in advance and outcomes; uncertainty and effect delay |
| Reproducibility | Model/provider/version, parameters, harness/kernel/protocol commit, compiler/tool versions, seed, and data snapshot |

Account for full cost and payoff over the time horizon: faster execution with more expensive environment maintenance does not imply a net benefit. Equal budgets and naturally consumed budgets answer different questions; present both only if the design provides for this.

## 5. Confounders and analysis

Key confounders: later tasks are easier; the human has learned and provides more help; the context budget grows; the provider updates the model; the compiler receives future solutions; the evaluator changes; external dependencies or hardware change timing; D gets more attempts; unsuccessful trajectories are excluded; the code itself accumulates solutions useful to all conditions.

Fix or balance these factors and disclose residual limitations. Tasks within one trajectory must not be treated as independent replications: the analysis accounts for the project/trajectory as a cluster and for sequential dependence. Report the effect with an uncertainty interval, full costs, the trajectory across checkpoints, and every assigned replica, including stopped ones. Rules for missing data, exclusions, multiple comparisons, and early stopping are fixed before inspecting the main results.

New protocol changes suggested by dogfooding are the subject of a separate experiment and method version. A confirmatory experiment must not quietly optimize its own success criterion. Model-upgrade replay may later address a separate question: can a newer model safely remove obsolete scaffolding? It is not combined with fixed-model H1.

## 6. Retention and limits of inference

Collect enough measurements for the assigned experiment without retaining all conversations and telemetry by default. Before running, define sampling, retention periods, access, and the minimum set needed for reproduction. Retain significant negative and interrupted results; do not disguise deletion of a sensitive source as preserved provenance. Derived conclusions must reflect unavailable grounds.

Neither the current bootstrap nor one successful recursive iteration confirms scientific novelty, universality, causal improvement, or endless development. A literature review and verification of source citations are separate future work. Publication is possible after data and reproducible analysis; no external actions are being performed at this stage.

Still open before the empirical run: project and task sets, exact model, budget, sample size, minimum useful effect, primary metric, blind evaluator, holdout, and retention. This is the boundary of the prepared protocol, not work silently treated as complete.
