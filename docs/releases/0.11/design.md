# Design: the ordinary path, measured correctly

Date: 2026-10-10. Scope: two local runtime steps on 0.10.0 toward the accepted
[1.0 target](../1.0/design.md): [0.10.1](../0.10.1/README.md) first, then 0.11.0
on top of it. Record format 0.1, exact sources, receipts and the authority model
stay as they are. Decision IDs `D-0.11-NN` are decision records in the project
realm; the generated table is in [1.0 decisions](../1.0/decisions.md).

## Where this leads

The 1.0 target says past work measurably improves the next work, in every host,
proven in real use. Its components are A (writes that finish), B (experience
from host events), C (current-first knowledge), D (relevance on a fixed
baseline), E (one contract), F (evidence through a frozen baseline and the
owner's review) and G (delegation). 0.8.4 to 0.10.0 delivered the mechanisms of
A to F. The first week of real use showed that their measurements cannot yet be
trusted, and that 0.10.0 deletes held results the owner has never seen from
2026-11-01. 0.11 is not a feature release. It makes the ordinary path countable,
judged by the owner and fast enough for the comparison that the course starts
with:

```
host events ──► owner-work gate ──► episode (own tool events) ──► outcome / link / hold / skip
     │                                                                  │
     └─ trust & liveness ─► host health ◄── journal calls by caller     ▼
                                                               realm store (current-first)
owner ◄── review due (status, card, entry) ◄── sample, expiry, backlog ◄──┘
  └── verdicts (declared provenance) ──► labels, preferences, acceptances, withdrawals
field use ◄── runtime-stamped observer rows, named series, fixed windows, minimum n
```

## Two steps (D-0.11-01)

| Step | Outcome | When |
| --- | --- | --- |
| 0.10.1 | Nothing the owner has not judged is lost silently, and nothing is attributed to the owner that the owner did not declare: one host identity, runtime stamps, explicit expiry, declared provenance, working `accept --id`, full IDs | Activated on 2026-10-10 at 23:26:59 UTC on the owner's word (planned for 2026-10-17); the 0.10.0 snapshot window ends there; no index rebuild or audit, because neither the loader fingerprint nor the store verifier changes |
| 0.11.0 | Every real session is counted correctly, the owner's review runs without any host schedule, entry and publication meet the 1.0 targets, every host serving EKK runs the active runtime | Activated when its gate passes, on top of 0.10.1, so that a rollback keeps explicit expiry |

0.10.1 removes the date from 0.11. A single 0.11 would have to be active before
2026-11-01 or lose data, and a rollback from it to 0.10.0 would delete the held
backlog again.

After 0.11 the order is the course's: observe a window until the pre-registered
minimum labels exist, compare, and let the results choose 0.12 (removing rule 2
polling, the archive prior, link rule 2 for multi-day sessions, delegation G if
subagent re-entry becomes a visible cost). Method transfer and dependent-work
repair stay research until the comparison is recorded.

## Principles applied

- **Mechanisms, not instruction rules.** Every gap is closed by state EKK
  computes or by an interface that refuses an incomplete request. The agent
  contract is unchanged.
- **Declared, never inferred.** Who spoke is declared on every command that
  records it (D-1.0-25, D-1.0-12). Host, profile and session are recorded beside
  the declaration as facts; they never choose it.
- **Count, never guess.** Each new rule has a version ID recorded on what it
  produces; the rule it replaces is computed alongside where comparability needs
  it. Each threshold names its series, its minimum sample and its source before
  the window opens.
- **Nothing is lost silently.** Every expiry, skip, untrusted or stale hook and
  lost diagnostic is a counted state that status reports.
- **Verification is never relaxed for speed without evidence.** Performance work
  keeps byte-identical results and every byte-exact check; count gates in tests,
  not wall-clock thresholds, guard it.

## Decisions revised

| Earlier decision | Change | By |
| --- | --- | --- |
| D-1.0-11 episode rule 2 | Superseded by episode rule 3; rule 2 is computed beside it for one release | D-0.11-03 |
| D-1.0-18 change credit by polling | Superseded by the session's own tool events; its revisit condition (hosts' own file events) is met | D-0.11-04 |
| D-1.0-22 final report as outcome and title | Superseded: the final report stays the body, title rule 1 gives the title | D-0.11-06 |
| D-1.0-24 commits recorded by the hook, signatures by the observer | Stands for the rule 2 shadow; replaced when polling is removed in 0.12 | — |
| 1.0 owner decision: ten minutes a week for the owner sample | Revised only if the owner accepts the page budget of D-0.11-09 | D-0.11-09 |

D-1.0-10 (subagents form no episodes), D-1.0-12, D-1.0-21 and D-1.0-25 stand.

## B. Capture that counts the right work

### B0. One host identity (D-0.11-24, 0.10.1)

One adapter, `adapters/host_identity.py`, returns (host, profile, session) for the
hook, the journal, delivery and reading notes, accept, decide and review. It
replaces the three resolvers of 0.10. The caller registry declares each host's
session variable: `CODEX_THREAD_ID` for Codex; `CLAUDE_CODE_SESSION_ID`, with
`CLAUDE_SESSION_ID` as a fallback, for Claude Code. The hook event and the journal
row of the same call carry the same (host, profile), also for a profile whose
directory name differs from its registry key. A host without a declared session
variable can record nothing as `host_chat`.

Every observer row carries the runtime that wrote it. The observer schema has a
`user_version`, new columns are nullable or defaulted so that 0.10.0 inserts keep
working, and a read-only accessor opens the database with `mode=ro`, runs no DDL
and refuses an unknown version. Field use reads only through it.

### B1. Owner work (D-0.11-02)

Owner work is a property of a session, computed once when its transcript is first
readable and cached beside the transcript cursor. For Codex, the rollout lies under
that profile's home, its `session_meta.id` is the session and `thread_source` is
`user` (not `subagent` or `guardian_review`). For Claude Code, a top-level
transcript (not under `subagents/`) whose `entrypoint` marks an interactive session
(`claude-desktop` or `cli`); `sdk-cli` sessions are not owner work, and the marker
of scheduled sessions is verified on a real one before host parity is claimed.

The property applies to everything from the session: its episode closes as
`not_owner_work` with a reason (`no_transcript`, `thread_source=<value>`,
`entrypoint=<value>`), its correction candidates move to a counted
`not_owner_work` state, and its agent writes and deliveries are stratified apart.

### B2. Episode rule 3: the session's own tool events (D-0.11-03, D-0.11-04)

Changes are credited from what the session itself did, read from its transcript
when the episode closes. Three parts with separate owners:

- **The definition.** `ekk.session-change/1` is a pure, digest-pinned predicate
  beside the correction rules in `observation.py`. It reads normalized events
  (kind `file_change`, `commit` or `ekk_call`; ok; path; item ID; turn; actor) and
  decides a changed session exactly as the September field-use definition does: a
  completed file change, a successful edit or write, or a successful commit
  command.
- **The normalizers.** `adapters/host_transcripts.py` turns Codex rollout items and
  Claude Code `tool_use`/`tool_result` pairs into normalized events. Normalizers
  are versioned as collector rules, recorded on activity rows and field-use runs;
  a normalizer fix never changes the predicate's digest. The reader is incremental
  (path, inode, size, offset), prefilters item kinds by bytes, follows continuation
  segments, rescans on truncation and de-duplicates by item ID. Its cursor store is
  a parameter: the observer keeps it in its database, field use and the private
  replay in memory. It stores no text.
- **The credit.** `credited_changes(events, workspace, store_root, resolver)` is
  one shared function: a path counts when it resolves into the bound workspace
  through `.git`, `gitdir` and `commondir`, so a worktree whose main checkout is
  inside the workspace counts wherever it lives; paths under the realm's store
  root and store snapshot commits are excluded; a commit hash printed in output
  counts only after the resolver confirms it in that repository. The observer and
  field use both call it.

Field use reports two named series: changed anywhere (the September definition)
and changed in the bound workspace (rule 3 credit). A test reproduces the
September baseline's session and changed-session counts exactly under
`session-change/1`, with every correction rule digest unchanged.

Disposition: own credited changes keep the episode (or link it, B3); no own
changes and a substantial report hold it; otherwise skip. Being alone, a file
basename in the report and a quoted commit no longer give credit. When events
cannot be read the reason is `activity_unknown`; the episode is held or skipped
and never credited by polling. Rule 2 stays frozen and is computed for every
episode as `shadow_action`/`shadow_reason`; records carry
`experience.rule: ekk.episode-rule/3`.

Subagent changes are not credited in 0.11: in the replay they change one
disposition in 181, and a parent whose edits were all delegated still holds a
substantial report for the owner. A subagent's own retain is mapped to the parent
episode through `parent_thread_id` (B3).

At upgrade, held episodes that are still open are re-closed under rule 3 (they are
observer rows, not records). Published rule 2 records are not rewritten; a
one-time backlog section lists those that rule 3 would not have published, for the
owner's verdict (F2).

### B3. One record per piece of work (D-0.11-05)

After a successful `retain` or `decide`, the CLI writes a private `agent_write`
event (kind, queue key, time, host session, workspace, realm; no text). The
transcript reader also recognizes successful `ekk retain|decide` invocations, so a
lost event does not duplicate. A Codex subagent's write maps to its parent
session.

At close: own changes and an agent `retain` into the episode's realm at or after
the last own change make the episode `linked`. A linked episode follows the write's
queue key: it becomes final when that write is read back, and if the write ends in
`needs_attention` the composed outcome is published instead. A `decide` is
reported apart and does not count as the session's retained outcome. Agent writes
only before later changes leave the outcome published with
`experience.agent_writes`.

### B4. Titles and skipped text (D-0.11-06)

`ekk.title-rule/1` cleans the final report (code fences, host directives, link
markup, a colon lead-in joined with its first item), drops a leading bare
acknowledgement, and rejects JSON- or markup-led text, salutations, narration
about another session and fragments under three words. The title is the first fit
sentence among the first six; otherwise the last verified commit subject, earlier
reports, or "Changes in <repository>: <names>". No fit title and no changes means
hold. A "Result:" line in the contract was rejected as an instruction rule; a
model-written title was rejected by D-1.0-17.

Skipped episodes keep their composed request for 14 days, then the text is
cleared. The review sample draws skipped episodes; a "should have been kept" mark
within the text window publishes the episode like a kept held result, and the
mark measures the skip rule's recall.

### B5. Host health and one connection path (D-0.11-07)

The hourly observer run computes health per enrolled Codex profile and for Claude
Code and stores one row per profile; `enter --brief` only reads that row, so entry
does no journal scan. States:

- `trusted`: the hook ran since EKK last wrote it (an observer event for EKK hooks;
  Codex's own execution records for other hooks where they exist, otherwise
  `unverified`);
- `needs_trust`: no trust entry, or the entry's opaque value is the one EKK saw
  before its own last write of that handler;
- `stale_suspected`: the same handler definition carries different trust values in
  different enrolled profiles, for any hook, the pre-tool guard included;
- `silent`: at least five journal calls by that caller over 7 days and no observer
  event.

EKK compares opaque trust values; it never computes or writes them.

It is reported by `ekk observe status --hosts`, by `observe install` after
writing, and by one attention line in `enter --brief` inside an affected profile,
so the agent tells the owner. Codex profile enrollment and connectors live in an
installer-owned file (`ekk.connectors/0.1`), read only by the installer and host
health; the caller registry, read on every call, is unchanged, so a malformed
connector entry cannot drop journal rows. Hook commands name the stable launcher
path, never a PATH lookup. `observe install` rewrites an EKK entry only when its
canonical command changed, keeps a backup and returns the events that now need
trust; `observe uninstall --host` removes only EKK entries. Trust stays the
owner's act.

## F. The owner's review as a mechanism

### F1. Review due (D-0.11-08)

The observer owns review state: a `reviews` table records each page written and
applied (time, host session, counts, time to apply). `review_state(now)` computes
the backlog per kind, the oldest age, the next explicit expiry and whether a review
is due: labels below the pre-registered minimum and no review applied for 7 days,
or any item within 14 days of expiry (urgent). Proposed decisions are counted per
realm when cards are built, so no realm is loaded on the hot path.

Three host-independent channels carry it: `ekk observe status`, one line on the
session card, and one `next` entry in `enter --brief`. Entry runs in almost every
session, including profiles without hooks and resumed sessions. A per-day claim
lets only the first delivery of the day carry the notice; an urgent notice ignores
the claim within 3 days of expiry. The notice asks the agent to mention it once at
the end of its report and to run the review only when the owner agrees.
`ekk observe review` returns the procedure and a numbered digest, so any host's
agent can conduct it in chat. No schedule is added: a review cannot finish without
the owner, and the owner is in chat daily.

### F2. A page that converges (D-0.11-09)

Measurement and disposition are separate sections:

- **Sample.** A draw seeded by the page date, never judged before: 5 entry results
  from the uniform stratum (the delivered top 5 of each, 25 marks), 3 from the
  stratum where the delivered and plain orders differ (the union of both top 5 in
  an order that reveals neither, about 24 marks), 10 correction candidates from the
  union of both rules, 5 held, 5 automatic outcomes and 3 skipped episodes, plus
  owner-stated decisions awaiting acceptance. About 70 marks, an estimated 10–15
  minutes; six applied reviews reach every pre-registered minimum. Unmarked sample
  items stay unjudged; no bulk line applies to the sample. Only sample labels feed
  precision metrics.
- **Backlog.** Absent from the first page unless an item is within 14 days of
  expiry. Later pages size it from the recorded time to apply, oldest first, with
  "shown X of Y, Z left, oldest expires DATE". Proposed decisions are
  de-duplicated per realm and record, each realm is resolved once per page, and
  the page is written within 30 s. The one-time list of published rule 2 records
  that rule 3 would not have kept is a backlog section.
- **Marks.** Corrections take `x` (keep for this project), `a` (keep for all), `c`
  (a real correction, no standing preference) or `n` (not a correction), so
  correction-rule precision is (x+a+c)/judged. A backlog section may have an
  "every unmarked item: no" line. Items are numbered, and
  `apply-review PAGE --marks '3x 4c 7n' --group '3,4=<statement>'` is equivalent to
  editing the page.
- **Grouping.** Kept corrections with the same destination (realm and area from
  the mark) and the same normalized statement become one preference carrying up to
  ten owner-word artifacts and the event IDs; a group may not mix `x` and `a`. When
  a current owner-stated preference with that statement exists in the area, the
  group becomes its revision (exact supersession, union of artifacts), not a
  duplicate. The agent proposes the wording in chat; the owner confirms it.
- **Effects of "no".** An `n` on an automatic outcome queues a revision of that
  record with `adoption: not_adopted`, so it moves to the archive tier and keeps
  its history. Under "accepted in your name", host-chat acceptances since the last
  review are listed with their words and locating result; an `n` there creates an
  owner-stated withdrawal decision that supersedes the accepted record and is
  accepted in the same apply with the owner's mark as the statement.
- **Review dialogue.** Corrections in the reviewing session between the page write
  and its apply are `review_dialogue`, not pending; later corrections in the same
  session are pending. Field use applies the same bound.

A page is about 70 marks, against the 1.0 design's ten entry results and five
preferences a week. It is larger because every measure needs its minimum sample
and the backlog is 113 corrections and 111 held results with an inflow near 88
and 50 a week. A smaller page means more reviews before the comparison; the page
budget is an owner choice.

### F3. Explicit expiry (D-0.11-10, 0.10.1)

Held and composed episodes become `expired_unreviewed` at 60 days from their last
activity; pending corrections and review dialogue at 90 days. Their title, request
and text are cleared, and the row stays as a counted tombstone. Terminal episodes
(published, linked, skipped, not_owner_work, rejected) lose their text on the
schedule they have today, but keep a text-free row (key, host, profile, session,
state, reason, rule, shadow, runtime, times) for 365 days, so field use can read
any window. Tombstones and text-free rows are deleted after 365 days. Status shows
expired counts and the next expiry; F1 escalates 14 days before it. With 0.10.1
active since 2026-10-10, the oldest held results expire on 2026-12-01 instead of
being deleted on 2026-11-01.

### F4. Correction rule 2 beside rule 1 (D-0.11-11)

Rule 1 keeps every byte; its digest pin enforces this, and it gates the primary
outcome against the September baseline. Rule 2 has its own objects: injected host
texts added to the exclusions, the Russian second-person cue ("you ... not")
anchored to a word boundary, and bounded Russian repeat phrases ("last time", "I
did ask", "how many more times", "yet again", "again"). The hook spools text when either rule fires and stores both flags;
the observer keeps a candidate pending if either fires; the review sample draws
from the union, so owner labels give both rules' precision on the same items. Rule
2's September baseline is frozen as soon as the pure rule exists, before the
remaining Claude Code transcripts of September age out: complete for Codex,
partial for Claude Code. It is a secondary series.

### F5. Declared provenance (D-0.11-12, 0.10.1)

`apply-review` refuses without one of two declarations:
`--relayed --words FILE` (the owner's verbatim reply, first 600 characters plus its
digest; preferences `stated_by: owner_relayed`, decisions accepted
`via: host_chat`) or `--owner-marked-page` (the owner edited the page; `owner`,
`review_page`). `decide` refuses without `--stated-by agent|owner-relayed`, and
`owner-relayed` requires `--owner-words`. Host and session from B0 are recorded
beside the declaration; a declaration that contradicts them (an owner-marked page
declared from inside an agent session) is listed under "accepted in your name".
Session cards and the entry prior treat `owner` and `owner_relayed` alike.

### F6. Advisor in shadow after the page is written (D-0.11-13)

Following D-1.0-17, the advisor runs in the same `ekk observe review` command
after the page file is written, on the page's sample items, within a 120 s budget;
its labels are stored and never shown, and `apply-review` reports agreement on
sample labels. Page preparation time is the time until the page is written. The
drain never runs the advisor. Its environment and weights (about 2 GB on disk,
about 4.4 GB of memory while it runs) live in a temporary folder of an earlier
session today; with the owner's agreement of 2026-10-10 they are copied into the
EKK home with digest checks. Without them, review works and status reports the
advisor as absent.

### F7. Evidence series and readiness for the comparison (D-0.11-14)

- Status reports named series, never a pooled rate: the legacy `used` mark of
  0.9.1, `exact_reading_link/1` of 0.10, and field-use transcript signals. The
  24 h linkage window is unchanged: removing it gives no net gain under 0.10's
  ambiguity rule.
- Field use derives runtime windows from release manifests, stratifies every
  measure and refuses to pool across windows. It reads observer outcomes and held
  and skipped denominators through the read-only accessor, records its own source
  commit and the observer schema version, applies the review-dialogue bound, and
  counts continuation commands against their September use.
- Entry evidence adds output bytes and item count per delivery, hub share and
  prior displacement per realm and week, and the share of automatic outcomes
  among delivered items with their sampled precision.
- Each 1.0 measure names its gating series, its minimum labelled sample and its
  threshold in [status](status.md) before the window opens. The comparison reports
  "insufficient n" rather than a value below the minimum. Ranking does not change
  in 0.11; the archive prior changes only under its pre-registered rule.
- 0.10.0 gets a descriptive snapshot on fixed windows (0.9.1 from 2026-10-03 to the
  0.10.0 activation; 0.10.0 from activation to the 0.10.1 activation), from the study source of
  the 0.10.0 delivery, limited to transcript-derived measures: the observer
  measures of that window are invalid (an untrusted profile, wrong sessions counted,
  polling credit). It is not the course's comparison.

## C. Authority interface (D-0.11-15)

- One public application query, `decision_queue(scopes)`, returns current decision
  heads with the exact chains that supersession honours, and the host-chat
  acceptances since a given time. The review, the card and `accept` use it;
  adapters call no private service methods.
- **Acceptance by standing.** An accepted record may supersede any unaccepted
  target. A step for a predecessor is needed only when an unaccepted predecessor
  itself claims an accepted record; then acceptance refuses and names that record,
  so the owner's words cover it explicitly. One statement is never copied onto
  records the owner did not name. This removes a dead end in which a decision that
  supersedes an outcome could never be accepted, and keeps D-1.0-21: an unaccepted
  record still cannot replace an accepted one. If the owner vetoes it, `decide`
  refuses outcome targets instead.
- `accept_current(scopes, record_id, statement, key)` validates against one view,
  then writes with the expected snapshot re-resolved, and refuses if the head
  changed.
- `ekk accept --cwd . --id ID --words FILE` builds
  `{by: owner, via: host_chat, host, session, at, words}`; without `--words` it
  refuses and names the form (0.10.1). `--via cli` or `--statement-file` remain for
  other channels.
- **Locating the words** (0.11). EKK looks for the words in the named session's own
  transcript (top-level user thread, continuation segments followed, injected host
  text excluded, token-boundary match with a minimum length). Three outcomes:
  found, so `spoken_at` and `located: host_transcript` are stored; cannot be
  checked (no transcript, unknown format, a channel without transcripts), so the
  acceptance proceeds with `located: unavailable` and a reason and is listed under
  "accepted in your name"; readable but the words are absent, or the session is not
  a top-level user thread, so acceptance refuses and asks for the owner's verbatim
  words. Statements are validated on write only, so existing receipts stay valid.

## A, C, D. Entry and publication within targets (D-0.11-16, D-0.11-17)

Measured on copies of the real stores with isolated homes (installed 0.10.0), and
in the field:

| Store | Field entry | Copies, warm | Cause |
| --- | --- | --- | --- |
| Larger product store | p50 about 16 s since a curation that moved 142 records to new revisions; about 4 s before it | 11–19 s wall, 9–11 s user CPU | 35 stale exact pins → 39 whole historical snapshot loads; 5,635 history steps |
| Contained project realm | 7–13 s on 0.9.x; one 16 s entry on 0.10.0 (n = 1) | 2.8–3.7 s | 156 Git spawns per entry, 114 of them binding checks |
| Research store | p50 0.6 s | 1.1–2.0 s | Base cost only |

A scratch commit that re-pinned the stale references brought the larger store
back to 3.6–5.7 s, confirming the cause.

- **L1. Pinned references through the version index.** A pin resolves by version
  range from the existing per-record version index, which yields exactly the
  revision the history scan finds; the scan remains only as the fallback for
  broken or unindexed commits. Historical candidate sets become lazy per-commit
  views that decode only the requested record and check its digest against the
  index. The equivalence check covers every exact pin in every store copy against
  the legacy scan; a prototype was byte-identical in 9 of 9 sampled cases and cut
  user CPU on the larger store from 12.8–16.5 s to 3.1–4.9 s. Rewriting stale pins
  was rejected: exact pins to earlier revisions are legitimate provenance.
- **L2. A constant number of processes.** The contained store's binding check
  reads `.git/HEAD` directly (falling back to Git for anything but a plain
  symbolic ref). Each store owns one persistent `git cat-file --batch` reader per
  operation; recovery keeps its fresh reads.
- **L3. Lazy published views and cached ranking statistics.** A published snapshot
  is a read-only mapping of paths to object IDs; bytes are read when needed, so
  preserved sources are not read on entry. Views are memoized by commit, at most 8
  per process and 64 MB in total, least recently used first; the 0.10 bound of
  four loaded views stays. Source digests are checked whenever a source is read and
  in full by apply and the audit. Ranking term vectors are cached per record
  content in a derived cache, so a warm entry tokenizes nothing.
- **Publication proportional to the change.** One publication validates one view
  and reuses it for apply and the card; read-back decodes the committed revision
  from Git. The discoverability check stays a real search. The new tree is built
  from the base tree plus the changed files, for both store kinds; before the
  reference moves, `diff-tree base new` must equal the request's write and remove
  set, otherwise the publication refuses. The clean-tree check stays byte-exact.
- **Background hand-off.** A background drain tries the worker lock without
  waiting; a contender whose scopes the holder covers exits as
  `deferred_to_running_worker`; a contender with uncovered scopes waits with
  today's bound. The hourly observer run starts a worker for `local_pending` rows
  older than five minutes, so no request depends on the next session.
- **Audit after publication.** The weekly full audit stays under the writer lock and
  byte-exact, but runs as its own pass after the drain's publications instead of
  inside one; L2 removes its thousands of process spawns. Only one audit runs per
  store.
- **Evidence.** `queue.drain` rows carry the realm; outbox rows gain
  `enqueued_at`, `published_at` and stage durations. `tools/bench_entry.py` measures
  copies with isolated homes: wall time, self plus child CPU, Git spawns and output
  bytes, against the per-store baselines recorded in status. Tests gate counts:
  whole historical loads, history scan steps, spawns per entry, records tokenized on
  a warm call, views and validations per publication, memo bounds.
- **Write-path oracle.** On copies of every store, every historical operation is
  replayed: base tree plus request blobs must reproduce the recorded tree, for both
  store kinds. `ekk recover` runs on the copies after 0.11 publications.

## Activation and rollback (D-0.11-18)

`local_install.py activate` warms the staged release before switching: it builds
the history index under the staged loader fingerprint, prebuilds the ranking cache
and runs the audit with the staged verifier; it switches only after warm passes,
and records the per-store cost. The audit checkpoint is kept per verifier
(`verified-operations.<verifier>.json`), so 0.10.1's checkpoint stays valid and a
rollback starts warm. A rollback drill on isolated copies is part of the gate:
activate 0.11, run capture, publication, expiry and the journal, roll back to
0.10.1, and verify that hook inserts, publication, `ekk backup` and journal writes
still work and that no held episode, tombstone or correction disappears.

## S13. One active runtime per machine (D-0.11-23)

The CLI, the hooks and the launch agent already run the active release through
the stable launcher. `active_release()` in the package reads `cli/current` and its
build record as a file contract, and host health shows each caller's last runtime
against it, the gateway included.

The private gateway, a separate project, has served reads only since
2026-09-08 and still embeds 0.8.0. The owner chose on 2026-10-10 to keep and
update it and to reconnect it personally:

- **Kept (chosen).** EKK adds one declared host facade, `ekk/host_api.py` (dispatch to an
  envelope, capture or retain once, an observed call with a caller,
  `active_release`), and pins its signatures. Its first version dispatches read
  operations only; writes return as an additive version
  ([0.10.1 implementation decision 19](../0.10.1/implementation.md)). The gateway imports only the facade,
  is rebuilt from the exact release wheel, compares the wheel's digest with the
  active release in its preflight, answers `runtime_superseded` and writes a pause
  marker that its supervisor honours when the active release changes, and never
  reconnects on its own. A connector never refuses an activation or a rollback; a
  failed check pauses the gateway locally and shows in host status. Reconnecting the
  tunnel touches an external account and needs the owner's go-ahead each time.
- **Disconnected (not chosen).** Its launch agent would be removed.

The facade ships in 0.10.1, so the gateway can be rebuilt on the active runtime
right after 0.10.1 is activated; the 0.10.1 and 0.11 gates do not depend on the
gateway project.

## Operations that stay bounded

- **Operation journal v2 (D-0.11-19).** Each call appends at most three short
  lines of `ekk.operation-event/0.2` to segments in a directory outside the legacy
  journal directory, under a lock held for milliseconds; `finish` carries the
  complete row; segments roll at 4 MB and are dropped whole after retention. A
  begin with no finish after 6 h is `abandoned`. The legacy file stays where it is,
  is only read by 0.11, and an older runtime (0.10.1 after a rollback) keeps
  appending to it without warnings; reports merge both. Loss is measured
  independently, by matching `ekk` invocations in host transcripts against journal
  rows per window. Durations in 0.11 exclude about 0.2 s of journal writes; the
  comparison corrects for it as registered in status.
- **Worker log (D-0.11-20).** One line per background pass; the log rotates at
  1 MiB. Compaction of published request bodies is deferred until their size
  matters: today about 85 MB qualify, and compaction would break 0.10's backup
  reader.
- **Privacy at capture (D-0.11-21).** `ekk.redaction-rule/3` normalizes the owner's
  home path to `~` in observer-composed text. Agent retains keep exact bytes. A scan
  at the boundary where a store is first shared is deferred until a store is shared.

## E. Interface details (D-0.11-22)

- The card and the review page print full IDs (0.10.1); the card is cut by whole
  lines. `fetch` stays exact; an unknown ID that is a unique prefix gets an error
  naming the full ID and the exact command.
- Request errors get their own code, `invalid_request`, naming the failing option
  or value; `invalid_format` is kept for malformed records and files, so the
  journal's error rate separates agent requests from runtime defects (0.10.1).
  Until journal v2 the legacy journal records a request error as `invalid_format`
  with failure stage `request`, because older readers refuse an unknown code
  ([0.10.1 implementation decision 4](../0.10.1/implementation.md)).
- A source whose title is a bare file name is displayed as "first heading or
  sentence — file name"; entry and search equivalence compare exact references and
  scores, and display text separately against this transform.
- The agent contract is unchanged. Continuation commands stay in the handbook: the
  owner's stores hold no authored work items, so naming them would point agents at
  an empty set; field use compares their use with September.

## Compatibility and rollback

- Record format, receipts and references are unchanged. New observer columns and
  tables, outbox columns, journal events and label values are additive and nullable
  or defaulted; readers accept old values.
- 0.11's rollback target is 0.10.1, which keeps explicit expiry and declared
  provenance. After rollback 0.10.1 ignores rule 3, host health and the review
  state; journal v2 events are invisible to it; it cannot accept a decision that
  supersedes an outcome.
- 0.10.1's rollback target is 0.10.0, used only before 2026-11-01, because 0.10.0
  deletes episodes after 30 days.

## Risks

| Risk | Mitigation |
| --- | --- |
| Rule 3 triples automatic records (136 of 181 user-thread episodes kept in the replay versus 44) | Holding single-file edits would change only 2–10 %; instead a pre-registered stop rule holds rule-3-only outcomes from 0.12 if their sampled usefulness is below the threshold, and an owner `n` moves a record to the archive tier |
| Host transcript formats drift | Versioned normalizers, counted `activity_unknown`, hold instead of credit; the predicate's digest does not move |
| Shell-written edits are not seen by rule 3 | Substantial reports are held; skipped text is kept 14 days and sampled |
| Claude Code deletes transcripts after 30 days | Freeze rule 2's September baseline and the replay's change facts first; raising the retention setting is an owner choice |
| Lazy views expose mutation bugs that deep copies hid | Views are read-only mappings in production |
| Review notices nag | Once a day across sessions; mention at the end; run only on agreement |
| 0.10.1 slips past 2026-10-31 | Its scope is small and touches neither the loader nor the verifier; a review applied from chat before it lands would be recorded with 0.10's provenance, so the owner's answer is kept verbatim and applied with 0.10.1 |
