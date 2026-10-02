# EKK 0.8.1

A corrective release of 0.8 based on field observation of real use: what work
entry delivers, how long it takes, and what agents trip over. Record format
`ekk.record/0.1`, realm identity and acceptance semantics are unchanged.

## Why

Logs of ordinary agent work from 7 September to 1 October showed three problems
with 0.8 (details stay with the owner; this is a technical summary):

- Entry ranked records by how many distinct task words appeared anywhere in a
  record and in up to 1 MiB of each source asset, without stop words, word
  rarity or length normalization. Long captured pages and hub documents matched
  most tasks, so the same few records filled a large share of every result.
- Most listed records reached the agent as a title and metadata without any text,
  and agents rarely opened them afterwards. Entry output was dominated by
  structural metadata.
- `retain` blocked the agent for about a minute or longer; interrupted and
  lock-contended writes were the most frequent failures. Display flags used with
  the wrong command and hand-built exact references caused avoidable format errors.

## Changes

- **Entry relevance.** Optional reading is ordered by BM25 over title and aliases
  (weight 3), body and the readable opening of each text source (weight 1, 8 KB,
  markup removed). Common Russian and English words are ignored and inflected
  forms are matched conservatively. Records scoring below a quarter of the best
  match are not candidates. Mandatory and governing selection, dependency closure,
  challenges and changed grounds are unchanged. `manifest.source_search` now
  describes this coverage; reading only source openings is declared coverage and
  no longer marks a projection incomplete.
- **Cheaper budget accounting.** The context budget counts the stored canonical
  bytes of current records instead of re-encoding every candidate (about 4 s per
  entry on the larger store), and stemming is cached. Building the BM25 index
  costs 1.5–3 s per process, so cold CLI entry on the larger store went from a
  median of 7.9 s to 6.4 s on five tasks. On a store whose records pin historical
  versions, entry still spends most of its ~13 s reading past snapshots to resolve
  those references; that is the next latency fix.
- **Why a record is here.** Each selected record carries `selection`
  (`required`, `ranked`, `related` or `dependency`); ranked records carry
  `discovery` with the matched task words and passage.
- **One short agent view.** `--brief` and `--compact` on `enter`/`context` print
  `ekk.context-brief/0.2`: required reading in full; ranked records with title,
  date, passage, reason and exact reference within a 4 kB target; pinned records
  and grounds as title and ID; plus `incomplete_reasons`. Because the view
  summarizes, it selects with a 64 kB record budget unless `--budget` is given, so
  a few large pinned records no longer crowd out relevant ones. Other commands
  accept and ignore display flags.
- **Asynchronous retention.** `retain` queues the frozen request durably, starts
  the background publisher and returns `ekk.retention-queued/0.1` with
  `state: local_pending`. Without a supplied key, identical content yields the
  same key. `--wait` keeps the previous synchronous behavior and receipt.
- **Reading by ID.** `fetch --id ID` and `read-source --id ID` build the exact
  reference to the current version of a listed record.

## Compatibility

- Consumers of the 0.8 `--compact` projection (`ekk.context-display/0.1`) receive
  `ekk.context-brief/0.2` instead; the full projection is available without the
  flag. The brief schema replaces `material` with `items`.
- Scripts that relied on `retain` returning a publication receipt must add
  `--wait` or read `queue status`.
- The installed 0.8.0 runtime remains the rollback.

## Evidence and limits

A field-use study (`research/studies/field-use`) reconstructs agent episodes from
local logs. On the owner's real entry tasks, the known-item benchmark (a repeated
task finding the result its earlier session retained, top 8, averaged per target)
rose from 0.11 to 0.36 on the larger store and from 0.19 to 0.40 on the smaller
one. The share of each result taken by records that appear for at least 30% of
tasks fell from about 0.3 to 0. In a warm process, full entry on 30 sampled
tasks took a median of 3.1 s on the larger store. These are mechanism and
retrieval measurements on one owner's data, not proof of better agent work. BM25
is lexical: paraphrase and cross-language matches remain weak, which is where a
semantic advisor can be compared against this baseline.
