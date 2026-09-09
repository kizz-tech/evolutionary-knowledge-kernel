# Open research agenda

**When does past work make future work better?**

EKK investigates how experience from people and AI agents can become capabilities
that persist, transfer to another participant, and change when their assumptions
fail. We want to understand which parts of a working environment help its next
participant solve a new task, at what cost, and under which conditions.

Four questions make the ambition concrete: what must travel with a useful
method; how to repair work built on a mistaken premise; how to tell whether
an apparent improvement survives independent evaluation; and what current
observations make the next action defensible. The nine questions below
connect that ambition to experiments and product decisions.

This is an open research program, updated **2026-09-09**. All nine questions remain
open. EKK has implemented record, continuity and method-lifecycle mechanisms;
their tests establish bounded implementation properties. Empirical productivity,
general transfer and human learning benefits have not been established. Existing
research overlaps with this program; a question here is not a claim of priority
or evidence that no solution exists. See the [selected related work](related-work.md).

## How to use this agenda

Start with the [first proposed study](studies/method-applicability/README.md) for
a concrete comparison, the [roadmap](../ROADMAP.md) for dependencies and completion
criteria, or [contributing](../CONTRIBUTING.md) for a bounded way to help.

The question IDs are stable by meaning. Their order does not imply nine parallel
projects or a ranking of importance. Each hypothesis below is a proposal to test.
The first study covers a small part of LIF, CIN and XFR, with EVA and UNK shaping
the measurement. REP, COL, HUM and CMP require their own designs.

The selected [Belief Runtime concept](../docs/belief-runtime.md) develops UNK as
an explicit observation/belief/action loop. Its separate
[action-readiness comparison](studies/action-readiness/README.md) can share
applicability cases where the prerequisite must be observed, while preserving
distinct arms and conclusions. Selecting this direction establishes no empirical
answer to UNK and does not renumber or merge the nine questions.

| ID | Open question | First useful evidence |
| --- | --- | --- |
| [EKK-Q-LIF](#lif) | Can external experience support sustained improvement? | Later-task benefit that survives cost and condition changes |
| [EKK-Q-CIN](#cin) | What should change after an ambiguous failure? | A diagnostic observation leading to a better intervention |
| [EKK-Q-XFR](#xfr) | What makes a capability transferable? | Useful transfer with compatible and incompatible controls |
| [EKK-Q-REP](#rep) | How do we repair consequences of mistaken knowledge? | Affected artifacts repaired while independent work stays valid |
| [EKK-Q-EVA](#eva) | How do we evaluate an adapting system? | Independent later outcomes with all selection costs counted |
| [EKK-Q-UNK](#unk) | When is more investigation worth its cost? | Fewer missed constraints without unnecessary investigation |
| [EKK-Q-COL](#col) | Can participants learn together under different rights? | Useful permitted transfer under an explicit threat model |
| [EKK-Q-HUM](#hum) | Which human capabilities should assistance help preserve? | Better joint work and the participant's chosen independent skill |
| [EKK-Q-CMP](#cmp) | When do independently useful methods work together? | Interaction failures detected without blocking compatible changes |

<a id="lif"></a>

## EKK-Q-LIF: Sustained improvement from external experience

**Question.** With a fixed model, bounded active memory and full maintenance cost,
when does accumulated experience improve later work despite obsolete or mistaken
lessons?

**Hypothesis and first test.** Separating preserved history, selected context and
the method used for an action may reduce harmful transfer. Compare a strong
ordinary workflow, retrieved history, an existing adaptive method and EKK through
acquisition, new tasks and a relevant condition change. Preserved history need not
all govern the next action.

**Measure and challenge.** Report later-task quality, regressions in requirements
that still apply, harmful transfer, recovery time and maintenance cost per
independent trajectory. A legitimate changed requirement is not forgetting.
The hypothesis loses support if its advantage disappears with equal total budgets,
a longer horizon or an independent task family, or hides rare severe harm.

EKK provides versioned history and retrieval. A policy with demonstrated sustained
benefit remains to be established.

<a id="cin"></a>

## EKK-Q-CIN: Choosing the right intervention

**Question.** After an ambiguous failure, should the system change code, knowledge,
a tool, retrieval, evaluation, the task framing, or its understanding of the cause?

**Hypothesis and first test.** A low-cost distinguishing observation may be better
than an immediate edit. Use controlled cases with different hidden causes: an
obsolete method, a broken tool, a changed requirement, or no need for a change.
The investigator knows the cause; the agent receives ordinary observations and
diagnostic tools whose costs are counted.

**Measure and challenge.** Measure the result after intervention, unnecessary and
missed changes, diagnostic cost and damage from a wrong choice. Naming the cause
correctly is insufficient. A hypothesis fails if plausible explanations do not
improve action over a simple diagnostic workflow, or fail on a new cause.

EKK's records can preserve evidence. They do not automatically identify causes.
The first applicability study tests only a narrow intervention choice; broader
architectural and product decisions remain open.

<a id="xfr"></a>

## EKK-Q-XFR: Transferring a capability and its conditions

**Question.** What must another participant receive to solve a new task, and how
can they detect incompatible models, tools, concepts or operating conditions?

**Hypothesis and first test.** A procedure with testable prerequisites and
counterexamples may transfer better than a summary at comparable preparation
cost. Compare a trace, a concise procedure and a procedure with conditions on new
task instances. Change participant, model and tool separately; include cases
where the method should remain useful and cases where it should not apply.

**Measure and challenge.** Measure quality within a complete budget, harmful
transfer among incompatible cases, unnecessary rejection among compatible cases,
and preparation, admission and use costs. An apparent benefit fails the test if
it relies on a curator selecting the right skill, stored test answers or free
expert help. A renamed copy of the training example is insufficient evidence.

EKK can transfer exact permitted bytes and require receiver-owned evaluation and
admission. Those properties do not establish transfer of ability or authority.

<a id="rep"></a>

## EKK-Q-REP: Repairing consequences of mistaken knowledge

**Question.** Once a premise is disproved, how can we find and repair affected
decisions, documents, tests and code while preserving independently justified work?

**Hypothesis and first test.** Re-establishing grounds and checking impact may
outperform editing the source alone or invalidating every linked descendant.
Use a synthetic project with known causal history, some missing links and valid
independent grounds. Compare source editing, link-based invalidation and repair.

**Measure and challenge.** Count uncorrected consequences among affected artifacts,
damage to valid artifacts, repair cost and delay, and reappearance through a
summary or cache. Unknown impact must stay explicit. Updating a note while faulty
code remains, deleting correct work, or treating missing history as proof of no
impact is a failure.

Recording an objection or stopping a method does not repair existing outputs.
Changing knowledge also cannot reverse an external action; compensation belongs
to its owner. This question is a separate study after applicability, unless
observed downstream harm makes it the more urgent problem.

<a id="eva"></a>

## EKK-Q-EVA: Evaluating an adapting system

**Question.** How can we establish useful improvement when the system proposes
candidates, selects experience and may influence its own evaluation?

**Hypothesis and first test.** Independent later tasks, frozen criteria and a
record of every attempt may reduce admission of changes that improve a visible
score but harm the actual task. Include useful, neutral and harmful changes.
Fix evaluation, attempt budgets and stopping rules before the main comparison;
changing the evaluator is a separate experiment.

**Measure and challenge.** Report false admissions and rejections, held-out
effects, selection and evaluation cost, harm distributions and uncertainty across
independent trajectories or projects. Calls within one history are dependent.
An effect that vanishes outside selection tasks or requires weakening the
evaluator does not establish benefit. A file called a holdout is insufficient
if repeated adaptation can learn from it.

EKK receipts and harnesses verify declared contracts and provenance. They do not
authenticate every observation or guarantee evaluator independence. Compare
different experience on fixed code separately from divergent product development.

<a id="unk"></a>

## EKK-Q-UNK: Current understanding and when to investigate

**Question.** When should a participant act, read a source, run a diagnostic test,
or ask a person, given uncertain current-world conditions and requirements of
the proposed action, especially when the full set of possible problems is unknown?

**Hypothesis and first test.** Seeking observations that can change the decision
may reduce errors without endless clarification. Hide a relevant condition,
provide diagnostic observations with different costs, and add a plausible wrong
explanation. Include controls where no further investigation is useful.

Develop an action-scoped working belief from permitted knowledge and
observations, keeping proposition, target/version, grounds, acquisition mode,
currentness and relevant alternatives separate. Compare a strong ordinary
evidence/precondition workflow, explicit belief semantics, and a machine-maintained
projection. Give every arm the same sensors, authority/conditional-action checks
and full budget; include an ablation that removes belief semantics while retaining
those checks. Stale, wrong-target, conflicting and unavailable observations must
be distinguished from useful unchanged controls.

**Measure and challenge.** Measure missed constraints, completed tasks, useful and
unnecessary investigation, and avoidable human interruptions. Do not demand
recovery of a hidden fact without an available information channel. Asking
everything, never finishing, or acting confidently when available evidence cannot
distinguish consequential states are failure modes.

Measure false action-readiness and false completion claims separately from
unnecessary stopping. A tool receipt is not an observed outcome. Include changes
between observation and action and sensors that fail or cannot observe the
relevant state. This tests a known set of requirements; open discovery of missing
variables and general value-of-information policies remain further questions.

EKK can expose bounded context coverage and unavailable sources. Complete delivery
of selected records does not mean sufficient knowledge about the world.

<a id="col"></a>

## EKK-Q-COL: Learning together under different rights

**Question.** How can participants transfer useful methods without transferring
forbidden information, dependencies or another owner's execution authority?

**Hypothesis and first test.** Re-derivation from permitted grounds or a reviewed
method release may preserve useful transfer. Start with two synthetic owners,
different secrets, an explicit sharing policy and a defined threat model.
Compare no transfer, independent re-derivation and authorized transfer.

**Measure and challenge.** Measure permitted transfer value, forbidden information
flows and actions, review cost and test coverage across outputs, delegation,
summaries, logs, tools and restored derivatives. Generalizations can themselves be
confidential. Removing names or failing to find one secret marker does not
establish privacy; refusing all transfer does not solve useful collaboration.

EKK has owner and scope boundaries. Their existence is not a general guarantee
about semantic disclosure or OS process isolation. Real organizations require
their own participants, permissions and study design.

<a id="hum"></a>

## EKK-Q-HUM: Human capability, purpose and control

**Question.** How can assistance improve joint work while preserving or developing
the capabilities a person actually wants to retain?

**Hypothesis and first test.** Chosen modes of execution, explanation and
investigation may affect understanding and control differently from completion
speed. With voluntary participants and a skill they select, compare an ordinary
assistant, broad delegation and the experimental environment. Include a new task,
a delayed independent task and mistaken advice.

**Measure and challenge.** Measure joint quality, reconstruction of grounds, error
detection, continuation with a different tool, delayed chosen-skill retention,
human time and perceived control. Participants retain the right to delegate
details they do not want to learn. A speed gain that erodes their chosen skill or
hides training hours is insufficient. Research evaluation must remain separate
from employer assessment.

An accepted record does not demonstrate understanding. No participant cohort or
human study has been started for this agenda.

<a id="cmp"></a>

## EKK-Q-CMP: Composing independently evolving methods

**Question.** When do individually useful changes preserve useful behavior
together, and when do they violate one another's assumptions?

**Hypothesis and first test.** Targeted interaction checks may detect some
regressions more cheaply than complete re-evaluation. Use methods that pass
independent checks but conflict together, alongside compatible pairs. For example,
one method assumes a fresh read while another introduces caching. Compare
independent admission, full re-evaluation and checks of interacting prerequisites.

**Measure and challenge.** Measure missed joint regressions, unnecessary delay of
compatible changes, coordination and evaluation cost, cascade size and time to
localize failure. Individual percentage gains cannot be added. Only detecting
manually signposted conflicts or repeating every test without saving cost would
undermine the hypothesis.

Versions and local admission do not establish semantic compatibility. More agents
alone are not evidence of improved composition.

## What counts as progress

Progress means reducing an uncertainty enough to change a decision. Keep distinct:
question framing; measurement readiness; empirical findings; and observed practical
benefit in a named setting. A counterexample, failed replication or cheaper
alternative can be a useful outcome.

Every result should identify its question and hypothesis, compared versions,
task owners and conditions, independent unit, denominator and window, full costs,
uncertainty, limitations and the decision it changes. Preserve earlier findings
when an interpretation changes. Unmeasured values remain unknown; there is no
combined percentage of this research program being solved.

Revisit priorities after a pilot, independent replication, material counterexample,
relevant new work or a changed user need. The [roadmap](../ROADMAP.md) records the
next deliverables and their gates.

This English text is an editorial adaptation of owner-supplied research drafts
and the subsequent working synthesis. The original bytes are preserved separately;
[provenance](agenda-provenance.json) identifies the inputs and this edition.
