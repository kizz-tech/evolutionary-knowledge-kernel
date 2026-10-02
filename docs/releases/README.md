# Release packages

A release is a working specification for one connected product outcome. Keep its
requirements, design, implementation slices, decisions and delivery evidence
together, using the same lightweight discipline as feature specifications.

| Release | Product outcome | Authoritative package |
| --- | --- | --- |
| 1.0, planned target | Past work measurably improves the next work, in every host, proven in real use | [Specification](1.0/spec.md), [status](1.0/status.md), [tasks](1.0/tasks.md), [decisions](1.0/decisions.md) |
| 0.9, delivered as runtime 0.9.0 inside the 1.0 package (D-1.0-06) | Observations acquired during work and recalled for later decisions | [Specification](0.9/spec.md), [status](0.9/status.md); delivery evidence in [1.0 status](1.0/status.md) |
| 0.8, historical layout | Continuous work, proportionate context and recoverable operations | [Specification](../plans/v0.8/spec.md), [implementation and delivery](../plans/v0.8/implementation.md) |

The table is navigation, not a second status tracker. Earlier releases keep their
existing documents and evidence; do not relocate or rewrite historical packages
merely to make them match this layout.

## One home for each fact

New release packages live at `docs/releases/<target-version>/`:

| File | Owns |
| --- | --- |
| `spec.md` | Problem, connected outcome, scope, acceptance criteria and explicit exclusions |
| `design.md` | Interfaces, data flow, invariants, failure/recovery behavior and unresolved technical choices; omit for a trivial release |
| `services.md` | Repositories/components, responsibility boundaries and integration order |
| `tasks.md` | Dependency-ordered implementation slices, task states and completion evidence |
| `status.md` | Current release phase, delivery states, next actionable slice, unresolved decisions and handoff |
| `decisions.md` | Consequential choices, alternatives and reasons; omit when no such choice exists |
| `sources.md` | Relevant prior specifications, research and reading limits; omit when inline references suffice |

Add evidence files only when evidence exists. Operational paths, logs, credentials,
private material and installation receipts stay with their private owner; public
documents contain an appropriate technical summary. A directory is not a reason
to create an empty report.

The release owns its end-to-end acceptance. An existing feature spec owns its
local contract and task state. Link it and record the exact integration boundary;
do not copy its backlog or silently expand its authority. Split a feature into
another spec when it has an independent outcome, owner or lifecycle, not for every
module. A single coherent release can be one spec package.

## Progress and changes

Use `planned -> implementing -> validating -> delivered` for the main phase.
`blocked`, `paused`, `cancelled` and `superseded` require a stated reason. A phase
does not grant permission to implement, install, train, publish or act externally.
Carry forward authority from the user's actual request; do not invent an approval
ceremony for routine implementation decisions.

Track these facts independently in `status.md`:

- implementation and technical verification;
- local installation and supported integration surfaces;
- public preparation and publication;
- practical benefit and unresolved limitations.

`delivered` means the delivery target in the spec is fulfilled. A locally installed
release can be delivered while public publication is not requested. An uploaded
archive is not evidence of a working installed release. Passing mechanism tests
does not establish improved agent behavior.

Update task state when a slice changes, decisions when a consequential choice
changes, and release status at a handoff or delivery transition. There is no
required entry after each tool call, no daily diary and no second EKK record for
each Markdown edit. Reuse unchanged evidence. If inputs change, identify exactly
which checks need refreshing.

At scope change, record what moved and why, update affected acceptance/tasks, and
preserve the previous interpretation in history. A missing required capability
cannot disappear through a status edit. An optional experiment can finish with a
negative result when its own declared completion criteria are satisfied.

At delivery, identify exact component versions, frozen artifact hashes, completed
acceptance, remaining limitations and the rollback route. Keep follow-up
improvements separate from the historical delivery statement. The existing
[English export and release procedure](../releasing.md) still governs packaging;
these documents do not change its schema or the source allowlist automatically.

For the next release, read `status.md`, then the relevant task and requirement.
Read the full design only when its boundaries affect the change.
