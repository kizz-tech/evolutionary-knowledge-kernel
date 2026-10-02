# EKK 0.9.0

Experience without reminders, and entry that shows what is current. This release
implements the [1.0 design](releases/1.0/design.md) components for experience,
current-first knowledge, the agent contract and evidence. Record format
`ekk.record/0.1`, realm identity, acceptance and authority semantics are
unchanged; new record fields are additive.

## Why

Field evidence for September 2026 (two primary hosts, 458 sessions):

- Agents retained an outcome in 40 of 332 sessions that changed files (12%); in
  Claude Code, in none of 66.
- 857 of 3,797 owner messages that followed an agent report matched the frozen
  correction rule, 120 of them with a "said this before" marker. None of them was
  kept anywhere an agent would see it again.
- Entry could return an outdated decision without its successor, and imported
  historical documents, 88% of the larger store, competed with current work.
- Agents read four layers of instructions about EKK, which disagreed with each
  other and with the CLI.

## Changes

- **Host hooks.** `ekk observe --event NAME` handles `SessionStart`,
  `UserPromptSubmit`, `Stop` and `SessionEnd` in Claude Code and Codex. The hook
  imports only the standard library, returns in about 40 ms and cannot fail the
  host: it exits 0 on every error, and the registered command ends in `|| true`.
  It writes one bounded event to a private spool, with credential-shaped strings
  and e-mail addresses removed (`ekk.redaction-rule/2`). The host is read from
  the event itself, not from the environment. Nothing is captured outside a
  project bound to exactly one realm, from a subagent, from a project that opted
  out (`observe: false`), or while observation is off (`ekk observe off`).
  `ekk observe install` registers the hooks beside existing ones and edits a
  linked configuration where it lives.
- **Outcomes from sessions** (`ekk.episode-rule/2`). A background observer closes
  a session's reports when the session ends or has been idle for 20 minutes with
  no turn in progress. The session's report is recorded as one unaccepted outcome
  when the session changed the repository: a new commit, or a new or further
  edited uncommitted file since the session's own earlier state. Beside another
  active session in the same checkout, the change is credited only to a session
  whose report names a changed file or commit. A substantial report without such
  a change is held for the owner. Routine sessions leave nothing. The outcome
  goes through the ordinary durable queue under a deterministic key, carries an
  `experience` annotation with host, session, period and the number of owner
  corrections, and the observer follows it to publication. No transcript is
  stored; report text leaves the observer state once its outcome is published,
  held, or skipped.
- **Corrections and preferences.** A short owner message with a correction cue
  after agent work is kept as a private candidate. It is never published by
  itself. On the review page (`ekk observe review`, then `ekk observe
  apply-review FILE`) the owner keeps it, rewording it on the `record as` line,
  or rejects it. A kept preference is an unaccepted `decision` record with a
  `preference` annotation (`stated_by: owner`) and the owner's own words as its
  source; a later one supersedes an earlier one exactly. In a terminal the owner
  can state one directly (`ekk observe prefer`); inside an agent host the same
  command records what the agent understood as `agent_reported`, which does not
  reach session cards and gets no ranking preference.
- **Session card.** At session start in a bound project the agent receives the
  whole [agent contract](agent-contract.md), the owner-stated preferences in
  force and the titles of the latest results, one bounded line each and marked
  as record data. A project that cannot own a record receives the contract
  variant that says so. The card is rebuilt when a result or preference is
  published; a resumed session is not given it again.
- **Current-first entry.** A record that a current record supersedes gives its
  place and score to its successor, which carries `replaces`; a superseded record
  that must still be shown carries `superseded_by` and brings its successor. An
  unaccepted record cannot take the place of an accepted one: its link is shown
  as `replacement_claimed_by` on the accepted row and it appears only through
  ordinary ranking. Governing records precede all optional reading; one left out
  by the byte budget is a required gap (`governing_left_out`).
- **Ranking priors.** The ranker returns plain BM25. Entry multiplies an
  imported record's relevance by 0.5 (`tier: archive`) and an owner-stated
  preference's by 1.5, and records the plain order beside its own
  (`manifest.ranking.plain_order`). A source whose text equals its record body is
  indexed once.
- **Agent view 0.3.** Each item shows the record's own opening paragraph, the
  reason it was selected, `grounds: N` with up to three `ground_refs`, and
  `tier`, `replaces`, `superseded_by`, `claims_to_replace` where they apply.
  `incomplete` is true only when something required is unresolved;
  `challenges_not_shown` appears only when relations were really cut. `next`
  lists the follow-up commands.
- **Evidence.** Entry in an observed project notes privately what it showed for
  which task (redacted, bounded) and what plain order would have shown; a later
  read by ID marks the item as used. The review page lists the top items of both
  orders mixed, so one marking yields owner-judged precision of each. It also
  lists held results and automatic outcomes for a verdict. `apply-review` reports
  the totals. The field-use study measures retention after changes, corrections
  under the frozen rule and entry use against a frozen September baseline, with
  host labels aligned to the runtime.
- **Advisor in shadow.** `ekk observe advise` runs the configured local model
  (GLiNER2.5-Decide today) in batch over what waits for review and over noted
  entries, stores its labels and reports their agreement with the owner's
  verdicts. Nothing it returns is applied. The adapter contains every malformed
  output and verifies the model identity it loads.
- **Writes.** `--wait` without a key derives the content key, the same one a
  queued write would use. A queued source over the outbox bound names `--wait`.
  The verification checkpoint keeps comparing every operation's runtime journal
  with its Git evidence on every write; a failed full audit drops the checkpoint;
  the background queue worker runs a full audit under its worker lock when the
  last one is older than seven days and, when it fails, marks the waiting
  requests `needs_attention` with the error; `tools/local_install.py warm`
  audits and indexes every store after an installation.

## Compatibility

- `--brief`/`--compact` print `ekk.context-brief/0.3`: `authority`, `budget_note`
  and `read_more` are replaced by `next`; dependency rows become a `grounds`
  count with `ground_refs`; `incomplete` no longer reports optional omissions.
  The full projection gains only additive row fields (`replaces`,
  `superseded_by`, `replacement_claimed_by`, `claims_to_replace`, `tier`,
  `ground_refs`, `discovery.plain_score`), manifest fields (`omitted_governing`,
  `ranking.plain_order`) and a `successor` selection value.
- Entry order changes: governing records first, priors instead of a strict
  archive tier, superseded records replaced by their successors.
- A new private directory `<data home>/observed` holds the spool and observer
  state; `<cache home>/observed/cards` holds session cards. Both can be deleted.
- Hooks are registered with a command that cannot fail the host, so a rollback to
  an earlier runtime leaves them inert. Register them only once 0.9.0 is active.
- The previously installed runtime remains the rollback
  (`tools/local_install.py rollback`). The 0.8 increment (0.8.0–0.8.4) was
  installed locally and is published for the first time with this release; the
  previous public release is 0.7.0.

## Evidence and limits

- Ranking on real entry tasks (known-item recall@8 per target, 794 and 167 tasks):
  0.275 and 0.222 for BM25, against 0.115 and 0.131 for the 0.8 scorer. Weighting
  query terms by their rarity across tasks gave no gain and is not applied. The
  archive prior and the preference boost are unmeasured by the owner; the review
  page's mixed listing is their measurement. On a fresh collection (797 and 168
  tasks) the plain scorer alone gives 0.273 and 0.210, and full entry with the
  priors and the record budget 0.172 and 0.204 on 80 sampled tasks per store;
  the samples differ, so this is not yet a comparison of the two orders.
- The correction rule has about 0.73 precision on its tuning sample, judged by
  one reader who is not the owner; out of sample it is lower. Candidates therefore
  wait for the owner's review and are never applied by themselves.
- The episode rule is a second version. Whether automatic outcomes are worth
  keeping, and whether held results are kept, is measured by the owner's verdicts.
  Uncommitted changes are compared when the observer runs, so a session whose
  events are processed late is credited by commits only.
- Redaction is rule-based and incomplete; an unusual secret can pass into a
  published outcome, which the realm then keeps in its history.
- Hook payloads were verified live for Claude Code session start, prompt and
  session end; the `Stop` payload follows the hosts' documentation and schemas and
  is confirmed by the first recorded sessions. Codex runs a new hook only after
  the owner trusts it.
- The advisor's first smoke run labelled an unrelated candidate "supporting" at
  0.56. It is in shadow so that such errors are counted before anything depends
  on it.
