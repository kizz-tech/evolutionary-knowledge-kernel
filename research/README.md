# EKK research

**When does past work make future work better?** The [open agenda](agenda.md)
frames nine questions about sustained external experience, intervention choice,
transfer, consequence repair, evaluation, investigation, collaboration rights,
human capability and method composition.

- [Open questions and falsifiers](agenda.md)
- [Selected related work and reading limits](related-work.md)
- [Roadmap: next tasks and completion gates](../ROADMAP.md)
- [Contribution guidance](../CONTRIBUTING.md)

## Current and proposed studies

| Study | What it compares | Actual state |
| --- | --- | --- |
| [Human/shared/method transfer](studies/human-shared-method-transfer/README.md) | A strong ordinary baseline, personal-only, shared-only and combined environments | Existing protocol and contract validator; `designed_not_run`, freeze unset |
| [Method applicability](studies/method-applicability/README.md) | Ordinary work, a frozen retrieved method, a proposed SkillAxe reproduction and an EKK applicability candidate | Proposed first comparison; no executable protocol, reproduction, dataset or run yet |
| [Action readiness under partial observation](studies/action-readiness/README.md) | Strong evidence/preconditions, explicit belief semantics, and a temporary machine-maintained projection | Direction selected; bounded projection and deterministic example implemented; comparative study `designed_not_run` |

The second comparison requires its own protocol and validator. The existing four
environment arms do not implement those algorithmic alternatives. The
method-transfer example in `examples/method_transfer.py` tests deterministic
mechanisms and makes no model calls; it does not establish productivity or human
understanding. The action-readiness comparison has its own arms and evidence
boundary; selecting it does not mark either earlier study complete or superseded.

## Evidence and history

Keep exact task, evaluator and protocol versions, whole-lifecycle costs, failures
and negative transfer. Distinguish framing, measurement readiness, empirical
findings and practical benefit. Human understanding is separate from agent
execution. Purpose and authority remain with the participant and owning systems.

Earlier protocols under `studies/001-environment-learning`,
`studies/sequence-learning`, `protocol-v0.1.md` and `metrics-v0.3.md` are historical
designs retained to reconstruct the change in direction. They do not supersede
the existing human/shared/method-transfer protocol or become completed evidence
through this agenda. `replay.py` invokes preserved historical semantics in a
separate process; it never selects a retired writer for current work.

The English agenda is an editorial adaptation of owner-supplied drafts and later
working synthesis, with independently stated proposals and evidence limits.
[Edition provenance](agenda-provenance.json) identifies exact inputs and outputs;
private originals remain with their owner and are not distributed here.
