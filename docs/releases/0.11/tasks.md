# Implementation and verification plan

Date: 2026-10-10. Slice states: `planned`, `in_progress`, `done`. Each slice is
complete on its own: code, focused tests, documentation of the changed surface.
0.10.1 has its own [plan](../0.10.1/tasks.md) and lands first. Findings closed by
each slice are listed in [status](status.md).

## Research steps that cannot wait

Claude Code deletes transcripts after 30 days by default, so the inputs of two
measurements disappear while 0.11 is built.

| ID | Step | Verification | When | State |
| --- | --- | --- | --- | --- |
| R01 | Correction rule 2 as a pure digest-pinned rule; freeze its September baseline (complete for Codex, partial for Claude Code) | Rule 1 digest unchanged; rule 2 fixtures for injected text, the word boundary and repeat phrases; baseline digest recorded | Now, before 2026-10-14 | done 2026-10-10 |
| R02 | Normalizers for both hosts, `ekk.session-change/1`, `credited_changes`; freeze the change facts (no text) of the first post-0.10 week for the replay | September counts reproduced exactly; parser fixtures for both hosts, segments and truncation | Before 2026-11-01 | planned |

## Slices

| ID | Slice | Depends on | Verification | State |
| --- | --- | --- | --- | --- |
| T01 | Authority: `decision_queue`, `accept_current` against one view with re-resolved snapshots, acceptance by standing (or, on the owner's veto, `decide` refusing outcome targets), locating owner words with three outcomes (D-0.11-15) | 0.10.1 | A head pinning an older target revision is refused before any write; a chain accepted while the snapshot advances; refusal when readable words are absent; the five real statement shapes as fixtures; no adapter calls a private service method | planned |
| T02 | Review due: `reviews` table, `review_state`, notice in status, card and `enter --brief` with the daily claim and urgent bypass (D-0.11-08) | 0.10.1 | Notice once per day; urgent within 3 days of expiry; no realm loaded on the hot path | planned |
| T03 | Review page: protected sample, backlog sized by time to apply, per-realm resolution and de-duplication, `x/a/c/n`, `--marks` and `--group`, groups as revisions of existing preferences, `n` on an outcome archives it, `n` on a chat acceptance withdraws it, review dialogue bound (D-0.11-09) | T01, T02, R01 | Page written within 30 s from a copy of the real observer state; bulk lines never touch the sample; a correction after apply in the same session is pending; idempotent re-apply | planned |
| T04 | Correction rule 2 in the hook and the observer: both flags, union for pending and the sample (D-0.11-11) | R01 | Both flags stored; rule 1 output byte-identical | planned |
| T05 | Owner work as a session property applied to episodes, corrections, writes and deliveries; Claude Code marker verified on a real scheduled session (D-0.11-02) | R02 | Fixtures for Codex user, subagent and guardian threads, missing transcripts, Claude Code `claude-desktop`, `cli` and `sdk-cli` | planned |
| T06 | Episode rule 3 in the observer with rule 2 shadow; re-close of open held episodes at upgrade; the one-time backlog list of rule 2 records rule 3 would not keep (D-0.11-03) | T05 | Spec acceptance 2 (private replay); `activity_unknown` never credited; zero stored text | planned |
| T07 | Agent writes link their episode and follow the queue key to read-back; subagent writes map to the parent; `decide` reported apart (D-0.11-05) | T06 | Same-session retain: no second record; `needs_attention` publishes the composed outcome; retain before later changes: published with the link | planned |
| T08 | Title rule 1; skipped text window; a kept skipped episode publishes (D-0.11-06) | T03, T06 | Title fixtures from real report shapes; text cleared after 14 days | planned |
| T09 | Host health and the connection path: four states computed by the observer run, `ekk.connectors/0.1`, stable launcher path, install returning owner actions, uninstall (D-0.11-07) | 0.10.1 | Fixtures reproducing a stale trust entry and an EKK entry rewritten after trust; zero journal reads per `enter`; unchanged command leaves `hooks.json` bytes unchanged whatever PATH is; a malformed connector entry leaves journal rows intact | planned |
| T10 | L1: pins by version range, lazy commit views with digest checks, fallback for broken commits (D-0.11-16) | — | Spec acceptance 4; count gates on whole historical loads and scan steps | planned |
| T11 | L2: `.git/HEAD` binding, one object reader per operation | T10 | Count gate on Git spawns per entry; recovery still reads fresh | planned |
| T12 | L3: lazy read-only published views with bounded memos, consumers read only what they need, cached ranking vectors | T11 | Count gates on bytes read, records tokenized and memo bounds across many commits | planned |
| T13 | Publication: one validated view, read-back from Git, incremental trees for both store kinds, `diff-tree` check before the reference moves (D-0.11-17) | T12 | Spec acceptance 5; count gates on views and validations per publication; a wrong tree is refused before the reference moves | planned |
| T14 | Hand-off and audit: covered contenders exit, uncovered ones wait; the observer run starts a worker for stale `local_pending` rows; audit as its own locked pass after publications, one per store | T13 | Uncovered request enqueued during a holder's pass is published; audit beside a publication and a synchronous accept: no conflict | planned |
| T15 | Latency and output evidence: realm on drain rows, outbox timings, output bytes and items per delivery, `tools/bench_entry.py` | T14 | Spec acceptance 3 against the baselines in status | planned |
| T16 | Operation journal v2 outside the legacy directory; abandoned begins; merged reports; loss matched against transcripts (D-0.11-19) | — | Parallel-call stress test loses no rows; a 0.10.1 writer keeps appending to the legacy file without warnings while v2 runs | planned |
| T17 | Worker log rotation; home-path normalization at capture (D-0.11-20, D-0.11-21) | — | Rotation at 1 MiB; fixtures; agent retain bytes unchanged | planned |
| T18 | Evidence readiness: named series, runtime windows from manifests, strata, both change series, read-only accessor, minimum-n reporting, hub, displacement and automatic-outcome share, continuation against September (D-0.11-14) | T03, T04, T06, T15 | Field-use tests on fixtures; "insufficient n" below the minimum | planned |
| T19 | Advisor after the page is written; optional environment install with digest checks (D-0.11-13) | T03 | No advisor load before the page file exists; agreement report on sample labels | planned |
| T20 | Release identity and activation: `active_release()` as a file contract, caller runtimes in host status, warm of the staged release before the switch, checkpoints per verifier, rollback drill (D-0.11-18, D-0.11-23) | T09, T13 | Spec acceptance 7; `active_release()` follows a switch made by another process; a failed warm does not switch | planned |
| T21 | Documentation: handbook, release notes, decision table regenerated, export allowlist for new modules | T01–T20 | Links checked; export review | planned |
| T22 | Gate: spec mechanism acceptance 1–8 (and 9 if the gateway is kept) on the exact staged source | T21 | All pass | planned |
| T23 | Delivery: activate through T20's path, rollback reference to 0.10.1, retained result | T22 | Installed CLI workflow; warm report per store | planned |
| G01 | Gateway, kept by the owner's choice and outside the gate: in the gateway project, version control, imports only from `ekk/host_api.py` (shipped in 0.10.1), build from the release wheel, preflight digest check, pause marker on `runtime_superseded`, no automatic reconnect; the owner reconnects the tunnel | 0.10.1 | Spec acceptance 9; host status lists it on the active runtime | planned |

## Before 0.11 is activated

| ID | Step | When |
| --- | --- | --- |
| P01 | Descriptive snapshot of 0.9.1 and 0.10.0 on fixed windows, transcript-derived measures only, from the study source of the 0.10.0 delivery | After P02 |
| P02 | 0.10.1 active | Done: 2026-10-10 at 23:26:59 UTC |
| P03 | The owner's answer to the review prepared on 2026-10-10, kept verbatim, applied with 0.10.1's declared provenance | After P02 |

## Not in 0.11

| Item | Why | Revisit |
| --- | --- | --- |
| Removing rule 2 polling | Needs one release of shadow data and the recorded comparison | 0.12 |
| Archive prior or a hub cap | Needs the labelled stratum and the pre-registered rule | When the minimum labels exist |
| Link rule 2 (multi-day sessions) | Measured net gain is zero under the current ambiguity rule | If multi-day sessions become a visible miss |
| Superseding repeated progress retains through `retain` | A current-first (C) change to who may supersede; T07 provides the session link it would use | When sessions keep more than one retain per task after T07 |
| Crediting subagent changes | Changes one disposition in 181 in the replay; delegated-only work is held for the owner | When field use shows delegated-only work being missed |
| Compaction of published request bodies | About 85 MB today; it would break 0.10's backup reader | When their size matters |
| An audit outside the writer lock; a stat-based clean-tree check | Thresholds hold without relaxing either check | If per-request stage durations put the publication threshold at risk |
| Advisory privacy counts on retain receipts | No consumer; no secret values were found | — |
| Share-boundary privacy scan | No store is shared | When a store is first shared |
| Delegation (G), recall at a change of focus | Deferred by D-1.0-16 and the 1.0 status | When subagent re-entry is a visible cost |

Ownership is by module; shared files are edited only in the assigned sections and
unrelated work is preserved. No new worktree, schedule, hook trust, external
account action or public publication is part of the plan.
