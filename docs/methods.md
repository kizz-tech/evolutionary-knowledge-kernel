# Evaluated, transferable, revisable methods

For result retention, explicit challenges, current file evidence and owner recovery, see [daily reliability](daily-reliability.md).

Use `ekk method OPERATION` with the current `--cwd` binding or one explicitly
selected `--profile`/`--realm`/`--scope`. Mutations target exactly one owning realm.
Pass a JSON request through stdin or `--json FILE`. `ekk method --help` lists the
operations. The installed adapter is `builtin:handoff@1`, a read-only draft builder.

| Operation | Request fields | Result |
| --- | --- | --- |
| `propose` | `method_id`, `title`, `spec`, `artifact_base64`, `explanation`, `key`; optional `basis`, `previous` | Inert candidate and exact artifact source |
| `evaluate` | `reference`, `case_id`, `facts`, `key` | Host evaluation receipt and retained exact evidence |
| `admit` | `reference`, `evidence`, `explanation`, `key` | Separately accepted local admission |
| `use` | `reference`, `request`, `facts`, `key` | Current host execution receipt; never automatic source execution |
| `reconsider` | `reference`, `case_id`, `facts`, `key` | Re-evaluation, outcome and review signal |
| `quarantine` | `reference`, `reason` | Immediate host block, canonical history unchanged |
| `retire` | `reference`, `explanation`, `basis`, `key` | Accepted local retirement superseding admission |
| `export` | `reference`, `destination`, `grants` | Exact current method bundle under existing owner export grants |
| `receive` | `bundle`, `expected_digest`, `method_id`, `key` | Captured source and independent inert local candidate |
| `inspect` | `reference` | Exact method contract and local admission projection |

A method reference contains `id`, `revision` and `digest` (`sha256:` plus the full
SHA-256). The owning realm is selected separately by the route. Resume references
also contain `realm`. Evaluation's `evidence` result can be passed unchanged to
`admit`; only its exact source reference is used. Passing `accepted: true` or a
forged receipt does not activate a candidate.

The method `spec` uses `ekk.method/0.1`: fixed adapter/version, artifact digest,
explicit applicability lists for task family/environment/model, privileges,
rollback, reconsideration conditions and limitations. Examples are in
`ekk.adapters.builtin_methods.spec` and `examples/method_transfer.py`. Artifact
bytes are frozen source bytes; records never contain an executable loader URI.
The host adapter owns the verifier and cases (`public-training`, `public-transfer`,
`private-change` for the demonstration).

A replacement uses `propose` with the same `method_id` and the exact current
`previous` reference. Its revision increases and the old bytes remain readable.
The new revision needs new evaluation and acceptance. An old historical reference
cannot be paired with current export bytes; prepare an explicitly reviewed current
release before transferring an older method.

Evaluation, knowledge retention and activation remain separate. A negative case
is evidence for review, not a universal causal conclusion. Host quarantine persists
outside knowledge; restoring a knowledge snapshot does not remove it. Canonical
retirement replaces the accepted local admission and keeps the original source,
evaluation and decision reconstructable. A clean process repeats all activation
gates instead of trusting a persisted “active” flag.

The local execution journal is authoritative only within the trusted host boundary.
Receipt replay checks the exact request, method, evaluator and fixture. Imported
source receipts cannot stand in for a receiver's own evaluation. The receiver's
expected bundle digest must come from an independently authorized transfer;
matching a digest alone does not authenticate a remote organization.

The concrete example builds artifacts and never sends them. Do not infer support
for arbitrary shell commands, network tools, credentials, cross-user isolation,
external exactly-once effects or general model learning from this adapter.
