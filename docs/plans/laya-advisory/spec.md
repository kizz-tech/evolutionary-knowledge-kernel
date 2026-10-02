# Laya advisory decisions for EKK

Status: approved for bounded implementation on 2026-09-21. This specification
does not claim that Laya improves retrieval or that any model decision is safe to
apply automatically.

## Outcome

Add a local, optional semantic advisor that helps an agent inspect already
authorized EKK search candidates. Begin with low-consequence decisions where a
wrong answer cannot hide context, alter authority, write knowledge, or dispatch an
effect. The agent retains the original candidate order and can verify any model
suggestion through the existing exact-read path.

## First use case

Given a task and a bounded list of candidates that the application has already
authorized, Laya may label each candidate as `primary`, `supporting`,
`background`, or `irrelevant`. The result is a shadow report beside the unchanged
baseline. It is not applied to search, context assembly, byte-budget selection,
retention, acceptance, review, or execution.

## Invariants

1. Authorization, realm, scope, mandatory commitments, exact references,
   dependency closure, conflicts, byte budgets, and execution authority remain
   deterministic application concerns.
2. The advisor receives only bounded summaries of candidates already selected by
   the authorized application projection. It never discovers or requests hidden
   candidates.
3. Model output cannot add, remove, reorder, accept, supersede, govern, retain, or
   execute anything. The baseline is returned unchanged.
4. Every advisory result identifies the model and revision, preserves the exact
   candidate reference, reports probabilities, and requires agent recheck.
5. Missing, malformed, slow, or unavailable model output yields an advisory
   failure only. Existing EKK behavior remains available and unchanged.
6. Personal and company source bodies are not pooled into a shared training set.
   Initial training uses synthetic or explicitly declassified fixtures. Any later
   owner-specific data and checkpoint remain owner-scoped.

## Non-goals

- No automatic semantic filtering or context reranking.
- No model-selected permissions, scope, owner, truth, adoption, or action.
- No direct dependency from the EKK kernel on MLX, Laya, PyTorch, a model path, or
  a subprocess.
- No harvesting of private task text or record bodies for training by default.
- No claim of product benefit from mechanism tests or a small synthetic benchmark.

## Acceptance gates

- Shadow output contains exactly the baseline candidates in their original order.
- Advisory labels can be inspected but are never applied.
- Invalid or unavailable advisor output cannot fail the baseline operation.
- Tests cover candidate preservation, bounded input, malformed probabilities,
  unknown candidate IDs, duplicate decisions, advisor failure, and explicit
  recheck metadata.
- Offline evaluation precedes live shadow integration. The first evaluation uses
  synthetic/declassified RU and EN fixtures and publishes accuracy, recall@k,
  calibration, option-order stability, latency, and model identity.
- Any later applied reranking requires a separate decision after shadow evidence.

## Stop conditions

Stop before deeper integration if the model is overconfident on wrong candidates,
materially worse in either RU or EN, unstable under option order, unable to
recognize `irrelevant`, or requires access to unauthorized/raw cross-owner data.

