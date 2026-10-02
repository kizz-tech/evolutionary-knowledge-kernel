# EKK 0.8.4

Writes that finish. Record format `ekk.record/0.1`, realm identity, selection and
acceptance semantics are unchanged.

## Why

On the owner's larger store one synchronous `retain` took four to five minutes
and an agent's `capture` was cancelled after 263 s; the store received no
publication for eleven days. A profile of one write showed where the time went:

- about two thirds in the check that a new record ID never existed before, which
  read and loaded every past commit in full;
- about a quarter in two complete recovery passes, one for the idempotency lookup
  and one for the write, each re-verifying every past operation and re-reading
  every historical blob;
- under 8% in validation, commit and working-tree checks.

## Changes

- **Incremental operation verification.** A write verifies operations that no
  earlier pass verified. A private checkpoint records the verified operations
  with their evidence commit and completed journal digest; an unchanged entry is
  checked only for presence in published history. `ekk recover`, restore
  activation and a missing or foreign checkpoint still audit every operation and
  every historical blob. Old-object corruption is now found by `ekk recover` and
  backup instead of by the next write.
- **Record versions from commit deltas.** The 0.8.3 per-commit record listing is
  replaced by the records each commit added, changed or removed. The index stays
  proportional to what was published, and it also answers the new-ID check, with
  the same result as loading every commit.
- **`capture` is queued like `retain`.** It stores the exact bytes durably, starts
  the background publisher and returns a key; `--wait` keeps the synchronous
  receipt. Without a supplied key, identical content yields the same key.
- **The publisher does not leave late requests behind.** A request queued while a
  publication is running is taken in the same worker's next pass, and a second
  background worker leaves quietly instead of logging a lock error.

## Compatibility

- Scripts that relied on `capture` returning a publication receipt must add
  `--wait` or read `queue status`. Sources above about 12 MiB exceed the queue
  limit and need `--wait`.
- The first write after the upgrade audits the whole store once and builds the
  version index; on the larger store this took about seven minutes in the
  background. The 0.8.3 history cache is unused and can be deleted.
- The installed 0.8.3 runtime remains the rollback.

## Evidence and limits

On an isolated copy of the larger store (about 2,600 records, 170 publications),
under unrelated background load:

| Synchronous `retain` | Time |
| --- | --- |
| 0.8.3 | 497 s (profiled) |
| 0.8.4, first write (one-time audit and index build) | 453 s |
| 0.8.4, later writes | 11 s |

With the queue the agent waits about a second in either case. Focused tests cover
the checkpoint (unchanged, foreign verifier, forged journal), explicit recovery
still auditing everything, record removal and recreation through the version
index, and queued capture published by the worker.
