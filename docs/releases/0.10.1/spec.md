# EKK 0.10.1: nothing lost, nothing misattributed

Release ID: `EKK-R-0.10.1`. Target version: **0.10.1**, a local runtime increment
on 0.10.0. Date: 2026-10-10. The mechanisms are in the
[0.11 design](../0.11/design.md) (B0, F3, F5, C and E, marked 0.10.1); the
findings are in [0.11 status](../0.11/status.md).

## Problem

- 0.10.0 deletes episodes in every state 30 days after their last activity. Held
  results the owner has never judged are lost from 2026-11-01, and the review page
  shows only the newest of them.
- An agent that applies the review page records the owner's marks as the owner's
  own page edit, and an agent that records the owner's decision defaults to
  `agent`. Both lose who actually spoke.
- Claude Code sessions are read from the wrong variable, so its openings cannot be
  linked; three resolvers of host identity disagree.
- `accept --id` fails with an opaque error; the session card prints shortened IDs
  that `fetch` refuses; request errors share one code with runtime defects.

## Connected outcome

**Nothing the owner has not judged is lost silently, nothing is attributed to the
owner that the owner did not declare, and every observer row says which host,
session and runtime wrote it.**

## In scope

| Slice | Design |
| --- | --- |
| One host identity; runtime stamps; versioned observer schema with additive columns; read-only accessor; transcript path in the spool | B0 |
| Explicit, counted expiry: held and composed at 60 days, pending corrections at 90, text-free terminal rows for 365 days | F3 |
| Declared provenance on `apply-review` and `decide` | F5 |
| `accept --id --words` building a host-chat statement; refusals that name the missing fields | C |
| Full IDs on card and page; prefix error naming the full ID; `invalid_request` | E |
| Review page lists held results and corrections oldest first, with counts | F2 |
| A declared host facade, `ekk/host_api.py`, with pinned signatures, so the gateway can be rebuilt on the active runtime | S13 |

## Acceptance

1. The full isolated compatibility suite passes, with tests for the migration of a
   0.10.0 observer database copy, inserts by 0.10.0 code into the migrated schema,
   expiry tombstones and text-free rows, refusals without a declaration, and the
   Claude Code session variable.
2. The loader fingerprint and the store verifier are unchanged from 0.10.0, so no
   index rebuild or audit follows activation.
3. A real read-equivalence gate against 0.10.0 on unchanged requests, apart from
   the full IDs on the card.
4. After activation, `ekk observe status` shows the next explicit expiry later than
   2026-11-01 and no episode deleted without a count.

## Exclusions

Everything else in the 0.11 package: rule 3, host health, the review mechanism,
the read and write paths, the journal, the gateway. Correction rule 2 ships as
unused code; the runtime keeps rule 1. The decisions that settle open points of
the design are in [implementation.md](implementation.md). No change
to the record format, receipts, the agent contract or acceptance validation.
