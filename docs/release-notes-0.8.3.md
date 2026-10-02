# EKK 0.8.3

Faster work entry and reads for every coding agent, with output identical to
0.8.2. Record format `ekk.record/0.1`, realm identity, selection, acceptance and
recovery semantics are unchanged.

## Why

Cold CLI calls on the owner's two active stores took 7–15 s, and a fetch of one
record cost as much as entry. Profiles showed that ranking was not the cost:

- each call read the same published commit through Git up to six times (on the
  larger store, 111 MB of records and sources each time), including three full
  reads only to learn the realm manifest;
- every `_head`, history and ancestry check started a Git process;
- on a store whose records pin earlier versions, every call reloaded and
  revalidated about ninety past commits in full to resolve those references.

## Changes

- **Immutable Git facts are read once per process.** The files of a commit, a
  tree listing, the history behind a head and commit parents are named by their
  object IDs, so a memo of them never goes stale; publication only adds new IDs.
  The memo is bounded by bytes. The published head is still read on every call,
  from its loose ref file when there is one and from Git otherwise.
- **Past commits are indexed once.** Resolving a pinned reference walks history
  as before, but each commit's record locations come from an index derived from
  one complete, validated load of that commit. Only the matching record is decoded
  again from its exact bytes. The index is a private, authenticated derived cache
  keyed by the code that loads records; a missing or foreign entry is a miss.
- **One file, one read.** A receipt's governance policy and a historical record or
  source asset are read as single files of their commit instead of whole snapshots.
- **Recovery still reads Git afresh.** Operation recovery checks what is durable
  on disk, so it bypasses every memo.

## Compatibility

- No format or interface changes. A new private cache directory,
  `<cache home>/history/<realm>`, can be deleted at any time.
- Output is identical to 0.8.2 for the full projection of eight real entry tasks
  on both stores, the agent view, `fetch`, `read-source` and `doctor`, except for
  the projection's assembly timestamp.
- The installed 0.8.2 runtime remains the rollback.

## Evidence and limits

Cold CLI processes on the owner's machine, median of five runs per request after
one warm-up, both runtimes interleaved under the same unrelated background load
(load average 16–65 during the run, so absolute times are pessimistic):

| Request | 0.8.2 | 0.8.3 |
| --- | --- | --- |
| Entry, larger store (5 real tasks) | 8.1–15.1 s, median 9.7 s | 2.8–5.1 s, median 2.9 s |
| Entry, store with pinned history (3 real tasks) | 14.2–15.2 s, median 14.6 s | 0.52–0.55 s, median 0.54 s |
| `fetch` / `read-source` / `doctor`, larger store | 7.9 / 8.4 / 7.5 s | 2.1 / 2.1 / 2.1 s |
| `fetch` / `read-source` / `doctor`, pinned-history store | 12.6 / 12.8 / 13.1 s | 0.35 / 0.36 / 0.43 s |

The first call after an upgrade, or after many new publications, builds the index
for commits it has not seen and costs about as much as 0.8.2 once. On the larger
store entry still reads the whole published snapshot once and builds the ranking
index in each process; reading source assets only when needed and keeping the
ranking index across processes are the next steps. Writes still re-verify every
past operation in each new process.

The test suite now runs through `tools/run_tests.py`: every module in parallel
with temporary EKK homes, so tests no longer write rows to the owner's operation
journal, and a full run took 8–9 minutes instead of 21–36.
