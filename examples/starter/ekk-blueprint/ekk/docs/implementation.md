# Agent implementation task for EKK

## Input and outcome

Study the user's current working repository, `architecture.md`, `../spec/contract.md`,
and real examples. If the user has already implemented part of the kernel, briefly
map existing components to the target architecture and reuse compatible parts.
This specification is not grounds for rewriting all working code.

The first pass should produce a local vertical slice that reads a realm, allows a
change to be proposed and safely applied, supplies context through a binding, and
retains a verifiable significant observation. A server, web UI, or swarm is not needed.

Do not create placeholder classes, repositories, agents, and files for every future
capability. Do not report that migration is complete if only frontmatter normalization
has been performed.

## Stage 1. Format and pure reading

Implement the parser, IDs, resolver, schema/version handling, source pinning, and a
data snapshot. Preserve unknown fields through a round trip. Distinguish format
validity from confirmation of truth, authority, or productivity. New mandatory
semantics require a version.

Criteria: reading without an LLM; stable IDs on moves; no duplicate IDs; handling of
broken local links; explicitly unverified external links; preservation of original
source bytes; an error for an unknown mandatory capability; symlink and path
traversal checks.

The current `tools/validate.py` can be reused as a test foundation, but it does not
replace a version store, authority resolver, or runtime. Do not expand the production
API around the utility's implementation details.

## Stage 2. Writer and recovery

Implement propose/apply with an expected snapshot, idempotency key, writer
lease/serialization, change preparation outside the published tree, validation,
and an atomic switch of the published ref. Readers are bound to snapshots. A manual
working directory must not be declared a transactional store.

Actual test results must include: repeating one request; two changes to one revision;
two independent changes; a crash before and after publication; source failure; a
rollback attempt after someone else's change; a policy change after proposal preparation.

External file changes and uncommitted data require recovery of the actual bytes,
not just restoration of Git HEAD. Do not write to the original LIFEOS before a
separate authorized stage.

## Stage 3. Binding and context

Implement local profiles and explicit realm alias resolution. There is no global
scan of all the user's folders by default. A conflicting or missing binding is not
resolved through a whole-vault fallback.

Context includes mandatory constraints of the selected scope, current accepted
decisions, their grounds, relevant history, conflicts, and unknowns. The manifest
includes exact snapshots, policy/pack digests, sources, and incompleteness. Lexical
search and explicit links are sufficient initially.

When the budget is insufficient, mandatory constraints must not be silently
truncated. Do not promise completeness for constraints that were never registered.
Do not run commands from a source.

## Stage 4. Work and significant retention

Implement capture/proposal for a new source, observation, and outcome. Zero writes
after a trivial task is acceptable. A consequential commitment is accepted within
delegated rights and bound to exact bytes. Automatic confirmation is permitted only
for a previously authorized class of operations, not on an unsupported `accepted: true`.

Connect one existing project without moving its deployment and tests into EKK.
Show a real task in which a retained constraint influenced an action, and a task
in which detected uncertainty was not turned into a fact.

## Stage 5. Migration

Use `migration.md`. Start with a pilot context in a separate copy. Verify ledger
completeness, provenance, and key queries. Switch only a context whose migration
has been demonstrated. Do not automatically publish any LIFEOS source.

## Stage 6. Review and research

Introduce selected triggers, an explicit attention budget, success/removal criteria,
and links between expectations and outcomes. Replay and the held-out evaluator
must remain outside the experiment's mutable scope. Separately compare a new model
with the previous and simplified scaffolding.

## Definition of done

Readiness is demonstrated through separate results: format, safe writing, recovery,
access restriction, semantic usefulness, and effect on real work. One green
`doctor` cannot replace all of them.

After each stage, provide: commands that actually work; files changed; checks and
results; remaining limitations; and the next smallest unmet contract. Do not generate
a report of benefits that nobody has measured yet.
