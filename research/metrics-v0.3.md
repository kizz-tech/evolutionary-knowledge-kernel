# H1–H4: measurement instrumentation v0.3

Status: local measurement contracts and a deterministic rehearsal are implemented. This supplements [protocol v0.1](protocol-v0.1.md); it is not a scientific result. The code is in `ekk.experiments`; the capability mechanism is in `ekk.capabilities`.

## How to use it

`RunRecord` describes an individual task within a preassigned independent trajectory. `Costs` requires every cost component; an unknown value must not be replaced with zero. Zero rehearsal prices mean there are no model calls; zero times are scripted values, not a measured benchmark.

Create an `ExperimentLedger()`, add validated `RunRecord` objects through `add`, obtain `summary()`, and write a new artifact through `write(path)`. `RunRecord.from_mapping` accepts a JSON-compatible representation; `ExperimentLedger.read` validates the records again and recalculates the derived summary. An existing file is not overwritten. Measurements use machine-readable JSON; narrative research documents remain Markdown.

Required fields include the protocol version, hypothesis, task family/task ID, trajectory/condition/split, replica/seed, exact model ID/revision, harness/kernel/compiler/evaluator versions, isolated environment IDs, authorized snapshots/policy versions, and knowledge/tool fingerprints. For an undetermined backend revision, record an explicit `unavailable:...` and disclose the limitation; alias stability is not assumed.

Cost includes human minutes, tokens, actual model price, tool/compute costs, wall seconds, and time spent creating and maintaining the environment. Do not add minutes to money. Do not record the full environment setup cost again for every task: assign it once to the setup task or use a prespecified allocation. The summary sums the reported components; it does not convert currencies.

Success requires independent verification. Failure, stopped, omitted, and no-change outcomes require a reason and remain in the data. Unsuccessful/stopped assignments are not removed to produce a positive summary. The calling harness must enter every assigned trajectory: the ledger cannot detect an assignment hidden from it.

## Metrics and comparisons

| Question | Recording and interpretation |
| --- | --- |
| H1: environment evolution versus memory | B/D and the additional A/C arms are specified by condition; an H1 group keeps the same model/revision/protocol/harness/evaluator. A model change requires a separate experiment ID. Quality is compared against full cost, not just late-stage speed |
| H2: text versus executable knowledge | The same initial knowledge and permitted snapshots are fixed before the run. The capability digest is separate from knowledge digests. Differences in errors and full cost are evaluated on comparable tasks; the ledger does not itself establish that knowledge sets are equivalent |
| H3: federation | Required/covered authorized context, false inclusions, context bytes, compile seconds, denied disclosures, and authority confusion. Isolation, federation, and an authorized oracle are distinct prespecified conditions. A prohibited source is not part of the required context |
| H4: scaffold removal | `ScaffoldItem` / `scaffold_inventory` retain the reason for introduction, model dependency, maintenance, evidence, candidate, and a separate holdout. There is no arbitrary composite debt score. Verified removal in the inventory is a verification claim, not permission to disable a mechanism |

Learning Yield = validated reuses / reuse opportunities. The unit is a significant observation identified in advance with an opportunity for application: do not count the same observation multiple times across task rows. Amnesia Rate = repeated recognized errors / opportunities to prevent them after evidence became available. Each error is assigned one primary cause: capture, interpretation, retrieval, authorization, compilation, activation, obsolete_policy. Knowledge that is legitimately inaccessible is excluded from the denominator; authorization means a defect in intended access, not a requirement to bypass a prohibition. When the denominator is zero, the ratio contains `value: null` (N/A); the numerator and denominator are retained.

The summary shows the number of independent trajectories separately from the number of tasks. These are descriptive aggregates, not confidence intervals or causal inference. The non-inferiority threshold, sample size, budget, primary metric, and stopping rules are fixed before the main run. The deterministic `deterministic_rehearsal()` checks the success/failure/no-change recording branches without model calls; every value is marked `rehearsal: true`, and scientific confirmation is never inferred automatically.

## Isolation boundary

The ledger rejects duplicate task IDs within a trajectory, condition/split/model changes within a trajectory, a shared agent environment between independent trajectories, and overlap between agent and evaluator environments. Recorded snapshots are declarations: the launching environment enforces actual restrictions on the filesystem, global EKK config, caches, and evaluator write access. A distinct directory name does not by itself prove isolation. A holdout must not be reused repeatedly for tuning; an exposed set becomes pilot data, and verification requires a new independent set.

## Capability admission and reuse

The manifest binds the owner/code URI, version/digest, qualified basis refs, generator version, environment, privileges, verifier, rollback, and reconsideration. The descriptor is inert: no Python import, installation, or execution from the URI occurs.

The trusted host supplies `CapabilityRuntime` with callbacks `admit(operation, manifest)`, `basis_is_current(ref)`, `verifier(bytes, manifest)`, and `runner(bytes, fixture)`. These functions are not extracted from a document. Activate checks authority, digest, and grounds, then invokes an independent verifier; after verification, authority and grounds are checked again. The runner receives the same immutable bytes. The next run checks authority and grounds again. After the source file changes, the activated version uses the bytes already verified; new code requires a new version and admission.

`BOUNDARY_CHECK`, `verify_boundary_check`, and `run_boundary_check` are a small, safe instance: they check source disclosure, target acceptance, and digest matching across different synthetic fixtures. This is a fixed function, not execution of arbitrary artifact code. The general runtime trusts host callbacks and does not promise a sandbox for malicious Python.

Changed/unavailable grounds block further use and create a specific reconsideration candidate, but do not delete history. `retire` requires current authority and a reason. A safety control additionally requires a separate host-owned `retirement_verifier`: a Boolean from a user document is insufficient. Restoring it means reactivating the same verified bytes with current permissions. Runtime history is available to the caller for persistence; the registry is process-local, so restarting requires new admission. This prevents accidental restoration of authority from an old receipt.
