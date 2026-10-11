# Implementation decisions

Date: 2026-10-10. These decisions settle the points where the slices of the
[plan](tasks.md) touch the same code or where the [0.11 design](../0.11/design.md)
leaves a choice open. Where a slice description disagrees, this file wins. Order of
work: U01, U02, U05, U04, U03, U07, then the U06 gate.

## Compatibility constraints

These hold for every slice:

- The rollback target is 0.10.0, and the private gateway still embeds 0.8.0. Both
  share the operation journal and the observer database.
- Legacy journal rows (`ekk.operation-attempt/0.1`) gain no key and no error code.
  The 0.10.0 and 0.8.0 readers count such a row as damage and then stop
  journaling.
- The spool schema stays `ekk.observed-event/0.2`, and new keys are optional.
  0.10.0 deletes spool files whose schema it does not know.
- These stay unchanged, so the loader fingerprint and the store verifier do too:
  - `ekk/model`, `adapters/markdown.py`, the schemas, `git_store.py` and
    `contained_store.py`;
  - the bodies of `RealmService._load`, `_roots` and `_record_versions`.
- Receipts, records, the decision source `{host, session, at}`, the closed
  acceptance statement keys and the contract text do not change.

## Requests and errors

1. **One error type.** `RequestError(ValueError)` lives in the new
   `ekk/application/errors.py`, outside every fingerprint input. Its optional
   attributes are:
   - `refusal`: a stable name;
   - `option`: the option or field at fault;
   - `record_ids`: full IDs;
   - `next`: the exact command to run instead.

   Adapters raise it for option checks; the application raises it for values the
   caller passed. `error_code` returns `invalid_request` for it before any
   message heuristic.
2. **Which sites change.** Only sites that return `invalid_format` today are
   converted, and a test pins each converted site:
   - the request checks in `command_line.py`;
   - JSON input errors;
   - the three activity input checks;
   - in the service, the budget, the byte limit and "record exceeds byte limit".

   Record, store and model validation keep `invalid_format`, and so do the
   retention read-back and `search_records`.
3. **The error document.** It is `{error, message, refusal?, option?,
   record_ids?, next?}` plus the existing lock fields, wrapped unchanged in the
   result envelope. The exit code stays 2.
4. **Journal mapping.** The legacy journal records a request error as
   `invalid_format` with failure stage `request`. This applies to the failure
   finish and to the retention-pending path. `ERROR_CODES` does not grow; the new
   code enters the journal with journal v2 in 0.11. This narrows design E's
   "(0.10.1) journal".
5. **Unknown IDs.** Lookup stays exact for fetch, read-source, decide
   `--supersedes` and `--ground`, prefer `--supersedes` and accept `--id`. On a
   miss the refusal is `unknown_id`:
   - The prefix help considers only values of 8 or more characters, and only
     records a read from the selected contexts may return: the record and its
     dependency closure lie within them, as for every query.
   - Exactly one candidate: the refusal names its full ID. The `next` command is
     the caller's own command line with only that value replaced.
   - Several candidates: the refusal gives their count, without IDs.
   - Nothing is ever resolved automatically.

## Host identity

6. **One resolver.** It lives in `adapters/host_identity.py` and serves the hook,
   the CLI and the journal.
   - **Host.**
     - The hook uses the payload first: transcript path, then turn ID.
     - Otherwise `CODEX_HOME` gives `codex`; otherwise exactly one registry
       `environments` match gives the host, `claude-code` by `CLAUDECODE=1`;
       otherwise `unknown`.

     This is the journal's existing order. A Codex process started from Claude
     Code inherits `CLAUDECODE`, so with both markers the host is `codex`.
   - **Session.**
     - The hook payload's `session_id` comes first.
     - Otherwise the host's declared variables are read: `CODEX_THREAD_ID` for
       Codex; `CLAUDE_CODE_SESSION_ID`, then `CLAUDE_SESSION_ID`, for Claude
       Code.
     - Defaults live in code. An optional additive `sessions:` map in the caller
       registry overrides them. A malformed override gives that host no session
       and never raises.
     - The value is at most 256 characters.
     - `CLAUDE_CODE_HOST_SESSION_ID` and `CLAUDE_CODE_CHILD_SESSION` are never
       read. The child marker is set in top-level desktop sessions too.
   - **Profile.** It is the fleet registry key, matched by resolved Codex home,
     or none when the home is not registered. It is never a directory name.
     Claude Code has no profile.
   - **The hook stays standard-library only.** It spools the raw `codex_home`,
     and the observer normalizes it at ingest.
7. **Sessions are optional.** Every path records the session when it is known.
   Only host-chat statements need one (decision 12).
8. **Scrubbed variables.** `host_identity.SCRUB_VARIABLES` lists the markers,
   the session variables, `CLAUDE_CODE_HOST_SESSION_ID` and
   `CLAUDE_CODE_CHILD_SESSION`. Three places remove them:
   - the test runner's child environment;
   - every test that filters the environment;
   - the observer drain started by the hook.

   The CLI's queue worker keeps the caller's environment, because it publishes
   the caller's own write.

## Observer state

9. **One migration step.** `SCHEMA_VERSION = 1` carries every column the slices
   need. All are nullable, and NULL means unstamped, which is 0.10.0 or earlier.

   | Table | Added |
   | --- | --- |
   | events | `runtime`, `transcript_path`, `expired_from`, `expired_at` |
   | episodes | `profile`, `runtime`, `rule`, `shadow`, `expired_from`, `expired_at`; index on `(state, last_at)` |
   | `episode_keys` (new) | `key`: the ledger of counted episode keys |
   | deliveries | `runtime`, `labels_application` |
   | readings, advice | `runtime` |
   | labels | `runtime`, `application` |
   | `review_applications` (new) | `id`, `at`, `page`, `page_sha256`, `declared`, `words`, `words_sha256`, `words_chars`, `host`, `profile`, `session`, `statement_session`, `contradicts`, `counts`, `runtime` |

   How the step runs:
   - It is presence-checked under `BEGIN IMMEDIATE`, and the lock is skipped when
     everything is present.
   - The version is never lowered, and a writer accepts a newer one.
   - `episodes.rule` is backfilled from the stored request when the column is
     added.
   - The ledger `episode_keys` is seeded from the present episode keys in the
     transaction that creates it, and never again. A database already at
     version 1 without it gets it through the same presence check. 0.10.0 never
     touches it.
   - `runtime` is `ekk.__version__`. For events it is the version of the
     capturing hook, taken from the spool.
10. **Upserts.**
    - `save_episode`, `label` and `note_advice` become upserts over named
      fields.
    - A new episode key enters the ledger and is counted as `episodes_created`
      in the transaction that writes the row.
    - The statements of 0.10.0 still work against the migrated schema. A frozen
      copy of the 0.10.0 store module, kept under `tests/fixtures/`, tests
      this.
11. **The read-only accessor.** `open_read_only(strict=True)` opens the file
    read-only and creates nothing. A missing file gives "no observer state".
    - Strict mode refuses a newer schema.
    - Tolerant mode, used by the installer's rollback guard, reports the
      version and any unknown columns.
    - `observe status` keeps the writable store.
    - Field use loses `seed-task-terms` and holds no writer.

## Statements and declarations

12. **One statement builder.** A pure function in `application/experience.py`
    builds the host-chat statement from the closed keys. It handles more than
    600 characters of words in one of two ways:
    - accept refuses them (`words_too_long`);
    - apply-review keeps the first 600 characters, and the observer keeps the
      sha256 of the full bytes.

    Unknown host or session values are omitted, and `at` is the runtime's clock.

    `--statement-session` always names the session where the owner spoke, and
    the resolver's session is a recorded fact.
    - A receipt or a decision source has room for one session. `accept --words`
      therefore takes the resolver's session only, and `decide` refuses a
      declared session that differs from it.
    - The observer has room for both. `apply-review --relayed` therefore
      accepts a different declared session for the statement and keeps the
      resolver's session in `review_applications.session`. An answer relayed in
      a later session then still names the session where the owner spoke.

    A host-chat statement without any session is refused as
    `session_identity_missing`.
13. **The JSON accept form.** `--statement-file` and JSON statements are
    unchanged, `host_chat` included. Two issues are listed for 0.11:
    - this path can overwrite the receipt of an already accepted record;
    - this path can accept a superseded decision.
14. **Accepting by ID.** `accept --id ID [--id ID …] --words FILE` calls the
    public
    `RealmService.accept_current(scopes, record_ids, *, statement,
    idempotency_key=None, option='--id')`. Refusals name `option`, so a review
    page's refusals point at its marks.
    - **Refusals:**
      - `words_missing`, `words_unreadable` (the option takes a file path) and
        `words_too_long`;
      - `session_identity_missing`;
      - `unknown_id` and `not_a_decision`;
      - `superseded_target`, `predecessor_blocks` and `target_changed`.
    - **Already accepted:** the call returns `already_accepted` and writes
      nothing.
    - **Chains:** a chain is accepted by naming every unaccepted member, and
      predecessors are written first.
15. **Declaring how a review was applied.** `apply-review` requires
    `--relayed --words FILE` or `--owner-marked-page`.
    - **Relayed.** Kept corrections become `owner_relayed` preferences. Marked
      decisions are accepted through `accept_current`, one call per group of
      marked decisions that `supersedes` links within a workspace. The owner's
      words are therefore never copied onto a record the page did not mark, and
      one blocked chain does not hold back an unrelated decision.
    - **Owner-marked.** The page keeps the 0.10.0 chain behaviour until 0.11.
      It is flagged as contradicting when a host session is present.
16. **Declaring who stated a decision.** `decide` requires `--stated-by`:
    - `owner-relayed` requires `--owner-words FILE`. The words become an extra
      exact source of the decision.
    - `agent` refuses owner words.

    The CLI flags are checked at the option gate. The JSON fields are checked
    after request normalization, and both happen before routing.
    `observe prefer` keeps its `agent` default and takes its host and session
    from the resolver.

## Expiry and the review page

17. **Expiry.** It follows the slice map's retention table `ekk.observer-expiry/1`:
    - Held and composed results become `expired_unreviewed` tombstones at 60
      days.
    - Pending corrections and those in review dialogue become tombstones at 90
      days.
    - Other text is cleared per state.
    - Rows are deleted 365 days after their last activity.
    - Every transition and deletion is counted in the same transaction, and a
      deleted episode's key leaves the ledger in it.

    How it runs:
    - Episode and correction expiry runs only in `Observer.run`.
    - The agent's path prunes deliveries, readings and seen terms inside a
      savepoint, with counts.
    - Labelled deliveries are kept until 365 days.
    - Composed episodes are retried from the episode row.
    - A mark that arrives after its item expired is counted as
      `expired_before_apply` and listed as an error.

    `observe status` keeps the schema `ekk.observer-status/0.2` and adds an
    `expiry` block. Its `next_expiry` covers material the owner has not judged,
    and `next_text_clearing` is separate. Two values come from the ledger, and
    both are None without it:
    - `episodes_deleted_uncounted`: ledger keys absent from `episodes`. It is 0
      unless a runtime deleted episodes without counting, and a nonzero value
      is listed for the owner's attention.
    - `episodes_created_uncounted`: episode keys absent from the ledger, which
      a runtime created without counting. It is informational.
18. **The review page.**
    - Held results are listed by last activity and corrections by time, oldest
      first.
    - The caps stay at 10 and 30.
    - Each section states how many it shows of how many, and when the oldest
      expires, taken from the same expiry function.
    - The card and the decision lines print full IDs, and the card is cut at
      whole lines.
    - Page markers do not change, so pages written by either runtime apply
      under the other. A frozen copy of 0.10.0's page parser, kept under
      `tests/fixtures/`, tests this.

## Host facade and delivery

19. **The host facade.** `ekk/host_api.py`, version `ekk.host-api/1`, exposes:
    - a dispatch for the read operations only: enter, context, contexts,
      search, fetch, read-source, doctor, review and assurance;
    - capture once and retain once;
    - an observed call with a declared caller;
    - the error code and the record schema;
    - `active_release()` and `loaded_release()`.

    Writes return later as an additive version. `homes.release_home()` is the
    one definition of the release directory, used by the facade and by the
    installer.
20. **Rollback guard.** `tools/local_install.py rollback` and `activate` read
    the target's version from its release record. Switching to a runtime without
    explicit expiry is refused unless `--accept-observer-loss` is given, while
    the observer holds any of these:
    - an episode older than 30 days;
    - a correction older than 90 days;
    - an owner-labelled delivery older than 60 days, or outside the newest
      2,000 deliveries of all rows, which is 0.10.0's own predicate.

    The guard covers every retention that 0.10.1 extends beyond 0.10.0, with one
    displacement it does not count: while labelled deliveries are among the
    newest 2,000, 0.10.0's shared cap drops as many younger unlabelled ones,
    which the owner has not judged. An accepted loss reports each count.
    This is the installer's own guard against data loss. Connectors still never
    refuse an activation.
21. **Correction rule 2.** It ships in the same build, unused by the runtime:
    the hook keeps rule 1.
22. **Public export.** The reference export lists every new runtime module, every
    new test module and the frozen 0.10.0 fixtures under `tests/fixtures/`. The
    runtime modules are `application/errors.py`, `adapters/host_identity.py`,
    `host_api.py` and `adapters/runtime_release.py`.

## Departures from the accepted documents

| Decision | Departure |
| --- | --- |
| 4 | Narrows design E: in 0.10.1 `invalid_request` reaches the agent, while the legacy journal records it as `invalid_format` at stage `request`. |
| 13 | Leaves the JSON accept path as in 0.10.0. |
| 19 | Narrows S13 to read operations plus capture and retain. |
| 21 | Ships correction rule 2 as unused code, although the spec excludes it from the runtime. |

The spec's exclusions and the design's affected sections point here.
