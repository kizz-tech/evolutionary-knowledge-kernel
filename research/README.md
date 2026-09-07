# EKK research

The active question is whether personal environments and shared work can retain,
transfer and revise useful methods across participant, model and condition changes.

[Human/shared/method transfer](studies/human-shared-method-transfer/README.md)
is the current four-arm protocol and runnable validation harness. Its model-study
status is `designed_not_run`; its freeze is unset. The method-transfer example
in `examples/method_transfer.py` tests deterministic mechanisms, not productivity.

Earlier protocols under `studies/001-environment-learning`, `studies/sequence-learning`,
`protocol-v0.1.md` and `metrics-v0.3.md` are historical research designs retained to
reconstruct the change in direction. Their wording does not supersede the active
protocol, and their designed studies must not be reported as completed.
`replay.py` invokes preserved historical semantics in a separate process; it never
selects a retired writer for current work.

Keep exact task/evaluator/protocol versions, whole-lifecycle costs, failures and
negative transfer. Personal understanding is separate from agent execution. The
user's purpose and authority remain external to the optimizer.
