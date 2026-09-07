# Human/shared/method transfer study

This is the active research design for the final direction. It tests personal
continuity, shared-work continuity and transferable, revisable methods together.
Older study protocols remain historical designs, not completed evidence.
`protocol.yaml` is JSON-compatible YAML 1.2, deliberately readable with stdlib.

**Empirical status: designed_not_run.** No real model, participant cohort,
task sequence, budget or evaluator has been selected. `freeze: null` makes the
harness refuse to compare runs. Synthetic tests only verify this contract.

## Execution contract

1. Prepare a separate frozen copy of the protocol. Supply every field described
   by `freeze_contract`; `test_harness.fixture()` demonstrates the complete
   machine-readable shape with explicitly synthetic values. Do not use that
   fixture as actual evidence or invent participant/model identities.
2. Freeze matched nonidentical tasks in one family: acquisition, transfer to
   participant B with the same model, model replacement for B, then adverse
   conditions with the replacement model. Each later task is related to the
   acquisition task, with an independent task/input/answer digest. Freeze the
   adverse condition and unlearning bounds inside the criteria/failure artifacts.
3. Freeze evaluator bytes, criteria, observation window, baseline workflow,
   tools, kernel/harness versions, replica count and rationale, source owners,
   provenance, allowed participants, currency and identical lifecycle caps.
   Preserve the exact protocol bytes and SHA-256 outside candidate write access.
   This command cannot supply actual filesystem isolation: the run host must.
4. Execute independent environments for every arm/replica. Inventory every
   accessed artifact, including personal/shared context and transfers. Log
   origin arm/replica, channel, digest, owner, provenance and allowed participants.
   Holdout answers stay with the evaluator. Canonical task-source inputs are
   common to all arms; permitted learned context is separately inventoried.
5. Export a JSON array with one record per arm/replica/phase. Preserve failures,
   stops and omissions, with reasons and independent evaluation receipts.
   Report every lifecycle stage in all four units, using explicit zeroes where
   applicable. Allocate setup/maintenance/failure costs once to the phase that
   incurred them; do not silently exclude or double-count them. Caps apply to
   the sum of the entire trajectory. Aggregate money only in frozen currency;
   minutes, tokens and money remain separate, not a fabricated composite score.
6. Keep the human-understanding rubric score separate (`null` means unmeasured).
   Measure reconstruction of grounds, ability to challenge a claim and knowledge
   of applicability limits independently of agent/product acceptance.
7. Validate the observations:

   ```sh
   python3 harness.py frozen-protocol.yaml observations.json --frozen-sha256 <externally-pinned-sha256>
   ```

The output compares arm/phase acceptance counts, harm, method rejection/revision,
human rubric observations and lifecycle cost totals. It always sets
`empirical_benefit_established: false`. Observed mode means declarations passed
validation; it does not authenticate model calls, evaluator receipts, hidden
answer isolation or causal benefit. An independently audited analysis using the
frozen criteria and trajectory-level uncertainty is required before a benefit
claim. Failed or harmful transfer is a result, not a reason to tune the evaluator.

Run the contract tests from this directory:

```sh
python3 -m unittest -v test_harness.py
```

The synthetic fixture is built in memory. Tests cover missing arms, duplicate
observations, participant/model/heldout/evaluator/version/source/budget drift,
answer and personal-archive leakage, cross-arm environments and artifacts,
omitted maintenance/failure costs, mixed rehearsal/observed data, and changed
frozen protocol bytes. No dataset or model result is supplied by these tests.
