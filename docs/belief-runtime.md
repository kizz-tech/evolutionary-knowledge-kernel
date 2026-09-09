# Belief Runtime: current understanding before action

**Conceptual direction selected on 2026-09-09.** This contract develops EKK's
connection between durable experience and present action. Selection of the
direction is separate from implementation, execution authority and evidence of
usefulness. Record format `ekk.record/0.1` is unchanged.

## Responsibility

Derive a temporary, action-scoped assessment from authorized EKK context,
host-supplied requirements and current observations. State what is supported,
what is uncertain or contradicted, and which available observation could change
the decision. The owning system retains the world state; EKK retains significant
history, sources, commitments and revisable experience.

The fast loop is:

```text
authorized knowledge + current observations + action requirements
                  -> working belief / assessment
                  -> next observation or separately authorized action
                  -> separate outcome observation
                  -> revised working belief
```

Significant results can feed the slower method-evolution loop. No universal
confidence score, complete world ontology or canonical belief database is
required. A saved projection carries its exact inputs and time as a historical
account, never a current-state fact or reusable execution permit.

## Minimum semantics

| Element | Required meaning |
| --- | --- |
| Proposition | A specific, contestable condition relevant to a proposed action. |
| Target | Exact object, environment and version or consistency token where available. |
| Grounds | Permitted exact source/observation references; absence of access is not absence of a fact. |
| Acquisition | Observed, inferred or assumed; unknown remains expressible. |
| Currentness | Observation time and explicit invalidation conditions; freshness is not truth. |
| Alternatives | Decision-relevant competing explanations; contradiction is not resolved by record order. |
| Requirement set | Exact action identity, requirement-set version/digest, and host-declared completeness: `complete`, `incomplete` or `unknown`. |
| Requirement | What evidence and uncertainty are adequate for this action, supplied by its host/domain. |
| Assessment | Requirements met, known not met, a host-declared observation is missing, or the state remains indeterminate. |

The host supplies `assessed_at` explicitly. Each observation carries an immutable
identity, sensor ID/version, exact target, observed time, status/value or a payload
digest, and a consistency token where available. This binds the assessment to
reconstructable inputs without reading an implicit clock or querying a system
inside the projector. Future-dated or unavailable observations cannot satisfy a
current-observation requirement.

These are semantic distinctions, not new mandatory fields on every stored
record. Acquisition, currentness and conflict are independent axes. A direct
observation can be old, partial, cached, wrong-target or disputed. Multiple
derivatives of one source do not create independent evidence. Missing relevant
variables cannot be discovered by a schema alone.

Incomplete or unknown requirements yield `indeterminate`, never readiness. An
empty list alone does not declare completeness. Even a complete declaration is
the host/domain's bounded claim about this action, not a proof that every unknown
variable has been found. Current context blocks and unavailable mandatory grounds
remain restrictions; they cannot be cleared by a favorable belief projection.

An action with unmet relevant requirements is ineligible under this assessment.
`needs_observation` may only echo opaque observation-request IDs declared by the
host requirement. The host supplies relevance, availability and cost and checks
permission again before a request runs. Registry membership is not an execution
grant. The projector must not invent a sensor, executable command, credential or
new scope, and does not establish the empirical usefulness of that observation.
`indeterminate` preserves missing requirements, unavailable information channels
or unresolved alternatives. Requirements met means only the supplied epistemic
contract is satisfied, not that the world is fully known or execution permitted.

Known falsity of a prerequisite is `requirements_not_met`, distinct from lack of
information. It may require a different plan or action; repeating an observation
without a reason to expect changed information is not a universal remedy.

Investigation is bounded by its decision value and full cost. Prefer observations
that can change the next step; do not demand certainty about irrelevant facts or
invent calibrated probabilities. A qualitative decision-value rule is sufficient
until a quantitative model is justified and validated.

## Authority, concurrency and outcomes

Execution requires the conjunction of adequate current grounds, current host
authority and existing capability/acceptance checks. The epistemic component
can restrict action eligibility; it cannot expand any of those permissions.
Observation tools can themselves have cost, disclosure or side effects and need
their own authority.

Recheck relevant invalidation conditions immediately before a consequential act.
Use owning-system version checks, transactions or conditional operations where
available. A TTL or fresh snapshot does not eliminate the interval between check
and use. If the host cannot bind the action to the observed state, preserve that
residual risk instead of claiming atomicity. Changes by this or another actor
invalidate affected beliefs; handoff does not restart their lifetime.

Keep four execution facts separate:

1. **Action attempt:** what was requested, against which target and grounds.
2. **Effect receipt:** what the executor or orchestrator actually confirmed.
3. **Outcome observation:** what a separate sensor measured after the attempt.
4. **Outcome assessment:** interpretation of that observation and its limits.

An accepted request, exit zero or successful implementation verifier never
automatically fills the last two. Timeout, partial visibility and unavailable
sensors may leave the outcome unknown. Reconciliation must not blindly repeat
an action whose effect may already have occurred. Observation alone does not
establish causal attribution or user benefit.

## A bounded coding scenario

A proposed change requires schema 184 in a selected environment. CI succeeded
for commit A; the working tree is now B. A deployment request was accepted, while
the separate schema sensor still reports 183. These are compatible observations
about different stages, not permission to infer that the prerequisite holds.

The assessment must preserve target and version distinctions, identify the
missing requirement and leave the change ineligible. A direct suitable
observation of 184 can satisfy the epistemic requirement, subject to freshness
and conflict checks. Authorization and the final conditional action remain with
the host. A later world change invalidates the assessment even when the same
historical source bytes remain intact.

## Implementation and evidence boundary

The existing runtime supplies observations, authorized context, repository
evidence, observation-gap review, capabilities and staged execution receipts.
The bounded working slice is
[`assess_action`](../src/ekk/application/beliefs.py): a pure Python application
projection over typed host-supplied requirements and interpreted observations.
It checks declared completeness, exact target/version, acquisition mode,
observation age, invalidation, unknown values and conflicting alternatives.
Known false prerequisites return `requirements_not_met` when the overall assessment
is otherwise valid. Blocked/incomplete context or invalid target inputs take
precedence as `indeterminate`; individual refuted conditions remain visible.
Only matching available
host-declared observation-request IDs can be recommended. A blocked EKK context
remains a restriction.

Each output contains the exact normalized inputs, their digest, the requirement
set digest and the explicit assessment time. It is labeled
`historical_projection`, with no authority effect, execution or inferred outcome.
Calling the function again is necessary after a relevant change; retaining or
reloading its JSON does not revalidate anything. This function does not parse
source payloads, authenticate a sensor, establish requirement completeness,
discover missing variables or verify host permissions. Its `Observation` inputs
are fallible domain interpretations with pinned sensor grounds; their `mode`
describes how the proposition was obtained, not a certification of raw evidence.

Run the resettable local demonstration:

```sh
.venv/bin/python examples/action_readiness.py
```

It covers current matching evidence, old-commit CI, the wrong environment, a
receipt without a schema observation, a known false prerequisite, expired
handoff inputs, unavailable sensing, changed world versions and a context hold.
It performs no actions and makes no model calls. The Python API is experimental.
Runtime 0.7 also provides the manual [coding readiness](coding-readiness.md)
adapter: `ekk assess` obtains bound context, exact Git identity and configured
report bytes. Known incomplete context cannot be cleared by matching reports.
There is no automatic sensor loop or capability enforcement integration.
Before real execution, the host must recheck its current authority, context and
target state and perform the appropriate conditional action. The projection
cannot enforce that behavior outside its caller.

The installed-CLI [coding example](../examples/coding_readiness.py) additionally
runs real disposable fixture tests, refreshes report evidence after commit
changes, and distinguishes an accepted request from a separately observed effect.
The driver owns those local actions; the assessment operation remains read-only.

These pieces do not establish a complete Belief Runtime or useful autonomous
sensor selection. The implementation status is tracked in the
[roadmap](../ROADMAP.md#belief-runtime-development).

The first comparison is specified in
[action readiness under partial observation](../research/studies/action-readiness/README.md).
It must distinguish ordinary preconditions and evidence, explicit belief
semantics, and a machine-maintained projection under equal information and full
cost. Contract checks establish mechanism behavior; held-out comparative runs
are needed to establish benefit. Negative findings may justify keeping a smaller
implementation while retaining the conceptual distinctions.

The design follows the completed clean-boundary and evolutionary-pragmatism
reviews. Their tension was whether the useful seam already justified a new
runtime. The owner selected conceptual development; the comparison preserves
the strong ordinary alternative. Proposed port names or snapshot layouts are
not stable public APIs merely because the architecture describes their role.
