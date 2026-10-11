# Continuous work in 0.8

Use this page only when continuity or an operation is needed. An ordinary edit
with sufficient context needs no EKK call, reflection or retained record. For a
style change, begin with the component, tokens and style guide in its project.
Look up only the rationale or convention that is missing.

## Find and continue

`ekk enter --cwd PROJECT --task 'outcome' --brief` preserves complete selected
restrictions and lists other selected records briefly: title, date, the passage
where the task's words concentrate, why the record was selected, and an exact
reference. Pinned records and grounds appear as title and ID; grounds of other
items are counted and named by reference. A blocked projection
stays blocked. Required reading is always complete; the 4 kB display target bounds
only the other items. `--compact` prints the same view. Use `fetch --id ID` for an
exact record and `read-source --id ID` for its original asset. A passage is not the
complete evidence.

Entry orders optional reading by BM25 relevance over titles, aliases, bodies and
the readable opening of each text source, ignoring common words. It is lexical: it
does not understand paraphrase or translate between languages. Use `search` for
deep full-text matching across whole sources.

`ekk work find --cwd PROJECT --query 'words I remember'` searches intentions,
titles, aliases, continuation text and readable linked events with partial lexical
matching. Event matches return a current parent work reference, the exact event
reference, an excerpt and a reason. Coverage is bounded; earlier or unavailable
events make it incomplete even when no match is returned. General
`search` keeps its AND matching default; JSON `"match":"ranked"` opts into
partial matching. Search identifies exact source fragments and byte digests;
pagination still requires the original snapshot. Current rights and dependency
closure are checked before any cached source text is considered.

All examples below use the same authorized `--cwd PROJECT` route. Pass a JSON
file with `--json REQUEST`, or `--stdin`. References have exactly `realm`, `id`,
`revision`, `digest`; copy actual returned values. Do not invent them.

| Command | Request fields |
| --- | --- |
| `work start` | `title`, `fields: {intention, direction?, next_step?, aliases?, domain?, questions?}`, `key` |
| `work show` | `reference` |
| `work update` | `reference`, `fields`, `key`, optional `title` |
| `work event` | `reference`, `kind`, `body`, `key`, optional `basis` and `fields` |

Domains are `software`, `research`, `personal`, `general`. Statuses are `open`,
`waiting`, `paused`, `completed`, `cancelled`. Event kinds are `result`, `decision`,
`question`, `scope_change`, `limitation`, `observation`, `next_step`. A decision
event records a statement; it is not governance acceptance. Work updates require
the exact current version. Read and reconsider a stale update; do not force it.
Selected historical work keeps its exact bytes; status and next step are labelled
historical. Navigation separates exact selected and authorized current references;
runnable commands preserve the original owning route, personal inclusion and
effective scopes. A command with `--stdin` also supplies a `stdin` string; pass
those bytes to the command's standard input to preserve the original JSON scope
restriction across shared and personal projections. An ID-only fetch still
means the current version. The latest work view contains up to 64 event references and reports earlier or
unavailable events. Earlier records remain in ordinary canonical history.

Work posture belongs to this intention. External references contain only `owner`
and `locator`; the external tracker remains authoritative for its own state.

## Durable publication

`retain`, `decide` and `capture` already queue their request and return at
once; a decision travels as a retention request with `decision` (the
`ekk.decision/0.1` annotation: `stated_by`, optional `reason` and `revisit`,
`source` with `host`, `session` and `at`), `basis` (exact grounds) and
`aliases`, and the publisher composes the record. For other
durable writes, `queue submit` freezes an exact request locally before
starting a short-lived publisher. No long-running daemon is installed:

```json
{
  "key": "stable-owner-selected-logical-key",
  "operation": "retain",
  "request": {"title": "Useful outcome", "body": "What was actually established"}
}
```

Allowed operations are `retain`, `work.start`, `work.update`, `work.event`, and
`improve.record`. The queue owns the logical key; do not supply a different nested
key. Retention artifacts contain `filename` and either UTF-8 `body` or `base64`.
Use `--no-start` when publication should wait. The receipt explicitly distinguishes
`local_pending`, `publishing`, `retry_pending`, `needs_attention`,
`published_verification_pending`, `read_back`, and `read_back_and_discoverable`.
Local durability is not canonical publication. None of these states is acceptance.

### Declare a result and its required files

`ekk retain --cwd PROJECT --manifest result-manifest.json` assembles an ordinary
request from explicit files, with paths relative to the manifest:

```json
{
  "schema": "ekk.result-manifest/0.1",
  "title": "Investigation and verified continuation",
  "result_file": "result.md",
  "artifacts": [{"path": "evidence.md"}, {"path": "checks.json"}]
}
```

The destination and frozen inventory accompany the existing queue receipt.
Missing, changing or duplicate files and capacity violations fail before enqueue.
There are at most 32 explicit artifacts; the async envelope is bounded to 16 MiB.
`--wait` publishes synchronously, including larger binary sources. The complete
Markdown-record limit is 2 MiB; ordinary result fetch is bounded to 1 MiB, so
larger bodies can remain read-back pending and must not be called complete.

With `--wait`, `declared_package.state: complete` confirms exact body and artifact
read-back. Otherwise inspect the queue and partial or pending inventory. Retry
the frozen request with `queue retry`, or the unchanged manifest and key with
`--wait`. Changed file bytes are a new candidate. No directory scan or automatic
capture of linked papers occurs. This completion view is not another package
store or acceptance lifecycle.

Use `queue status --key KEY`, `queue drain`, or `queue retry --key KEY`. A retry
keeps the frozen bytes and key. The worker re-resolves the route and rechecks current
rights before publication. A crash after publication is reconciled through the
existing publication journal. Work updates retain compare-and-swap; only the
established additive retention path may advance an unpublished base. Attention
states require inspection; a new key is not a recovery workaround.

`queue backup` takes `destination` and makes a consistent private SQLite copy of
local tasks, requests and reconciliation. It requires an explicit full realm owner
route. `queue restore` takes `archive`, `sha256`, `destination`, restores to a new
directory and does not activate it. Inspect it with `queue status --state-dir DIR`
using the same explicit owner route. Draining checks current rights and routes.
Canonical `backup` remains separate. Neither archive registers host schedules.

## Decisions, acceptance and preferences

`ekk decide --cwd PROJECT --title '<decision>' --result-file FILE --stated-by
agent|owner-relayed` records an unaccepted `decision` with `--reason`,
`--revisit`, repeatable `--ground ID` and `--alias NAME`, and `--supersedes ID`
(a decision or an outcome, exactly). `--stated-by` is required: `agent` for the
agent's own decision, which takes no owner words, or `owner-relayed` with
`--owner-words FILE`, the owner's verbatim words, kept as a further exact source
of the decision unless they are the statement itself. The source records the
host and the host session from the host's environment; an owner-relayed
decision needs that session, and `--statement-session ID` only cross-checks it
(`session_identity_missing`, `session_mismatch`). The JSON request takes
`title`, `body`, `reason`, `revisit`, `basis`, `aliases`, `supersedes` (exact
references), `stated_by`, `owner_words` (text) and `statement_session`. The
refusals `stated_by_missing`, `words_missing` and `words_with_agent` name the
corrected command; `words_unreadable` means the option takes a file path.
Acceptance is the owner's separate act: `ekk accept` with
`references`, `expected_snapshot`, `idempotency_key` and an optional
`statement` (`--statement-file JSON`: `by: owner`, `via: review_page |
host_chat | cli`, `at` RFC 3339, optional `host`, `session`, `words`), which the
receipt keeps and the result returns. A missing field is refused by name. This
form infers nothing about who runs the command.

`ekk accept --cwd PROJECT --id ID --words FILE` accepts the current version of a
decision or policy with the owner's verbatim words of acceptance, from a UTF-8
file of at most 600 characters (surrounding whitespace is removed). EKK resolves
the exact reference and snapshot from one view, and builds the statement
`{by: owner, via: host_chat, host, session, at, words}`. The host and the
session are recorded from the host's environment as facts beside the owner's
words, never in their place: `CLAUDE_CODE_SESSION_ID`, then `CLAUDE_SESSION_ID`,
for Claude Code, and `CODEX_THREAD_ID` for Codex. `at` is the runtime's clock.
`--statement-file` or a JSON `statement` replaces `--words` for another channel;
exactly one is given. A chain is accepted by naming every unaccepted member with
repeated `--id`, and predecessors are written first, one receipt each. A record
already accepted at its current version is not written again, and the result
is `already_accepted` with the statement its receipt holds. Refusals are
`invalid_request` with a `refusal` name, the `option` at fault, full
`record_ids` and, where one exists, the `next` command to run:
`words_missing`, `words_unreadable` (the option takes a file path),
`words_too_long`, `session_identity_missing`, `unknown_id` (a unique prefix of
at least 8 characters names the full ID), `not_a_decision`, `superseded_target`
(a successor is not named), `predecessor_blocks` (a replaced record is
unaccepted and not named, or cannot be accepted: `not_acceptable_kind`,
`not_current`, `other_scopes`) and `target_changed` (the record changed while it
was being accepted). A failure after the first write of a chain lists
`accepted_so_far`.

`ekk observe prefer --cwd PROJECT --statement TEXT` records a preference with a
declared origin: `--stated-by agent` (default) or `owner-relayed`, recorded from
the host session in which the owner spoke (`--statement-session ID` only
cross-checks it); its source records the host and session from the host's
environment. `owner` is set only by a review page the owner marked. `--owner-wide`
records it for every project in the owner's personal realm (profile and realm
alias `personal`) with `preference.area: owner:all`; the review page's `[a]` mark
does the same for a kept correction. The session card lists the project's
owner-stated preferences, then the owner-wide ones, then the latest results with
their full record IDs, which `ekk fetch --id` takes as printed. A card over its
size limit drops whole lines from its end. The review page lists corrections and
held results oldest first, says how many it shows of how many, and when the
oldest expires.

`ekk observe apply-review` requires a declaration of how the page was marked:
`--owner-marked-page FILE` (the owner edited the page: owner preferences, and
decisions accepted with their unaccepted chain under `{by: owner, via:
review_page}`) or `--relayed --words REPLY FILE` (an agent marked it from the
owner's reply in a host chat: `owner_relayed` preferences, and the marked
decisions of each project accepted by ID with a host-chat statement of the
reply's first 600 characters, refused per decision when the page leaves an
unaccepted member of its chain unmarked). `--statement-session ID` names the
session in which the owner spoke when it is not the one the page is applied in.
Each application is recorded in the observer with the declaration, the host,
profile and session, the sha256 and length of the whole reply, and the labels
it set; the result returns the same, never the reply, plus `skipped` marks
whose item changed state after the page was written. An owner-marked page
applied from inside a host session contradicts its declaration and is listed
for the owner in `ekk observe status`. Without a declaration nothing is applied.

## Author notes, tasks and waiting

`source add` takes `alias` and an explicitly selected existing `root` folder. It
does not import or change notes. `source search --query TEXT`, `source fetch`
(`reference`, optional character `offset` and `limit`), `source list` and
`source remove` work only in the configured scopes. Search covers Markdown, text,
Org and reStructuredText; it reports bounded or unavailable coverage. Symlink
paths are refused. Fetch checks the exact digest, so an author's edit requires
selecting the new version. Historical sources are not migrated by this feature.

`task create` takes `key`, `title`, optional exact `work` reference and optional
`external: {owner, locator}`. `task list`/`show` read local follow-ups; `task update`
takes `id`, current `revision`, `key`, and `title` or `status`. Local status is
`open`, `waiting`, `completed`, or `cancelled`; it does not mirror a tracker.

`task wait` takes `id`, `revision`, `key` and `until` with timezone or `condition`.
Its registration starts as `not_registered`. When the user requests a reminder or
later continuation, the agent uses its host's existing automation tool in the same
task (a Codex automation or a Claude Code scheduled task), then records the actual
returned receipt through `task register-wait` with `host_receipt: {host,
automation_id, receipt}`, where `host` is `codex` or `claude-code`. This is a
recorded host receipt, not an independent verification that the schedule remains
active. Update or cancel the automation through its host. A written date never
creates one.

Before an authorized external action with uncertain delivery, `external-attempt`
records `operation_key` and starts as `unknown`. `external-outcome` requires that
same key, an `outcome` (`confirmed`, `not_performed`, `unknown`) and observed
`evidence`. A new attempt is refused until an unknown outcome is reconciled.
These records do not perform or authorize the external action.

## Practical methods and improvement

`guide show --domain software|research|personal` gives optional inputs, useful
tools, intermediate outcomes and stopping conditions. The guide does not impose
a pipeline. `guide package` returns the exact artifact and method specification
for the existing `method propose/evaluate/admit/use/reconsider/retire` lifecycle.
These registered adapters are read-only planning aids. Contract evaluation does
not establish their usefulness, and no method is automatically admitted.

`guide list` lists independent phases. Add
`--phase research|design|planning|implementation` to `guide show` for optional
decision, output, evidence and stopping guidance within any existing domain.
Research checks earlier findings and changed conditions; design keeps the needed
capability and actual place of use; planning starts from confirmed state and
current constraints; implementation checks the requested flow through its real
entry point. Use relevant phases only. Existing method package bytes and
identities are unchanged; a phase does not admit a method.

When prior experience changes a decision, describe that decision, exact grounds
and actual outcome in the ordinary result. Significant new evidence can use
existing `retain`, `work event` or `improve record`; no per-phase record is required.

Successful `fetch` and `read-source` calls leave private exact opening receipts.
Linkage requires one exact compatible delivery with the same observed host,
profile, session and workspace. Unknown identity or ambiguous delivery stays
unlinked. `observe status` reports linkage counts. Legacy ID/time-window `used`
marks retain their old semantics; opening is not application or observed benefit.

For a significant actual episode, `improve record` takes the current work
`reference`, `key`, optional exact `basis`, and an `observation` object:

```json
{
  "episode": "Locator of the selected actual task or feedback",
  "source": "user_feedback",
  "observation": "Concrete friction or improvement observed",
  "stage": "used",
  "target": {"kind": "component", "owner": "owning project", "locator": "component path"},
  "change": "Proposed or observed change to that artifact",
  "disposition": "candidate"
}
```

Sources are `user_feedback`, `task_log`, `observed_runtime`. Stages distinguish
`retrieved`, `delivered`, `used`, `helpful`, `unhelpful`, `unknown`. Targets can be
components, tools, checks, methods, instructions, knowledge or `process_removal`.
Dispositions are `candidate`, `implemented`, `retired`, `rejected`. These are
attributed observations, not measured causal effects. Verification stays with the
artifact owner; method admission remains separate. Record selected evidence and
useful changes, not transcripts or compulsory reflections after every task.
