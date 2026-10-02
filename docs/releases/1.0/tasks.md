# Tasks

Slice states: `done`, `in_progress`, `proposed`. Proposed slices become planned
only after the owner selects the scope ([status](status.md)).

| ID | Slice | State | Evidence / depends on |
| --- | --- | --- | --- |
| S01 | Field-use study: collector, report and ranking benchmark on synthetic fixtures; baseline run on real logs | done | `research/studies/field-use`; private baseline output |
| S02 | Entry relevance: BM25 over title, aliases, body and source openings; stop words; relative candidate floor; selection reasons | done | Focused tests in `tests/test_context_continuity.py`; benchmark against the 0.8 scorer |
| S03 | Compact agent view `ekk.context-brief/0.2` for `--brief`/`--compact`; incompleteness reasons | done | `tests/test_context_display.py`, `tests/test_architecture_cli.py` |
| S04 | Asynchronous retention by default, `--wait`, derived logical key; `fetch`/`read-source --id`; tolerant display flags | done | `tests/test_architecture_cli.py`, `tests/test_lock_contention.py` |
| S05 | Install 0.8.1 locally with a recorded rollback; propose the matching skill text | done | Release manifest; candidate proof before activation; skill text applied 2026-10-01 |
| S06 | Primary outcome: detection rules for repeated corrections and rework in transcripts, frozen before comparison | done (0.9.0) | `ekk.correction-rule/1` in `src/ekk/observation.py`; September baseline frozen (private output) |
| S07 | Owner sample: a lightweight labelling format and periodic sample of entry results | done (0.9.0) | `ekk observe review` / `apply-review`; both orders mixed on one page (D-1.0-19); `tests/test_experience.py` |
| S08 | Entry latency: read immutable Git facts once per process, index past commits across processes, read single files instead of snapshots; field p50 ≤ 3 s | done (0.8.3) | Equivalence gate and interleaved latency in `research/studies/field-use`; `tests/test_architecture_store.py`, `tests/test_workspace_entry.py` |
| S09 | Host event channel for capture and recall (0.9 T01) in Codex and Claude Code | done (0.9.0) | `ekk observe --event`, `ekk observe install`; Claude Code payloads verified live for start, prompt and end; `tests/test_experience.py` |
| S10 | Retention without reminders and capture of owner corrections with grounds and area | done (0.9.0) | Episode rule 2 (D-1.0-11, D-1.0-18), correction candidates on the review page; `tests/test_experience.py` |
| S11 | Recall at entry and at a change of focus | partly (0.9.0) | Session card at entry (D-1.0-14); change of focus deferred |
| S12 | Delegated context handoff and repeated-entry cache for subagents | deferred | D-1.0-16 |
| S13 | Host parity: Claude Code and gateway clients; project binding; one install/connect/update/disconnect path | proposed | S17 covers Claude Code attribution and automation receipts |
| S14 | Advisor shadow: GLiNER2.5-Decide adapter behind the semantic-advice port; comparison with BM25 on real tasks and owner samples | partly (0.9.0) | `ProcessAdvisor`, `ekk observe advise` with an agreement report; the comparison waits for owner labels |
| S15 | Decisions and preferences home with revision history | done (0.9.0) | Preferences as superseding records with labelled provenance (D-1.0-12); supersession preserves standing (D-1.0-21) |
| S16 | Export hygiene: review new modules and tests for the allowlist; stale version text; release links | proposed | — |
| S17 | Claude Code parity (0.8.2): caller attribution by registered environment markers, automation receipts from `codex` or `claude-code`, host-neutral skill and handbook, journal operations by caller in field use | done | `tests/test_operation_diagnostics.py`, `tests/test_continuous_work.py`, field-use tests |
| S18 | Test and release workspace: isolated parallel runner with exact known failures and an owner-journal sentinel; local build, activation and rollback from a commit | done | `tools/run_tests.py`, `tools/local_install.py`; rollback drilled 0.8.3 → 0.8.2 → 0.8.3; splitting `test_architecture_application` per class would cut a full run to about 6 minutes |
| S19 | Entry on large stores: read source assets only when needed and keep the ranking index across processes | proposed | S08 |
| S20 | Write latency: avoid re-verifying every past operation in each new writer process, without weakening recovery checks | done (0.8.4, hardened 0.9.0) | Verification checkpoint with journal-evidence comparison on every write, weekly full audit from the worker, `local_install.py warm`; `tests/test_architecture_store.py`, `tests/test_recovery_history.py` |
| S21 | Cache hardening before a long-running host adopts 0.8.3: include the store adapters' tree validation in the history-index fingerprint; make `doctor` and backup read through the durable-state path that recovery uses | partly (0.9.0) | Loader fingerprint narrowed to what decides a historical load; recovery bypasses memos |
| S22 | Entry selection integrity: governing first, standing-preserving supersession, priors recorded beside plain order, truthful completeness signals | done (0.9.0) | D-1.0-13, D-1.0-21; `tests/test_context_continuity.py`, `tests/test_context_display.py` |
