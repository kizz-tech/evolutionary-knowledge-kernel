# Implementation and verification plan

Date: 2026-10-10. Slice states: `planned`, `in_progress`, `done`.

| ID | Slice | Depends on | Verification | State |
| --- | --- | --- | --- | --- |
| U01 | `adapters/host_identity.py` replacing the three resolvers; session variable declared per host in the registry; runtime column on every observer row; `user_version` migration with nullable or defaulted columns; read-only accessor; `transcript_path` in the spool | — | Migration of a 0.10.0 database copy; 0.10.0 inserts still succeed; Claude Code openings link in a fixture; the accessor leaves bytes and mtime unchanged and refuses a newer version | done |
| U02 | Explicit expiry with tombstones and text-free terminal rows; counts and next expiry in status | U01 | Clock-driven tests: nothing deleted without a count; composed and held both covered | done |
| U03 | Declared provenance: `apply-review --relayed --words` or `--owner-marked-page`; `decide --stated-by` required, `owner-relayed` requires `--owner-words` | U01 | Refusal without a declaration; recorded host and session beside it; a page in the 0.10.0 format applies with `--relayed --words` | done |
| U04 | `accept --id --words`: current exact reference, host-chat statement, named refusals | U01 | Missing words, unknown ID and a superseded target each give a named error; existing receipts validate | done |
| U05 | Full IDs on card and page, whole-line truncation, prefix error, `invalid_request`; held and corrections oldest first with counts on the page | — | Display and error-code tests | done |
| U07 | `ekk/host_api.py`: dispatch to an envelope, capture or retain once, an observed call with a caller, `active_release()` read from `cli/current` as a file contract; signatures pinned by a test | — | Signature test; `active_release()` follows a switch made by another process | done |
| U06 | Gate and delivery: suite, fingerprint and verifier unchanged, read equivalence, install with rollback reference to 0.10.0, release notes | U01–U05, U07 | Acceptance 1–4 | done |

Completion evidence (2026-10-11): U01–U05 and U07 pass their tests in the full
isolated suite; the decisions that settled their shared points are in
[implementation.md](implementation.md). U06 passed acceptance 1–3 before
activation and acceptance 4 on the owner's observer after it. The release was
activated on 2026-10-10 at 23:26:59 UTC, a week before the planned date, on the owner's word. The
[status](status.md) has the results.

The owner's answer to the review prepared on 2026-10-10 is kept verbatim and
applied with U03's `--relayed --words` after activation.
