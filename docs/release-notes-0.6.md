# Runtime 0.6

This version completes the daily reliability increment while retaining record
format 0.1 and the personal/shared/method direction.

- `retain` publishes a discoverable result with exact source artifacts, verifies
  published bytes and preserves the receipt when subsequent verification fails.
- Additive capture/retention can recover from an unpublished stale base without
  changing IDs, source bytes or the retry key. Ordinary edits and acceptance keep
  explicit snapshot semantics.
- Private diagnostics distinguish registered caller environments, logical keys,
  attempts, errors, pending operations, confirmed publications and replays. They
  exclude knowledge content and expose incomplete coverage.
- Owner-only backup/restore preserves exact history and operation evidence in an
  independent isolated copy. Restoring knowledge does not restore execution permission.
- Large Git batches avoid a confirmed duplex pipe stall. Registered restore also
  verifies installed pinned packs and preserves private retry-journal permissions.
- Context exposes explicit challenges, changed pinned grounds, source-aware lexical
  matches and bounded optional current-repository checks. Human and AI attribution
  has the same epistemic status; authority still follows current grants.
- Incoming accepted holds block the installed method client until authorized
  resolution. Requested-scope dependency filtering also applies to context metadata.

See [daily reliability](daily-reliability.md) for commands, bounds, error behavior
and upgrade/recovery conditions. The empirical study remains `designed_not_run`;
this release's compatibility and mechanism tests do not establish productivity,
human understanding or general model improvement.
