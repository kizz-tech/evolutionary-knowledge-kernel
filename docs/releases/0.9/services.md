# Owners and integration boundaries

This release coordinates existing owners; it does not create new services merely
because a capability has a separate logical role. Exact private paths and host
receipts belong in the private handoff, not the public release package.

| Owner / repository | Responsibility in 0.9 | Does not own |
| --- | --- | --- |
| `evolutionary-knowledge-kernel` application/model | Experience profile, pure selection/projection contracts, correction semantics, exact evidence relations | Host logs, MLX, processes, inference credentials or arbitrary execution |
| EKK adapters/CLI | Authorized source access, operational buffer adapter, existing writer/outbox integration, work/search/recall operations | A second canonical writer or authority inferred from model output |
| Host integration tooling (private) | Inspect supported event/focus interfaces; capture/delivery adapter; explicit source enrollment, settings, lifecycle and enrolled-profile integration | Credentials, unrelated profile settings or unsupported Desktop internals |
| `ekk-gateway` (private adapter) | Narrow operations over kernel contracts, pinned configured route/actions, supported client coverage and limits | Caller-selected roots, profiles, principals, model executables or private data pooling |
| Laya-MLX / optional observer adapter | Local inference using pinned checkpoint/runtime, bounded inputs and fallible typed advice | Observation truth, canonical writes, authority, memory deletion or policy admission |
| Future observer OSS project, not created | Potential reusable episode/advisor contracts, permitted dataset tooling, training/calibration and model cards | EKK ownership/governance, private host integration or a competing canonical memory store |
| Domain project or author | Original code/documents, tests, design system, external tasks and real outcome interpretation | A duty to keep a parallel EKK diary |
| User / data owner | Product direction, data-use boundaries and consequential scope choices | Routine curation of every candidate |

Human assignees are not invented. These are responsibility boundaries for later
implementation in this task or another authorized task.

## Integration order

1. Inspect actual host capabilities and record the usable event/recall boundary.
2. Establish neutral contracts, evidence identity, storage/revision and cost bounds.
3. Implement candidate handling and canonical retention; then recall and correction.
4. Wire the proven host path and narrow Gateway/CLI surfaces.
5. Add optional shadow advice and its bounded data/evaluation work independently
   of the core behavior.
6. Prepare the frozen reviewed release, verify the installed composition and
   activate the declared local surfaces with a disable/rollback route.

Private Gateway support must report which client behaviors were actually
observed. A readable MCP operation is not a live event hook or proof that an
already-open chat refreshed its tool catalog.

## Existing work and concurrent development

The development checkout contains unrelated and pre-existing changes. Establish
an owned baseline before implementation. Do not reset, broadly stage or publish
that history. No worktree is implied by this plan.

[Laya advisory](../../plans/laya-advisory/status.md) remains authoritative for its
own completed shadow envelope and pending search work. This release may reuse
that interface pattern; it neither marks its later tasks complete nor requires
automatic search reranking. Update that spec only for a concrete shared change,
with its current owner and authority taken into account.

Shared instructions and profile projections stay in their current host owner.
Preserve selected models, permissions, routes and unknown local differences.
Install/configuration work follows the existing owner workflow when authorized;
none is performed by creating this release package.

An OSS extraction should start as a module/contract boundary until it has an
independently useful API. Choose the repository account, name, license, data and
publication target before external creation. Do not make repository creation a
dependency of the local experience workflow.
