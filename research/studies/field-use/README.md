# Field use: EKK in actual work

**Question.** In ordinary work on this machine, how often do agents use EKK, what
does it cost them, what does entry deliver, and does retained material come back
in later sessions?

This study observes real work. It reads the host transcripts that already exist
(Codex sessions, Claude Code projects) and the private EKK operation journal,
extracts every `ekk` command an agent ran, including archived Codex sessions, and
reports:

| Area | Measures |
| --- | --- |
| Adoption | Sessions with EKK by host, bound project, week and agent model; entry calls from subagents |
| Cost | Operation latency by EKK runtime version; outcomes and error classes; journal operations by registered caller (a Codex profile, `claude-code`, the gateway or `unknown`); entry output size by display mode |
| Retrieval behaviour | Share of each entry result occupied by items that appear for at least 30% of distinct tasks; items delivered without content; follow-up reads after entry |
| Reuse | Records retained in one session that resurface in a later session's reads, and the successful writes whose record ID no transcript shows (`writes_without_record_id`) |
| Retention after changes | Per host and bound project: sessions with changes (a completed file change or a successful `git commit`), sessions where the agent's `retain`, `capture` or `queue submit` returned a published or queued receipt, the share of changed sessions with such a receipt, sessions whose only attempts were unconfirmed, and, when the integrator supplies them, sessions with an outcome EKK recorded itself from a host event |
| Owner corrections | Per host, bound project and ISO week under the frozen rule `ekk.correction-rule/1` (`src/ekk/observation.py`): owner messages, owner messages that follow at least one agent report in the session (the denominator), corrections and repeated corrections. Counts only |
| Entry use | Per host: record IDs delivered by each `enter` (title-only pinned or required items included) and the ones with a later sign of use: a `fetch` or `read-source --id` of the record, or its ID (or first 8 characters) or normalized title (16 characters or more) in a later final report of the session |
| Ranking benchmark | Known-item recall (the task of a session against the records that session retained), always-on share and query time for the 0.8 scorer, the current scorer and the current scorer with task-term query weights fitted on the same tasks; optional end-to-end entry on sampled tasks, as the runtime builds it |

## Running

```sh
.venv/bin/python research/studies/field-use/field_use.py run --since 2026-09-07
.venv/bin/python research/studies/field-use/field_use.py bench --out <run directory> --pipeline 30
```

`--since` and `--until` select records by their own UTC timestamp, so a thread
that runs across the boundary contributes only its records inside the period.

`bench --pipeline N` runs entry through the application exactly as the CLI
builds it; the row records `query_weights_applied`. The runtime measures
task-term query weights but does not apply them, so the weighted condition is a
separate row, `pipeline_task_weighted`, written only with
`--pipeline-task-weighted`: a fresh application with weights fitted on the
project's tasks outside the evaluated sample. When fewer than 30 such tasks
exist the weights are inactive and the row says `skipped` instead of repeating
the unweighted run. The `task-weighted` scorer row is fitted on the evaluated
tasks themselves and says so.

How transcripts are read:

- An `ekk` call counts only in command position of the shell command
  (Codex `CommandExecution`, Claude Code `Bash`). The word inside a quoted `rg`
  or `pgrep` pattern, a heredoc body or prose is a mention. `python -m ekk`,
  the form used for development builds, is not counted.
- Retention is judged by the receipt in the output, not the exit code:
  `published` needs `read_back_and_discoverable`; `queued` is a durable local
  request or a publication not yet verified; `failed` is an error receipt, a
  traceback or an interrupted process; `unknown` is everything else, mostly
  output redirected to a file.
- The records a write created are read from its receipt only: the
  `result_reference` and `source_references` of a published receipt, or, for a
  queued receipt, of a `queue status` or `queue drain` receipt that shows the
  same key (in any session). Other UUIDs in the output, such as the realm, are
  not created records. A successful write whose record ID never appears is
  counted in `writes_without_record_id` and forms no reuse or benchmark pair.
- A Codex session is a thread: every rollout segment and subagent file with the
  same `session_id`. A Claude Code session is its transcript plus its subagent
  transcripts. Records replayed after a resume or compaction are counted once,
  by `uuid`, in the oldest file.
- Owner messages come only from the owner's own turns, after
  `ekk.observation.owner_text` removes host wrappers; subagent prompts,
  automation threads, task notifications and compaction summaries are excluded.

Freeze the correction counts of a fixed period, so that later comparisons use
unchanged numbers under the same rule version:

```sh
field_use.py run --since 2026-09-01 --until 2026-10-02 --out RUN
field_use.py baseline --since 2026-09-01 --until 2026-09-30 --out RUN   # RUN/corrections-baseline.json
```

`baseline` refuses to overwrite an existing file, a period the run does not
cover and a period that was still open at collection: `--until` must be before
the UTC day on which the run was collected. The run and the baseline record a
digest of the rule content (the cue patterns and bounds of
`src/ekk/observation.py` and the collector's version of what counts as an owner
message after a report). `baseline` refuses a run collected under other rule
content even when the rule name is the same, and `report` then labels the counts
with the rule recorded in the run and states that they are not comparable. A
test pins the digest of the current rule, so editing the rule without a new
version fails.

Transcripts cannot show the stores, so outcomes that EKK records itself are
merged by the integrator: `report --host-events FILE` takes a JSON list of
`{"host", "session"}` copied from outcome records whose metadata has
`experience.acquisition == "host_event"` (`merge_host_events` in the module).
`host` is the runtime's label as stored in `experience.host`: `claude-code`
(the study's `claude`) or `codex`; `session` is the Codex `session_id` or the
Claude Code session ID. A pair with host `unknown` matches by session ID when
exactly one session has it. The report gives the distinct pairs that matched a
session and, as `host_event_pairs_unmatched`, the ones that matched none.

Two commands compare runtimes on a private list of real requests, a JSON list of
`{"label", "argv"}` where `argv` is what follows `ekk` on the command line. Each
request runs in a fresh process through the CLI path with diagnostics not
journaled and observation switched off (`EKK_OBSERVE=0` in the child), so
measurement leaves no rows in the owner's journal and no deliveries, use marks
or task observations in the observer state. The requests themselves still run
against the owner's stores, so the list should hold reads only:

```sh
# Cold-process latency, runtimes interleaved so that machine load affects each alike
field_use.py latency --requests REQUESTS --python OLD --python NEW --runs 5
# Equivalence gate: identical output after normalizing assembly timestamps
field_use.py compare --requests REQUESTS --python OLD --python NEW --store STORE_CHECKOUT
```

Output goes to a private directory outside the repository, by default
`<EKK data home>/../evaluation/field-use/<UTC timestamp>/`, with owner-only file
modes. `episodes.jsonl` holds task text and record titles from private work; do
not publish it or copy it into the repository. `messages.jsonl` holds one row
per owner message with its time and rule flags and no text; reports and the
baseline hold counts only. Reports are aggregates for the
owner. Publishing any figure requires its own review.

## Evidence limits

- Observation, not a controlled comparison. Agent models, task mix, instructions
  and EKK versions change together; the report stratifies by model and runtime
  version but cannot remove confounding.
- A delivered item is not evidence that it was read, used or helpful. Reuse counts
  identifiers that reappear in later read output, for records whose ID a receipt
  in a transcript shows. Retention is queued by default, so most writes show
  only a key; unless a later `queue status` appears, they are in
  `writes_without_record_id` and outside reuse and the benchmark. Outcomes
  recorded from host events never appear in transcripts. A low reuse count
  next to a high unresolved count says nothing about whether material returns. The entry-use signal is a lower
  bound on visible use: it misses an item that shaped the work without being
  fetched or named, and it counts a title that a report repeats by coincidence.
  Entry output cut by `head` contributes the IDs that were shown, without titles.
- The correction rule is a list of cues applied to short owner messages. One
  judge who is not the owner labelled the tuning sample: precision is about 0.73
  there and lower out of sample, and recall is not measured. Read the counts as a
  trend under one rule version, never as a number of real corrections; a rule
  change is a new version and needs a new baseline. A message in a resumed
  Claude Code session counts as following a report only when that report is in
  the same session.
- Retention seen in transcripts is a lower bound: a receipt redirected to a file
  is `unknown`, and the report shows such sessions separately. A queued receipt
  shows a durable request, not a completed publication. Sessions with changes
  include trivial edits, so the share is not a share of tasks worth retaining.
- A subagent's changes and calls belong to its parent session, and a session is
  assigned to the project of its first working directory.
- Transcript parsing is heuristic. Hosts without local logs, such as a remote
  gateway client, are absent; the operation journal covers them only as anonymous
  operation timings.
- The known-item benchmark favours lexical methods because one agent wrote both
  the task and the retained record. It detects regressions and gross failures,
  such as the same records appearing for unrelated tasks; it does not certify
  relevance as judged by the owner. Owner judgments on a sample remain the
  reference.
- Changing the advisor model or the agent model is a new condition. Compare runs
  with the same task set and record the model identity of each run.

`test_field_use.py` checks the collector and report on synthetic host logs.
