# Working through the personal environment

For result retention, explicit challenges, current file evidence and owner recovery, see [daily reliability](daily-reliability.md).

Start with `ekk enter --cwd <project> --task <intent> --compact`.
[Quick entry](quickstart.md) describes the personal home, separate projection, and
exact continuation. [Methods](methods.md) describes verification, application,
transfer, and retirement of an outdated version. Neither entry nor reading creates
a new commitment.

The current low-level workflow for sources and records is preserved below.

## Exact follow-up reads

Keep the successful project route when following a reference:

```sh
ekk fetch --cwd /path/to/project --json /path/to/reference-request.json
ekk read-source --cwd /path/to/project --json /path/to/source-request.json
```

`reference-request.json` contains `{"reference": {"realm": "REALM_ID", "id":
"RECORD_ID", "revision": 1, "digest": "sha256:EXACT_DIGEST"}}`, using the exact
returned values. `source-request.json` adds `"asset_index": 0` for the selected
source asset; subsequent chunks add the returned `next_offset` as `"offset"`.
Assemble the original bytes until `next_offset` is null and check the asset hash.
An optional selector is a separate request field, not part of record identity.

For an explicitly selected owner, use `--profile PROFILE --realm ALIAS --scope
CONTEXT_ID`; repeat `--scope` for each applicable allowed context. Explicit realm
selection does not reuse the workspace's contexts, and context fields inside a
JSON request do not replace those routing flags. Reuse the successful bound
`--cwd` where possible. These commands do not expand permissions.

# Everyday work with EKK 0.7

Describe the task to the agent: "check the grounds for this decision," "retain a
significant result," or "help change the product in light of accepted constraints."
The agent links the request to its owner and project, obtains context, performs
authorized work, and reports what was actually verified and retained. A separate
record is needed for knowledge that is useful on its own; an ordinary edit may
finish without one.

Before acting, the agent reads applicable constraints and grounds. Changing a
decision preserves a new revision or an explicit successor; old acceptance does
not carry over to new bytes. A source is stored separately from its interpretation.
A detected conflict is not resolved by a "latest decision wins" rule.

The technical interface for the agent follows. Replace `CONTEXT_ID`, paths, and
keys with the actual values for the current authorized task; these are not
ready-made user data.

```sh
ekk context --profile personal --realm personal --scope CONTEXT_ID --task 'Check the grounds for a decision' --compact
ekk capture --profile personal --realm personal --scope CONTEXT_ID --file /path/to/source.md --title 'Significant observation' --idempotency-key CAPTURE_REQUEST_ID
```

For `enter` and `context`, `--compact` only shortens historical metadata and the
list of omitted IDs in the display. Complete selected bodies and the
`blocked`/`incomplete` indicators, authority, and digest are preserved. This is a
separate display schema; repeat the command without the flag for the full response.
JSON/stdin requests support only the full response. See [agent entry](agent-entry.md)
for details.

`capture` preserves the exact source bytes and applies the prepared change.
Repeating the same operation uses the same key; different content requires a
different request. A missing response after a failure does not mean that no write
was completed.

To change a record, the agent prepares a JSON request file for `propose`. `base`
comes from the published snapshot that was read, and `changes` contains relative
paths and complete UTF-8 record texts with the 0.1 envelope. Binary bytes use a
`{"base64": "..."}` object; `null` means deletion and requires appropriate authorization.

```json
{
  "base": "PUBLISHED_SNAPSHOT",
  "changes": {
    "records/RECORD_ID.md": "COMPLETE_RECORD_FRONTMATTER_AND_BODY"
  }
}
```

```sh
ekk propose --profile personal --realm personal --json /path/to/change-request.json
```

The agent saves the returned proposal as a separate JSON artifact, checks the
change, and applies that exact proposal. Direct `propose` output contains encoded
bytes; do not replace it with the original text request when passing it to `apply`.

For the common interface, the request can be passed in an envelope:

```json
{
  "request_id": "PROPOSAL_REQUEST_ID",
  "operation": "propose",
  "payload": {
    "base": "PUBLISHED_SNAPSHOT",
    "changes": {"records/RECORD_ID.md": "COMPLETE_RECORD_FRONTMATTER_AND_BODY"},
    "explanation": "Reason for the proposed change"
  }
}
```

The response then has schema `ekk.result/0.1`: `request_id`, `operation`, `status`,
`snapshot`, `data`, `source_references`, `incomplete`, `warnings`, and `guarantees`.
The proposal itself is in `data`; pass that into the `payload` of the common
`apply` request. The proposal fields `grounds`, `impact`, and `explanation`
describe the proposal but do not grant authority or confirm acceptance. An ordinary
request without the common envelope retains the direct response format. Status
`unbound` means there is no authorized binding and is accompanied by `incomplete: true`.

```sh
ekk apply --profile personal --realm personal --json /path/to/proposal.json --idempotency-key APPLY_REQUEST_ID
```

Acceptance of a governing decision additionally requires verified authority and
the corresponding acceptance request. Applying a note does not itself make it a
rule. If the base is stale, the agent rereads the context and rechecks the proposal;
it does not overwrite someone else's change to eliminate a CAS error.

After a significant result, the agent links the observation to its grounds and
expectation, retains actual checks, and states uncertainty separately. `ekk review`
helps find grounds for reconsideration but does not automatically start refactoring.
Failure and a decision to leave things as they are are valid outcomes. New checks
or methods are added only when their benefit is commensurate with their cost;
unnecessary ones can be removed.

Deployment, publication, and execution in external systems use those systems'
standard tools within their own authorization. Local verification does not prove
a production effect. Research protocols remain `not_run`; everyday use does not
replace controlled comparison and complete cost accounting.

## Assess current coding evidence

Use `ekk assess --cwd PROJECT --json REQUEST` for a declared set of configured
check reports tied to an exact Git commit. The command obtains current bound
context and report bytes itself; it does not run checks or grant permission.
Exit 0 means only that the declared report prerequisites are met; exit 1 preserves
failed, missing or indeterminate evidence. See [coding readiness](coding-readiness.md)
for the report contract, safe follow-up and complete disposable example.
