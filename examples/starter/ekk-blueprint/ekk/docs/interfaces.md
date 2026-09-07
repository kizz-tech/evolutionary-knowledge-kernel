# Interfaces and mechanism boundaries

All the following interfaces are proposed designs. The distribution currently has
only one actual command: `python tools/validate.py <realm>`.

## Common request envelope

`request_id`, `operation`, `workspace_id`, `target_realm`, `target_scope`,
`expected_snapshot` for a change, `payload`, and `idempotency_key` for a repeatable write.

The acting principal and its grants come from the trusted environment or server
transport. A user's CLI may name a profile, but a corporate server does not trust
an input of `principal: admin`. The weaker trust model is stated explicitly for
trusted-local mode.

The common result includes operation status, the snapshot used, data, source
references, incompleteness, warnings, and confirmed/unconfirmed guarantees. Errors
distinguish invalid_format, unresolved_binding, access_denied, stale_snapshot,
unresolved_conflict, unsupported_capability, source_unavailable, and recovery_required.
A denial message does not reveal prohibited content or another owner's metadata.

## Proposals

A proposal contains the expected base snapshot, a list of changes, grounds, and
impact scope. Free text may explain the changes, but the writer accepts patch/files
only within authorized roots. An unavailable source is marked explicitly. The LLM
does not have the final say on rights.

A draft proposal is not a separate task unless the intent to execute it has been
accepted. If the base changes, the writer refuses a silent overwrite and returns a
conflict. Non-overlapping changesets can be combined with revalidation of the new snapshot.

## Packs

A pack manifest contains ID, version, requires_format, entrypoints, a configuration
schema, and a list of explicitly declared executable capabilities. Reading and
installation do not execute code.

The lock contains the version, origin, and SHA-256 of the release artifact actually
installed. The digest is calculated from the distributed artifact; if a directory
is distributed, the packager defines a deterministic manifest of paths and hashes,
not a platform-dependent ZIP. The hash value is not filled in ahead of time and
is not treated as proof of trust in the author.

A project connects a pack by reference. Local configuration stores only deviations
and applicability scope. An upstream update creates an update candidate, not a silent
replacement of accepted methods. A packaging change without a method change is
distinguished from a change in governing behavior.

## Context bundles

The deterministic part resolves the binding, authority, snapshot, and declared
mandatory constraints. The search part ranks the remaining material. The optional
model part is a summary with source references. A summary has no greater authority
than its source records.

The manifest records the request, context IDs, record versions, policy/pack digests,
authorized projection, assembly time, sources, and degree of completeness.
Information about restricted sources is not published through the manifest.

## Connected systems

An adapter describes the owner's available operations: read, propose, execute, observe.
Having a read connector does not imply write permission. An unavailable external
owner is not remedied by creating an internal "official" copy of a calendar, task,
or runtime status.

A multi-repo change retains a receipt with independent step outcomes. A repeated
call continues the unfinished step. The UI does not declare the change fully delivered
until the corresponding external fact has been observed. General cross-realm atomicity
is not promised.

## Moving to a server

Initially, the same application layer works with a server-authenticated principal
and server-side writer. Files/Git may remain the backend. With differing rights,
team members receive only authorized projections, not a full clone. Shared caches
across grants are prohibited by default.

Later, canonical storage can be replaced only through an explicit cutover preserving
IDs, acceptance history, source references, export/import, and conformance. An index
does not become canonical merely because it already has convenient tables.
