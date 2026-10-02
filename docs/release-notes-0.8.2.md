# EKK 0.8.2

Host parity for Claude Code, kept host-neutral so another coding agent can join
the same way. Record format `ekk.record/0.1`, realm identity, entry and retention
behavior are unchanged from 0.8.1.

## Why

Claude Code reached the same bound projects as Codex through the same CLI, but
two parts of the runtime only knew Codex. Its operations were recorded as
`unknown`, so field use could not compare hosts from the operation journal, and
`task register-wait` rejected any automation receipt that did not come from
Codex, so a Claude Code scheduled task could not be recorded on a waiting task.

## Changes

- **Caller attribution by registered environment.** `config/callers.yaml` accepts
  an optional `environments` map from a caller ID to the environment variables
  its host sets for every command, for example `claude-code: {CLAUDECODE: "1"}`.
  Markers apply only outside Codex (no `CODEX_HOME`); Codex attribution is
  unchanged. A process that matches several markers stays `unknown`. Attribution
  remains diagnostic provenance, not authentication.
- **Host-neutral automation receipts.** `task register-wait` records a receipt
  whose `host` is `codex` or `claude-code`. The receipt is still the host's
  declaration, not a verification that the schedule stays active.
- **Handbook.** Continuous work and daily reliability describe the host-neutral
  automation and the caller registration.

## Compatibility

- Without an `environments` entry, attribution is exactly as in 0.8.1. Runtimes
  before 0.8.2, including bundled gateway runtimes, ignore the new key.
- After the owner registers Claude Code, its operations move from `unknown` to
  `claude-code` in the journal. Compare host shares across this change by
  registration date, not as a change in use.
- The installed 0.8.1 runtime remains the rollback.

## Evidence and limits

Focused tests cover Codex precedence, an unregistered Codex home, ambiguous
markers, invalid registrations and receipts from both hosts. This release
changes what can be recorded; it makes no claim about benefit.
