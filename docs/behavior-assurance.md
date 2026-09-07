# Behavior assurance contract

EKK keeps four lifecycle dimensions separate for every decision or policy:

1. `owner_authorized`: an exact record revision has a valid acceptance receipt.
2. `evidence_supported`: the record declares an evidence assessment with pinned basis.
3. `implementation_verified`: the implementation declares a check result with pinned basis.
4. `observed_benefit`: an outcome assessment declares observed benefit with pinned basis.

`RealmService.assurance(scopes)` reports these dimensions independently. Missing
evidence stays `unknown` or `not_run`. Acceptance does not imply evidence support,
an implementation check does not imply product benefit, and provenance does not
make a claim true. An observed result also does not establish causality.

## Method profiles

A record that describes an operational method may include `method`. The profile
must state, as nonempty lists, `supported_work`, `guaranteed_result`, `checks`,
`assumptions`, `stop_conditions`, and `autonomy_boundary`. The guaranteed result
is the artifact or check the method actually controls. It must not promise the
quality of an arbitrary future task.

## Observation coverage

An accepted decision can register an `observation_gap` review trigger with named
`aspects` and `max_age_days`. Observation records identify their `subject`,
`observed_at`, and covered `aspects`. Review then reports missing and stale
aspects. The detector runs only for explicitly registered commitments and visible
records. It provides no scheduler, full-world scan, or claim of complete
observability.

## Experience compiled into rules

A decision or policy derived from experience may include `evolution`. It must
state applicability, rollback, origin scopes, and either `local` or `explicit`
propagation. Local propagation cannot expand beyond its origin scopes. Explicit
propagation requires pinned basis and remains subject to acceptance authority in
every target scope. This keeps removal and supersession possible and prevents a
useful local episode from silently becoming a wider rule.

## Runtime boundaries and use

These are opt-in runtime conventions over record format 0.1. The starter schemas remain unchanged. The English design-pack edition has its
own versions and artifact digests; see runtime-starter-provenance.md. Older clients can preserve the fields
without implementing this assessment; reading the same bytes does not confer the
same behavior guarantees. `ekk assurance --profile PROFILE --realm REALM --scope
CONTEXT_ID` returns this read-only projection. No combined success score is emitted.

An assessment is a **recorded claim**, not a certification by the storage kernel.
A pinned note alone does not prove benefit. The domain method owns evidence
adequacy, source independence and criteria. `scope_of_claim` can state exactly
what was assessed; when absent, the report explicitly infers no broader guarantee.
Inaccessible basis produces `unknown` without exposing its references. Acceptance
and context assembly include assessment and propagation dependencies in their
normal pinned-evidence and access checks.

New execution receipts retain `stages.observed = not_observed` after a verifier
runs; `stages.implementation` reports `verified` or `failed`. Existing immutable
receipts remain historical bytes: the old `verified_result` value described a
process check and must never be interpreted as demonstrated product benefit.

An observation trigger may include `starts_at` (timezone-bearing timestamp).
Before that instant it creates no gap candidate; observations before that instant
or after the current clock do not fill the window. Without `starts_at`, coverage
is assessed immediately. `max_age_days` bounds freshness, not truth. Legacy
subject-ID observations cover declared aspects, not a certified implementation
revision. Pin the assessed implementation in observation basis and use a new
window when that implementation changes. Hidden observations are not evidence
of coverage. No candidate means only that registered visible checks found no gap.

## Operational method envelopes

Apply these additions when doing the named work; do not silently rewrite installed
0.1 design packs or infer a capability from their existence.

| Method | Supported work and checkable result | Assumptions and stopping boundary |
| --- | --- | --- |
| Base | Capture exact supplied bytes, resolve authorized context, propose a scoped change, report source/interpretation/adoption separately. Check IDs, pins, receipts and read authority. | Only supplied or accessible evidence is covered. An unresolved mandatory constraint blocks the affected action. Zero new records is valid. |
| Software | Authorized changes to the existing product. Separately examine the user problem, requirements, implementation checks and observed use. Report exact revision, scenario and verifier scope. | Tests cover their specified behavior. Missing product feedback leaves benefit unknown. Stop the affected action for missing authority or an unresolved material requirement; do not invent a product objective. |
| Research | A bounded question, attributed sources, frozen comparison and reproducible measurement where available. Separate observation from causal hypothesis; preserve failures and correlated-source caveats. | A source count does not prove independence. If comparison or observation is inadequate, report effect not established; do not promote a plausible explanation into a rule. |

For autonomous software work, name the supported task class, allowed changes,
checks, impact limits and stop conditions before execution at a level proportional
to the task. Keep observation/testing access separate from authority for external
actions. Measure incoming-task coverage, acceptable outcomes without substantial
manual rework, failure severity, full cycle cost and later regressions together.

## Reversible evolution

Before compiling an episode into a rule, distinguish the product invariant from
its current implementation choice and the agent's working procedure. State a
counterexample, applicability and rollback. A local trial may justify another
trial; it does not prove a company-wide causal effect. Explicit propagation needs
readable pinned trial evidence and acceptance in each destination scope. These
structural checks do not verify the trial's quality or prevent a dishonest author
from misdescribing origin; current ownership and domain review remain necessary.

Use a new proposal/revision or same-scope `supersedes` to retire an obsolete rule;
retain old evidence and test both restored flexibility and preserved capabilities.
Absence of failures is insufficient grounds to remove a protection. An
unrepresentative episode may correctly produce no learning and no new rule.

When reviewing an important outcome, reserve a small task-appropriate discovery
budget for real scenarios, discrepancies with current code/runtime, and aspects
without feedback. This is a bounded investigation, not an automatic schedule or
permission to inspect another owner's system.

The [study amendment](../research/studies/sequence-learning/protocol-hardening-0.2.yaml)
requires equal engineering environments and total budgets, strong baselines,
ablations, adverse memory cases, held-out transfer and explicit falsification.
It remains `not_run`; use within the existing workflow without requiring migration.

Coverage observations must include the subject's scopes and a nonempty pinned,
readable evidence basis. Other-scope, ungrounded or inaccessible observations
remain stored information and do not suppress review. This admission check is
structural: it cannot establish honesty or source independence. Evolution origins
must resolve to real contexts. The envelope is opt-in; requiring it for every
policy would misclassify ordinary and historical policies as learned rules.

## Implementation decision

A read-only engineering consultation used the clean-boundary advisor
(`epistemic_contract`, Parnas) and production-risk advisor (`risk_evolution`,
Nygard). The selected boundary preserves the 0.1 storage contract and adds derived
assessments plus optional method conventions. Shared reference traversal and
subject-scope observation admission close the concrete access gaps identified by
the risk review. A universal success flag and automatic rule promotion were
rejected: the kernel does not own domain truth or product benefit. The suggestion
to require an evolution envelope for every new policy was not adopted because
ordinary policies need not be learned rules; explicit evolution remains opt-in
and this limit is documented. Confidence is high in the checked structural access
boundaries, not in empirical benefit. Reversal removes the projections and method
conventions without altering retained source bytes; original receipts remain
historical. Product-observation adapters and a controlled model study are still
needed to establish effectiveness.
