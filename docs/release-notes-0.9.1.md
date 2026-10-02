# EKK 0.9.1

The owner's word as the only input of authority, documents as projections of the
realm, and experience capture that does not depend on when the observer runs.
Record format `ekk.record/0.1`, realm identity and acceptance semantics are
unchanged; new record and receipt fields are additive.

## Why

0.9.0 made acceptance the owner's separate act, but the act was a terminal
command the owner never ran: two records accepted in September, nothing since,
while twenty-one delegated decisions lived in a Markdown table that entry could
not select. The governing layer was a decoration. At the same time the only way
to record a decision was a raw proposal, and the session card knew nothing about
preferences that hold for every project.

## Changes

- **`ekk decide`.** A decision with its reason is recorded as an unaccepted
  `decision` record through the ordinary durable queue (`--title`,
  `--result-file`, `--reason`, `--revisit`, `--supersedes ID`, `--ground ID`,
  `--alias`). The record carries who stated it (`decision.stated_by`: `owner_relayed`
  when an agent relays the owner's words from a named session, else `agent`) and
  a canonical body shape that the projection reads. The agent contract names it.
- **Acceptance carries the owner's statement.** `ekk accept` takes a `statement`
  (`by: owner`, `via: review_page | host_chat | cli`, host, session, time, words)
  that is validated, stored in the acceptance receipt and returned. Nothing about
  who ran the command is inferred; the receipt says only what the statement says.
- **Acceptance from the review page.** The weekly page lists the decisions
  agents proposed; `[x]` accepts a record as governing with a `review_page`
  statement and the current snapshot as the expected base.
- **Provenance vocabulary.** A preference is stated by `owner` (review page),
  `owner_relayed` (an agent on the owner's words, from a named session) or
  `agent`; a decision by `owner_relayed` or `agent`, and the owner's word on a
  decision is the acceptance statement. The terminal heuristic of 0.9.0 is gone:
  `ekk observe prefer` takes `--stated-by` and `--statement-session`, and nothing
  is inferred from the environment.
- **The final report is the outcome.** A session's outcome is its final report,
  which gives the title; earlier reports follow in order as its history. 0.9.0
  chose the longest report, so a detailed wrong turn could outrank a short later
  correction.
- **The session card selects as entry does.** The card is built from
  `RealmService.card_view`: readable records of the bound contexts (the record
  and its dependency closure inside them), minus those replaced by an exact
  successor of equal standing. 0.9.0 listed records by scope intersection and
  treated any `supersedes` link as a replacement.
- **Owner-wide preferences.** A preference can be kept for every project
  (`[a]` on the review page, or `ekk observe prefer --owner-wide`); it lives in
  the owner's personal realm with `area: owner:all` and appears on every session card
  under "Owner-wide preferences". Entry weighs owner and owner-relayed
  preferences alike.
- **`ekk project decisions`.** The decision records of a realm are rendered as the
  Markdown table a release package carries; `docs/releases/1.0/decisions.md` is
  now that projection, with each row's state (accepted, proposed, superseded by).
  The records are the home; the document is read-only output.
- **Late events are counted, not hidden.** Taking uncommitted-file signatures
  in the hook was measured and rejected: `git status` on a 2,500-file checkout
  takes 237–283 ms under the owner's usual load, more than the hook's whole
  budget. The observer keeps taking them; an event it processes more than five
  minutes late credits its session by commits only and is counted
  (`events_state_unknown` in `ekk observe status`).
- **Hourly observer run.** `ekk observe install --host launchd` registers a user
  launch agent that runs `ekk observe drain --background` every hour, so a
  session without a `SessionEnd` closes within the hour instead of at the next
  host event; `uninstall` removes it.
- **EKK on itself.** In the development realm of EKK (not part of this
  repository) the 1.0 target design, its twenty-one delegated decisions, the
  five decisions of this release and a revised D-1.0-12 are records; the target
  is a proposed decision that claims to replace the 0.5 direction and waits for
  the owner's acceptance, so 0.5 stays in force until then. The adversarial
  review that shaped 0.9.0 is a record with the eight lens files as sources. The
  generated `docs/releases/1.0/decisions.md` is the public summary of those
  records.

## Compatibility

- New CLI operations `decide` and `project`; new `accept` field `statement` and
  receipt field of the same name.
- `ekk observe prefer --reported-by-agent` is removed; use `--stated-by
  owner-relayed --statement-session ID` or `--stated-by agent` (the default). A
  preference recorded from a terminal is now the agent's own reading (`agent`),
  not `owner`; only the review page records `owner`. Existing 0.9.0 records with
  `stated_by: agent_reported` stay readable and are treated as `agent`.
- `--owner-wide` needs a profile and a realm alias named `personal` in the local
  registry; without them the command reports the missing configuration.
- Observed events are unchanged; `ekk observe status` gains the
  `events_state_unknown` count.
- The launch agent is optional; hooks are unchanged.

## Evidence and limits

- The decision and acceptance paths are verified by focused tests and by the
  records of this repository's own realm; whether proposed decisions are accepted
  more often than before is measured on the review page.
- A statement is provenance, not authentication: every process of the OS user
  can write and accept. The receipt records what was said and where.
- The journal concurrency test tolerates a loaded machine by retrying the
  bounded lock wait; its claim (no attempt is lost) is unchanged.
