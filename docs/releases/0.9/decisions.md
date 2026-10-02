# Design decisions

These are planning decisions for the proposed 0.9 implementation. They do not
grant execution or publication authority. Revise a decision explicitly when new
evidence changes it; do not silently turn an unresolved question into a fact.

| ID | Decision | Reason / rejected alternative | Revisit when |
| --- | --- | --- | --- |
| D01 | One release package owns the connected outcome; reuse independent existing specs through links. | Avoid duplicate product requirements and parallel status trackers. Historical 0.8 documents need no layout migration. | A feature acquires an independent owner/outcome/lifecycle |
| D02 | Target 0.9.0, with no package version bump during planning. | A large coherent capability follows the delivered 0.8 workflow. Version is a release target, not a claim of installation. | Compatibility or release sequencing justifies another target |
| D03 | Capture and recall are equally required. | Saving notes alone does not address the user's experience of agents forgetting incidental findings. | Actual host capability inspection requires a visible scope change |
| D04 | Core behavior works without Laya; first Laya deployment is shadow-only. | The model is an unvalidated advisor for this task. Initial advice must not hide the baseline or silently discard useful findings. | Permitted held-out and ordinary-use evidence supports a specific applied policy |
| D05 | Keep a temporary candidate buffer and ordinary canonical records. | Not every event deserves durable knowledge; a second canonical store would split correction, ownership and recovery. | Measured workload demonstrates an unmet storage requirement |
| D06 | Separate event, interpretation, forecast, applicability and action. | An important hypothesis can be remembered without becoming a fact or a task. Provenance alone does not establish truth. | A concrete representation cannot preserve these distinctions |
| D07 | Preserve source identity and distinguish independent episodes from echoes. | Retries, copied summaries and repeated retrieval can manufacture apparent agreement. | Better causal/grouping evidence refines a specific relation |
| D08 | Recall is conditional, bounded and non-governing. | A universal memory check or full playbook in every task conflicts with proportionate work and increases irrelevant context. | Measured misses justify a specific additional trigger |
| D09 | Corrections affect future projections and dependent summaries while preserving history. | Append-only accumulation without correction perpetuates mistakes; deleting all related records damages independently valid work. | A real consequence exposes a missing dependency/recovery path |
| D10 | Reuse `ekk.record/0.1`, existing writers, queue, work and method lifecycle. Keep a separate additive experience profile from structured observation-gap fields. | Existing mechanisms already own durable identity, governance and recovery; semantic changes need focused compatibility checks. | A demonstrated incompatibility requires an explicit format decision |
| D11 | Evaluate ordinary work and selected real episodes; technical tests remain necessary for mechanism integrity. | No artificial task-solving competition, mandatory diary or universal benefit claim. Real-log selector replay is useful but does not prove productivity. | A separately requested scientific comparison needs a frozen protocol |
| D12 | Train selection behavior on permitted material with grouped splits and separate calibration. | Private project facts in a shared checkpoint are hard to retract and govern; teacher agreement is not ground truth. | A specific owner authorizes another model/data scope with a justified benefit |
| D13 | Defer training method choice until base-model/data evidence exists. | Supervised specialization may suffice; RL lacks a reliable reward here and custom Laya is not automatically compatible with generative LoRA tools. | T09 identifies the bottleneck and eligible training resources |
| D14 | Keep model experimentation, local delivery and public distribution as separate states. | A poor model experiment can be useful; a prepared artifact is not installed, published or evidence of user benefit. | Delivery target is explicitly changed |
| D15 | Preserve an independent observer-module boundary, with external OSS creation conditional. | Reuse outside EKK is plausible, but repository creation alone supplies no capability and must not split ownership prematurely. | A stable API, useful permitted artifacts and a selected repository target exist |

The existing [search-advice decisions](../../plans/laya-advisory/decisions.md)
remain intact. Their `primary/supporting/background/irrelevant` labels are not
the retention-triage rubric. Extending the advisory pattern does not certify
either task's quality.
