# Reliable retention and current work context

Runtime 0.6 adds durable results, private operation diagnostics, additive retention
retries, independent backup/restore, and explicit challenges to recorded grounds.
It preserves the `ekk.record/0.1` format, IDs, source bytes, existing acceptance
receipts and separate owners. Installation does not publish a source release or
activate a new company connection.

Existing descriptive `observation` metadata, such as a date and confidence label,
remains readable without rewriting its bytes. Either a `subject` or `aspects`
field opts into the structured observation contract: a resolvable subject, an
RFC3339 timestamp and nonempty unique aspects are then all required. Descriptive
annotations cannot satisfy an `observation_gap` review trigger. This preserves
old records without inventing measured evidence or weakening structured checks.

## Finish a useful result

Use `retain` to publish a derivative result and up to 32 exact source artifacts in
one operation. The result is an ordinary unaccepted `outcome` with exact source
basis references. Its body is a recorded assertion, not a verified account of the
world. A result without new artifacts is also valid.

Include retention in the final completion check for substantial work. The parent
integrator retains useful delegated findings with the result and checks the actual
receipt before claiming it was saved. Report unresolved retention explicitly;
ordinary work with no new material requires no additional record.

```sh
ekk retain --cwd /path/to/project --title 'Integration result' \
  --file evidence.txt --result-file result.md --idempotency-key integration-2026-09-08
```

By default `retain` freezes the request in the durable local queue, starts the
background publisher and returns at once with `ekk.retention-queued/0.1`, its
logical `key` and `state: local_pending`. That result confirms durability on this
host only. Report the result as pending until `ekk queue status --cwd PROJECT --key
KEY` shows `read_back_and_discoverable`. Without a supplied key, identical content
yields the same key, so a retry cannot create a second result. Add `--wait` to
publish and verify before returning; the receipt described below is then returned
directly.

For several artifacts, use a JSON request with `title`, `body`,
`idempotency_key`, and `artifacts`. Each artifact has a basename `filename`,
optional `title`, and exactly one UTF-8 `body` or `base64`. The private MCP adapter
exposes the same operation as `ekk_retain` within its configured space and scopes.

```json
{
  "title": "Integration result",
  "body": "The named compatibility checks passed. User benefit remains unmeasured.",
  "idempotency_key": "integration-2026-09-08",
  "artifacts": [
    {"filename": "checks.txt", "title": "Observed checks", "body": "Exact supplied output\r\n"}
  ]
}
```

`capture` retains one source. Both operations queue by default; with `--wait`, or
through `queue status` once published, they return the original publication
receipt and exact `source_references`; `retain` also returns `result_reference`.
They read published record and asset bytes back under current access, compare them
with the exact request, and check discovery through the ordinary scoped search.
The returned discovery query is the record ID. This proves addressability, not
semantic retrieval quality, truth, acceptance or observed usefulness.

`retention.state` distinguishes `read_back_and_discoverable`, `read_back`, and
`published_verification_pending`. A pending verification still includes the
confirmed publication receipt, an incomplete flag and a safe explanation.
The private capture request records its last confirmed stage; that stage is not
proof that no later publication occurred. Metadata failure preserves the owning
receipt and warns instead of repeating the write.

Use the identical request and key after a timeout, interrupted client or uncertain
response. A successful replay returns the same publication. A changed request
with that key is rejected. The adapter supports old capture-request journals.

Cooperating writer and same-request locks wait at most 30 seconds per lock
acquisition. Contention returns `lock_busy`, `retryable: true`, `lock_kind` and
`waited_ms`; it does not rebase a proposal or prove an earlier attempt unpublished.
Retry the identical frozen request and key. Keep that request separate from a
working report that may acquire later annotations. The limit covers lock waiting,
not total command duration or work already running inside the lock. Never unlink
a busy lock file: it may still protect a live writer. Private diagnostic locks
wait at most 250 ms; unavailable diagnostics produce a warning while domain work
continues under its normal publication and verification contract.

Only an unpublished additive capture/retain proposal may advance to a new base.
It first asks the owning store to recover and find the original exact operation.
If absent, every proposed path must be new in both snapshots and realm,
governance and pack controls must be unchanged. IDs, bytes and key stay fixed;
there are at most three attempts per invocation. Dirty projections, recovery
conflicts and key conflicts are not rebased. A supplied `expected_snapshot`,
ordinary edits and acceptance retain their explicit snapshot requirement.
After current authorization and exact publication lookup, a known stale base
is rejected before scanning all historical IDs or attempting a new store write.
Exact replay and idempotency-key conflicts still take precedence; the final store
compare-and-swap continues to protect against later concurrent publication.

Git input uses a private temporary file while output remains captured. This
avoids a duplex pipe stall observed when large snapshot batches sent many object
IDs while Git returned large binary blobs. Exact framing and bytes are preserved;
there is no fallback writer or automatic retry of an uncertain mutation.

Explicit recovery (`ekk recover`), restore activation and a store without a
verification checkpoint validate every recorded operation and read each unique
historical blob once, comparing tree identities and request SHA-256 digests.
Deleted baseline blobs remain checked. The digest memo is discarded after the
call; current file projection and pending-operation checks still run.

A write audits only what was not audited before. A private checkpoint in the
runtime directory lists the operations a previous pass audited, with their
evidence commit and completed journal digest, and the time of the last successful
full audit. The checkpoint lets a write skip one thing: reading the trees and
blobs of those operations again. On every write each runtime journal is still
compared with its operation evidence in Git, read in one batch, and each
operation must still be in published history, so no file in the runtime directory
can vouch for another. Any operation that is new, pending or changed is verified
in full. The checkpoint is ignored when the verifying code changes. The number of
Git processes a write starts does not grow with the number of earlier operations.

Corruption of an old object is therefore found by the full audit, not by the
next write. The full audit has three owners:

- the background publisher (`ekk queue drain --background`, started by every
  queued `retain`, `capture` and work operation) runs it before publishing when
  the store has no checkpoint or the last full audit is older than seven days;
- `ekk recover`, which you should also run after a crash, a restore or a
  suspected disk problem;
- restore activation, and `tools/local_install.py warm` after a new release is
  activated.

When a full audit refuses operation evidence, the checkpoint is removed. Every
write then audits everything and refuses, as before the checkpoint existed, until
the cause is resolved and `ekk recover` passes. A background publisher runs the
due audit under the queue's worker lock, so a second worker started meanwhile
leaves quietly. When the audit fails the publisher publishes nothing, marks every
waiting request `needs_attention` with the audit error (so `ekk queue status
--key KEY`, the check an agent is given, shows it), and writes one JSON line with
`"store_audit": "failed"` to the queue's `worker.log`; after `ekk recover` passes,
`ekk queue retry --key KEY` republishes. The audit records itself as soon as the
operation evidence passed: an external working-tree edit or a projection it
blocks is not an evidence failure, is reported per request as before, and leaves
the checkpoint in place.

A replay reports the recorded publication. `lookup`, and `apply` or a retried
`retain`/`capture` with a key that is already published, return the original
receipt after checking the operation evidence and its presence in published
history. They do not read the working tree. The working-tree projection is
checked by every new write, against its base, and by explicit recovery, which
refuses an external edit.

After activating a release, `tools/local_install.py warm` runs the full audit and
builds the record version index for every store named in the owner's profiles,
with the active release, and prints one line per store with both durations. A
release that changes the store adapters makes every checkpoint foreign, and one
that changes the historical loader makes the version index cold; without the
warm-up the first write and the first historical reference pay for that. The
index depends only on the loader itself, the envelope and method rules, the
codec, the schemas and the YAML and JSON Schema libraries, so other changes to
the application keep it warm.

Known limitation of contained realms. A contained realm shares the history of
its outer repository, and the check that a new record ID was never used before
loads every outer commit as a realm. If any outer commit does not hold a loadable
realm under the prefix, for example because the realm was added to an existing
project after its first commit, every write that adds a record ID fails with
`KeyError: '.ekk/realm.yaml'`; nothing is published or changed. Reading the
current realm still works. Place a contained realm in the first commit of its
repository, or use a standalone store, until the realm's historical horizon is
defined. The behaviour is pinned by
`tests/test_contained_store.py::ContainedRealmHistoryHorizonTests`.
The disposable YAML parse cache holds at most 8,192 entries and 64 MiB of retained
graph storage per codec, so a migrated working set can retain both current and
historical alias modes. Exact-byte checks, defensive copies, schema validation
and envelope validation are unchanged; cache entries never establish authority.

## Fallible assertions and explicit holds

Source material, its interpretation, acceptance and execution authority have
different meanings. Humans, models and evaluators can each be mistaken.
`created_by` is record attribution. It does not authenticate the original speaker
or establish truth, trust, understanding or permission.

Preserve the original source and express a correction as a new or revised claim
with exact grounds. An existing `contradicts` relation can name the exact disputed
record revision and digest. Context and `work_view` surface these explicit
challenges even when their vocabulary differs from the task. Disagreement is
advisory; no winner, revocation or execution permission is inferred.

An authorized owner can accept a mandatory decision that holds the affected scope
for review and explicitly conflicts with the relevant current decision. Current
accepted conflicts block context. The installed method client checks conflicts in
its selected work scopes, including incoming holds, before execution and before
releasing a result. An ordinary claim cannot install that hold. An authorized
resolution supersedes the hold or the original decision while preserving history.
Other clients must honor `blocked` for dependent work; EKK does not stop arbitrary
external processes.

## Resume with exact grounds and bounded coverage

Entry includes accepted commitments, results, questions, exact continuation
references, explicit challenges and changed named grounds. Historical pins keep
their bytes. A different readable current head is an additional advisory record,
subject to the ordinary record budget. Hidden dependencies suppress the entire
referencing record; a governing dependency that cannot be disclosed produces a
generic blocked/incomplete result.

The context record budget counts canonical record bytes, not the complete JSON
transport envelope. Mandatory closures remain all-or-blocked. Source-aware
ranking scans supported owned UTF-8 assets, up to 1 MiB each and 8 MiB total in
deterministic record order. Truncation and non-text assets make coverage incomplete.
Insights have a separate 32-row and 8 KiB compact-JSON bound. The MCP adapter also
enforces its configured total response limit. Inspect `manifest`, `insights` and
query coverage; use `search`, `fetch` and `read-source` for further exact reading.

Assembly time describes a knowledge projection. It does not establish freshness
of code, a website, a service or the external world.

## Check named current repository files

A workspace owner can add a small allowlist to the existing portable binding:

```yaml
evidence_checks:
  - id: service-contract
    path: src/service.py
```

A result can record the associated byte claim. `retain` accepts this optional
`repository_evidence` object, and ordinary records can carry the same declaration:

```yaml
repository_evidence:
  workspace_id: workspace:example
  files:
    - check: service-contract
      sha256: REPLACE_WITH_THE_EXACT_64_HEX_DIGEST
```

Entry reads only check IDs configured for the currently bound workspace. A record
cannot supply a new root, path, command or URL. The adapter checks regular files,
rejects symlinks/traversal, limits each file to 16 MiB, and bounds the projection to
32 checks and 8 KiB. Results name the checked file, expected/observed hash and check
time with `matches`, `changed` or `unavailable`. Missing declarations and unavailable
checks remain unknown. A matching file hash is not a semantic test of the assertion.

## Private operation diagnostics

Operation names are bounded ASCII labels when reading a journal; a reader can
preserve names introduced by a newer runtime. Each writer still emits only its
registered operations. Unknown schemas, malformed fields and integrity failures
remain errors. An unpatched 0.6 reader rejects later `assess` entries and cannot
append diagnostics; use a compatible maintenance build instead of deleting those
entries. This compatibility rule grants no knowledge or execution semantics.

CLI, retention and method adapters, and the private gateway instrument their
application attempts. Direct application calls that bypass these adapters are
outside this coverage. These are local diagnostic observations, not a count of
all user tasks or an independent audit against the OS owner.

```sh
ekk diagnostics --since 2026-09-08T00:00:00Z --until 2026-09-09T00:00:00Z
```

Reports group attempts by operation, registered caller, runtime version, result
and normalized error code. They distinguish logical keys, attempts, internal retry
children, replays, confirmed mutation attempts, pending attempts, and completions
after the selected half-open window. Logical outcomes describe observed attempts;
an unfinished member stays explicitly pending. They do not certify a task outcome.
Publication metadata comes from the owning store, including a confirmed publication
followed by a response failure. Stages are recorded only at known adapter boundaries;
otherwise the stage is `unknown`.
Recovering another pending key creates a separate `recover` observation for the
current recovering caller. Its publication is never attributed to the new request.
Recovery of the same key keeps the original logical operation. A recovery attempt
records what this invocation confirmed; it does not rewrite an earlier unknown result.

The journal stores bounded symbols, times and hashed identities/snapshots. It does
not store queries, task text, source bodies, titles, source paths, raw keys,
credentials or exception messages. Default retention is 30 days, at most 10,000
attempts and 16 MiB including atomic replacement space. Pending attempts are not
silently expired. Pruning, missing initial coverage, capacity refusal and corruption
remain explicit. Interrupted diagnostic bytes are preserved; they are not repaired
by inventing results. Logging failure must not discard a domain receipt or retry
domain work. CLI warnings produced after stdout completion appear separately on
stderr; programmatic callers receive warnings with the result.

Caller identity is optional host configuration in private `config/callers.yaml`:

```yaml
schema: ekk.callers/0.1
codex_profile_fleet: /absolute/path/to/owner-profile-registry.yaml
adapters: [private-gateway]
environments:
  claude-code: {CLAUDECODE: "1"}
```

The Codex adapter matches the process's exact `CODEX_HOME` against enrolled homes
in the owner's `lifeos.codex-profile-fleet/1` registry. Another coding agent is
registered under `environments` by the variables its host sets for every command
it runs; Claude Code sets `CLAUDECODE=1`. Markers apply only outside Codex (no
`CODEX_HOME`), and a process that matches several of them stays `unknown`. A
gateway may select only an explicitly registered adapter ID from its private
configuration. Missing or unrecognized callers stay `unknown`; request fields and
EKK role names cannot supply a caller label. Environment attribution is not
authentication or an OS sandbox. No host credentials, transcripts, profile state
or permissions are copied.

## Independent owner backup and isolated recovery

```sh
ekk backup --profile owner-role --realm owned-realm --destination /private/backups/new.tar
ekk restore --profile owner-role --realm owned-realm --file /private/backups/new.tar \
  --destination /private/drill/realm-copy --restore-data-home /private/drill/runtime-copy \
  --sha256 EXACT_ARCHIVE_DIGEST
```

Backup requires an explicit registered profile and realm, the current manifest and
bootstrap owner, and wildcard read/write grants. Recovery validates pinned packs
against the installed reviewed runtime; a missing or different pack blocks it.
Preserve the exact runtime artifacts with the archive. Workspace/root/scope overrides
cannot turn a bounded route into a full backup. Both destination parents must
already exist; archive, restored repository and restored data home must be new and
separate from the original stores and runtimes. Restore keeps the registered realm
identity and current owner policy when available; an offline original uses its
registered identity and verifies the archived owner policy before final copy creation.

The private archive preserves the selected publication, Git history, exact operation
refs and existing capture/retain requests that match published immutable evidence
for this realm and principal. Unmatched or unpublished legacy requests are explicitly
outside its coverage. Git configuration, hooks, credentials, unrelated runtime
directories and diagnostic logs are excluded. Every payload has a size and SHA-256
manifest; independent Git objects and isolated activation are checked before success.

Contained realms share their parent repository's commits. Exact backup therefore
requires separate authority over that repository and the explicit
`--include-repository-history` flag. The archive declares that wider scope; it does
not pretend to be a realm-only export. A default contained backup is refused.

Restore creates a new private copy and runtime, preserving historical IDs, bytes,
receipts and matching retry requests. It does not register the copy, retire the
original writer or perform a production cutover. Host execution receipts and
quarantine are not reconstructed: knowledge admission alone cannot authorize a
restored method. Archive corruption, incomplete publication, unexpected paths,
symlinks/gitlinks or destination reuse are rejected. A failed restoration can leave
a private partial destination and never reports it as a validated copy.

Backup and restore are bounded trusted-local adapters, not an encrypted remote
backup service. Current limits include a 1 GiB archive and 512 MiB expanded Git
object data. Keep archives private and test the exact operational scenario before
choosing a replacement writer.
