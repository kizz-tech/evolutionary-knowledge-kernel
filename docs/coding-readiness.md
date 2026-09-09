# Assess configured checks for a Git commit

EKK 0.7 provides one manual Belief Runtime workflow:

```sh
ekk assess --cwd /path/to/project --action review-selected-commit --compact
```

The command reads current authorized EKK context, the bound repository's Git
HEAD, and check reports at owner-configured paths. It compares those observations
with the declared prerequisites for the selected commit. It does not run a test,
change a file, approve a method, deploy code or perform the proposed action.
Private operation diagnostics can be written as with other read operations.

## Configure report locations

Use an existing `ekk.workspace/0.1` binding whose root is the Git repository
root and which selects one realm route. Preserve its existing identity, profile
and context IDs. The optional `evidence_checks` list is the shared allowlist of
check IDs and relative readable files:

```yaml
evidence_checks:
  - id: unit
    path: .reports/unit.json
assessment_actions:
  - id: review-selected-commit
    checks: [unit]
    grounds: []
    completeness: complete
    max_age_seconds: 300
```

This does not change the existing current-file hash checks. For `assess`, an
explicitly requested ID selects a check-report parser at that path. Reports and
retrieved records cannot select additional files, sensors or commands. Configure
only appropriate project-owned report files. Keep generated reports out of
committed source where appropriate. Installation does not edit a real binding.

## Choose a named action

The named action defaults to the first freshly observed HEAD inside the assessment
window. Use `--expected-head FULL_COMMIT` to pin a previously selected target.
Each action has a unique ID, a nonempty list of configured checks, exact `grounds`
(same realm/id/revision/digest form as `working_entries`), and an explicit
completeness declaration. `grounds: []` declares no additional reading grounds.
It never declares that the action has permission to execute. At most 32 actions
and 16 grounds per action are supported; commands, paths and privileges are not
allowed in an action definition.

The action projection includes every applicable active accepted `decision` and
`policy`, context-declared basis, workspace working entries and action grounds,
with their exact dependency closure. It excludes optional discovery reading.
Required closure remains all-or-none under the context budget: missing, denied,
conflicting or oversized required material cannot produce readiness. The manifest
explicitly identifies `action_requirements` and whether that projection is complete.
Ordinary `enter` and `context` discovery behavior is unchanged.

Named actions use the complete bound scope set. A caller cannot narrow away an
owner-declared requirement. When actions are configured, a JSON request must name
one and match its checks, completeness and age; it cannot weaken the preset.
`--action`/`--expected-head` cannot be combined with a JSON request.

## Describe an explicit assessment

`assessment.json` has this contract; replace the example commit with the full
lowercase object ID returned by the owning repository's `git rev-parse HEAD`:

```json
{
  "schema": "ekk.coding-assessment/0.1",
  "action_id": "review-selected-commit",
  "expected_head": "0123456789abcdef0123456789abcdef01234567",
  "completeness": "complete",
  "checks": ["unit"],
  "max_age_seconds": 300
}
```

The list must be nonempty, unique and contain at most 32 configured IDs.
`completeness` is explicitly `complete`, `incomplete` or `unknown`; it is a
caller/host declaration about these prerequisites, not a verified statement
that every condition for deployment or another real action has been considered.
The command derives fixed check-specific propositions. It rejects supplied
context, target-version maps, report paths, acquisition modes or executable text.
The default maximum report age is 300 seconds; an explicit age must be finite
and nonnegative.

The ordinary request envelope (`request_id`, `operation`, `payload`) is supported.
Without configured actions, CLI scopes and an optional JSON `scopes` list may
only narrow the bound route. With configured actions, the full bound scope set
is required.
`--root`, `--realm`, `--personal` and `--resume` are unsupported for this command.
An unbound, ambiguous or denied route never falls back to personal storage.

## Supply an observation from the host

A trusted host integration, CI adapter or explicitly operated local runner
produces the configured report. The exact JSON contract is:

```json
{
  "schema": "ekk.configured-check-report/0.1",
  "workspace_id": "workspace:example",
  "check_id": "unit",
  "tested_commit": "0123456789abcdef0123456789abcdef01234567",
  "observed_at": "2026-09-09T12:00:00Z",
  "status": "passed"
}
```

Use the actual bound workspace ID, full tested commit and timezone-bearing report
time. Status is `passed`, `failed` or `unknown`. The producer is responsible for
what was checked, the relationship between its test inputs and the named commit,
and the accuracy of the time. EKK observes the report's declaration; it does not
authenticate the producer or independently establish that tests passed. A digest
pins bytes, not their truth. The derived observation uses mode `inferred` and the
fixed proposition `configured_check:<id>:report_declares_passed`.

Only regular files up to 65,536 bytes are read. Symlink traversal, duplicate JSON
keys, unknown fields, foreign workspace/check IDs, malformed times and non-exact
commit IDs cannot supply evidence. Missing, unreadable or invalid reports remain
unknown. A future or expired time, unknown status or report for another commit
cannot satisfy the prerequisite. A current failed report refutes it. An incomplete or otherwise invalid overall
assessment remains `indeterminate`, with the refuted condition preserved. Suggested
observation requests contain configured check IDs; they contain no command and
do not establish permission, cost approval or a promise that fresh evidence exists.

## Produce a local report explicitly

The source distribution includes a POSIX host helper. From an EKK source checkout
with EKK installed, run an explicitly selected command:

```sh
mkdir -p /path/to/project/.reports
python tools/check_report.py --cwd /path/to/project --check unit -- \
  /absolute/path/to/venv/bin/python -B -m unittest discover -s tests -v
ekk assess --cwd /path/to/project --action review-selected-commit --compact
```

The command runs with the disposable checkout as its working directory. Supply
relative project arguments so it checks that checkout. The helper first replaces
an earlier report with `unknown`, makes a local clone of the selected committed
tree, verifies tracked bytes and executable modes before and after the command,
and checks that the original HEAD and binding did not change. Actual exit zero
produces `passed`; nonzero produces `failed`. Timeout, tracked-input mutation,
uncertain cleanup or setup failure cannot produce a passing report. Reports are
atomically replaced. The existing report parent must be a regular directory; the
report cannot overlap committed source or the binding. Operate one writer per
report path. The helper retains no command output in files or receipts.

This is an explicit host operation. It is never invoked by `ekk assess` and does
not authenticate its producer. The disposable checkout is not an OS sandbox:
the command retains the caller's environment and filesystem permissions. External
dependencies, services, untracked generated inputs and descendants escaping its
process group are outside the exact tracked-input claim. Tracked symlinks and
submodules are unsupported and yield `unknown`. Windows is not validated.

## Interpret the result

| State | Meaning within the declared assessment | Exit code |
| --- | --- | --- |
| `requirements_met` | All declared report prerequisites are supported for the selected current commit | 0 |
| `requirements_not_met` | A usable report states that a required check failed, with otherwise valid assessment inputs | 1 |
| `needs_observation` | A configured report needs to be obtained, refreshed or corrected | 1 |
| `indeterminate` | Context is blocked/incomplete, requirements are incomplete, the target is unverified, or observed inputs changed during the assessment | 1 |

Malformed requests, unbound/ambiguous routes, access denial and required-control
read failures return code 2 with an error on stderr. Computed results use stdout.
`blocked` means this assessment did not meet its declared prerequisites. Code 0
never means that execution is authorized or that an action's result was observed.

`--compact` returns the same assessment semantics with each check's state,
bounded reason codes (for example `missing_file` or `invalid_timestamp`), report
hash and next step. It includes target identity and the context manifest. Omit
`--compact` for the full normalized inputs; the display does not rerun a check or
change the assessment.

The full result preserves normalized projection inputs, report hashes, context
manifest, before/after Git IDs and control/snapshot evidence. `input_digest`
identifies the projection inputs; `assessment_digest` additionally covers the
host observation bundle. Neither is a signature or execution token. The result
remains `historical_projection`, `authority_effect: none`,
`execution: not_performed`, and `outcome: not_observed`.

This first adapter assesses the **committed Git object only**. Uncommitted
working-tree content, external CI provenance and other environments are outside
its claim. Git HEAD is read before and after context/report collection; an
observed change invalidates the assessment even if the final HEAD is the requested
one. Changes observed in the binding or EKK publication also invalidate it.
These observations are not an atomic world snapshot. The host must revalidate
current authority, context and target and use owning-system conditional actions
where needed. A previously saved favorable result cannot authorize a later act.

## Run the whole disposable workflow

```sh
.venv/bin/python examples/coding_readiness.py --ekk .venv/bin/ekk
```

The driver creates a temporary realm, profile and real Git repository, invokes
the installed CLI, and invokes the shipped host helper for four harmless local fixture validations
in disposable checkouts. It also exercises a named action and compact output. It observes
missing evidence, a matching report, a changed selected target, a stale report
for a new commit, a refreshed report, an actual fixture-test failure and its
repair. It then demonstrates an accepted request without an effect, followed by
a separately executed and observed local file effect. Those test runs and effects
belong to the driver, not `ekk assess`. Nine cases are reported; no model,
network service, existing profile or real project is used.

This is an executable mechanism demonstration. The comparative study remains
`designed_not_run`; no improvement in agent reasoning or productivity is inferred.
See [Belief Runtime](belief-runtime.md), [agent entry](agent-entry.md) and
[release validation](release-validation.md).
