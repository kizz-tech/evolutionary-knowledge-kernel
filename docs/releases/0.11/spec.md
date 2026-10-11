# EKK 0.11: the ordinary path, measured correctly

Release ID: `EKK-R-0.11`. Target version: **0.11.0**, a local runtime increment
toward the accepted [1.0 target](../1.0/spec.md), installed on top of
[0.10.1](../0.10.1/spec.md). Date: 2026-10-10. The [design](design.md) gives the
mechanisms for both steps, [services](services.md) the component boundaries,
[tasks](tasks.md) the slices and [status](status.md) the current state, the
findings each slice closes and the pre-registered thresholds.

## Problem

The selected course for EKK starts with one field-use comparison of the current
workflow: validate capture and review measurements first, then compare later
work against the September baseline. A practice check of the first week of real
use after 0.10.0 (one owner, four Codex profiles and Claude Code, three bound
projects, 2026-10-03 to 2026-10-10) showed that the ordinary path works
mechanically but cannot yet be measured honestly:

- **Capture counts the wrong sessions.** Every completed user turn in a trusted
  profile produced a report event, but one profile with a third of the turns had
  untrusted hooks, its pre-tool guard included, and nothing reported it.
  Background host sessions with no saved thread were counted as work. Changes were
  credited by polling the workspace: a session started in a parent directory that
  committed in a nested worktree got no credit, EKK's own store commits counted as
  a session's change, and neighbouring sessions lent each other changes. In one
  rater's sample, about two in five skipped episodes had made real edits, and
  skipping deleted their report.
- **Automatic records are noisy.** Titles were the first sentence of a chat
  report ("Checked.", a salutation, raw JSON). An agent's own retain and the
  observer's outcome for the same work were stored twice.
- **The owner's review never ran.** It depended on one host's weekly schedule,
  which failed on a usage limit and was later removed. No labels exist, so entry
  precision, the correction rule, held results and the advisor are unmeasured.
  The page showed only the newest items, and preparing one took about three
  minutes in a run on 2026-10-10. 0.10.0 deletes episodes in every state after 30
  days, so the first held results are lost on 2026-11-01.
- **Entry and publication miss their targets.** Entry on the larger product store
  rose from a median of about 4 s to about 16 s after a curation that moved 142
  records to new revisions: every exact pin to an older revision loads a whole
  historical snapshot, and pinned references are resolved by scanning history. A
  small contained realm pays about 150 Git process spawns per entry. Background
  publication takes about 33 s per write. When the weekly audit is due, it runs
  inside a publication and holds the writer lock.
- **Hosts and operations drift.** The private gateway, used only for reads since
  2026-09-08, still embeds runtime 0.8.0. The operation journal rewrites a 2.5 MB
  file on every call and loses rows under parallel calls. The worker log grows
  without bound. The session card prints shortened IDs that `fetch` refuses,
  `accept --id` fails with an opaque error, and Claude Code openings cannot be
  linked because the session variable name is wrong.

## Connected outcome

**Every real session in every connected host is counted correctly, the owner's
judgement reaches EKK without depending on any host's schedule, entry and
publication meet the 1.0 targets on every store, and every host that serves EKK
runs the active runtime, so that the field-use comparison can run on clean,
stratified data with enough owner labels.**

0.10.1 delivers the part that cannot wait: nothing the owner has not judged is
lost silently, and nothing is attributed to the owner that the owner did not
declare. This specification covers the rest.

## In scope

| Zone | Scope | 1.0 component |
| --- | --- | --- |
| Capture | Owner work as a session property; episode rule 3 credits changes from the session's own tool events (including worktrees) with rule 2 computed alongside; one shared change definition and credit for the observer and field use; the agent's own write links its episode; title rule; skipped text kept for a bounded audit window | B |
| Host health | Trusted, needs-trust, stale and silent hooks per profile, computed by the observer run and shown where agents work; one connection path for Codex profiles, Claude Code and the launch agent | B, S13 |
| Owner review | Review due as observer state shown in status, card and entry; a sample-first page with protected measurement, a backlog sized by time to apply, grouped preferences as revisions, effects for "no" marks, a bounded review dialogue; advisor in shadow after the page is written | F, D |
| Corrections | Correction rule 2 computed alongside the frozen rule 1, on the union of both; its September baseline frozen early | F |
| Authority interface | One decision queue; acceptance by standing; owner words located in the named session | C |
| Entry and publication | Pinned references through the version index; a constant number of Git processes; lazy read-only views with bounded memos and cached ranking statistics; publication proportional to the change with a pre-reference tree check; background hand-off; audit after publication; activation warms the staged release | A, C, D |
| Gateway | `active_release()` as a file contract; the gateway follows it through a declared host facade, or is disconnected, as the owner chooses | S13 |
| Operations | Append-only operation journal beside the legacy one; bounded worker log; home-path normalization in captured text | A |
| Evidence | Named evidence series; fixed comparison windows; observer-backed outcomes through a read-only accessor; latency and output size per store and per request; mechanism count gates; hub and displacement metrics; pre-registered thresholds with minimum samples | F |
| Interface details | Display titles for bare-filename sources; continuation measured against September | E |

## Acceptance

Mechanism acceptance (before activation):

1. The project's full isolated compatibility suite passes, including count gates
   on whole historical loads, history scan steps, Git process spawns per entry,
   records tokenized on a warm call, views and validations per publication, and
   memo bounds, plus a test that reproduces the September baseline's session and
   changed-session counts under `ekk.session-change/1` with every rule digest
   unchanged.
2. A replay of the owner's first post-0.10 week (private) under rule 3, from frozen
   change facts: no episode from a non-owner session, no store self-write credited,
   every worktree change of a session credited to its bound workspace, rule 2
   recorded beside rule 3 for every episode.
3. The entry benchmark on copies of the real stores, with isolated homes: warm
   entry wall time at or below 3 s on every store, and exact references and scores
   of entry and search identical to 0.10.1, with display text differing only by the
   bare-filename transform.
4. Every exact pin in every store copy resolves to the same revision through the
   version index as through the legacy scan.
5. On copies of every store, every historical operation replayed through the
   incremental tree builder reproduces its recorded tree, for both store kinds, and
   `ekk recover` passes after 0.11 publications.
6. A real read-equivalence gate against 0.10.1 on unchanged requests, as in 0.10.
7. A rollback drill on isolated copies: after 0.11 activity and a rollback to
   0.10.1, hook inserts, publication, backup and journal writes work, and no held
   episode, tombstone or correction disappears.
8. Host status names every enrolled Codex profile and Claude Code as trusted,
   needs-trust, stale-suspected or silent, from fixtures that reproduce the
   observed stale trust entry, and an affected profile is visible in its own
   `enter --brief`.
9. If the owner keeps the gateway: it imports only the host facade, and it refuses
   to serve when the active runtime differs from the one it loaded.

Field acceptance (over the 0.11 observation window, judged from runtime-stamped
data with the series, minimum samples and thresholds pre-registered in
[status](status.md)):

- entry, publication and agent-wait thresholds on every store;
- journal loss and abandoned begins within their thresholds; every review page
  written within 30 s;
- the pre-registered minimum of sample-labelled items, and no held result or
  correction lost without being counted;
- every host that serves EKK runs the active runtime.

Benefit is not claimed by 0.11. The comparison that the course requires runs once
the minimum labels exist, against the September baseline, under the
pre-registered thresholds of the 1.0 specification.

## Exclusions

- No new scheduler, daemon or host automation. The review becomes due through
  observer state; any host's agent conducts it with the owner's agreement.
- No automatic hook trust, and no computing of trust values. Trusting a hook in a
  Codex profile stays the owner's act.
- No transcript storage. Rule 3 reads bounded structured facts (changed paths,
  verified commits, the agent's own EKK calls) and stores no text.
- No ranking change without owner labels. The archive prior and any hub cap wait
  for the labelled stratum and the pre-registered rule.
- No change to the agent contract.
- No relaxation of a byte-exact check: the clean-tree check and the audit stay
  byte-exact and under the writer lock.
- No crediting of subagent changes; no compaction of request bodies; no
  share-boundary privacy scan. Each is deferred with a reason in [tasks](tasks.md).
- No rewriting of existing records or receipts, no change to the record format,
  and no change to the frozen correction rule 1 or its September baseline.
- No gateway reconnect without the owner's go-ahead, and no publication of the
  release. Public publication is a separate request.
