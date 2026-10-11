# Release 0.10.1: nothing lost, nothing misattributed

A runtime increment on 0.10.0 and the first step toward 0.11. See the
[scope](releases/0.10.1/spec.md), the [implementation decisions](releases/0.10.1/implementation.md)
and the [status](releases/0.10.1/status.md).

## What changed

- **Nothing the owner has not judged is deleted silently.**
  - Held and composed results become `expired_unreviewed` tombstones at 60 days.
  - Pending corrections become tombstones at 90 days.
  - Text-free rows stay for 365 days after their last activity.
  - Every transition and deletion is counted.
  - `observe status` shows the next expiry of unjudged material and any episode
    deleted without a count. The review page lists held results and corrections
    oldest first, says how many wait, and says when the oldest expires.
- **Declared provenance.**
  - `observe apply-review` requires `--relayed --words FILE` (an agent relayed
    the owner's reply) or `--owner-marked-page` (the owner edited the page).
  - `decide` requires `--stated-by agent|owner-relayed`. `owner-relayed` keeps
    the owner's words as an exact source (`--owner-words FILE`).
  - The host and session are recorded beside the declaration, and a relayed
    statement is never copied onto a record the owner did not name.
- **`accept --id ID --words FILE`.** It builds the host-chat statement from the
  host's session and the runtime clock. A chain is accepted by naming each
  unaccepted member. Each refusal is named.
- **One host identity** for the hook, the CLI and the journal. Claude Code
  sessions are read from `CLAUDE_CODE_SESSION_ID`. Every observer row carries
  the runtime that wrote it. The observer database has a schema version and a
  read-only accessor.
- **Full IDs** on the session card and the review page. An unknown ID that is
  the start of exactly one readable record gets an error naming the full ID and
  the command to rerun. Request errors return `invalid_request` and name the
  failing option.
- **`ekk/host_api.py`, a declared surface for hosts such as a gateway.** It
  offers reads, capture and retain once, an observed call with a declared
  caller, and the active and loaded release identity.

## Compatibility

The record format, receipts, acceptance validation, the loader fingerprint and the
store verifier are unchanged, so activation needs no index rebuild or audit.

An earlier runtime (0.10.0, or 0.9.1 for a public installation) remains a rollback
target until its own 30-day expiry would delete what 0.10.1 keeps. The installer
refuses that switch while such rows exist, unless `--accept-observer-loss` is
given. `ekk observe prefer --statement-session` now only cross-checks the host
session the command runs in; a different session, or a relayed preference without
one, is refused.

The legacy operation journal records request errors as `invalid_format` at stage
`request`, so older readers keep journaling.

Mechanism tests do not establish benefit.
