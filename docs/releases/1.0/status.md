---
release: "EKK-R-1.0"
target_version: "1.0.0"
phase: delivered
updated: "2026-10-11"
scope: owner_delegated_decisions_recorded
implementation: runtime_0.10.1_committed
technical_verification: runtime_0.10.1_tested
local_delivery: runtime_0.10.1_installed
public_preparation: runtime_0.10.1_export_prepared
public_publication: runtime_0.9.1_published_0.10.1_in_progress
benefit: baseline_measured_comparison_not_run
current_authority: target_1.0_accepted_by_owner_statement
---

# Current release state

The owner asked for the whole 1.0 design to be implemented and delegated the
open decisions on 2 October (D-1.0-09 to D-1.0-21 in [decisions](decisions.md)),
and accepted the 1.0 target as the governing direction the same day.
0.8.4 (write path), 0.9.0 (experience, current-first entry, the contract,
evidence, advisor in shadow) and 0.9.1 (the owner's word as the input of
authority, documents as projections) are the result. Delegation (G) and recall at a
change of focus are deferred with recorded reasons.

## Done

- Field-use study and a frozen baseline of real use for September 2026 (private
  output): 458 sessions, 332 with changes, 40 retained by agents; 857 correction
  candidates under `ekk.correction-rule/1`, 120 repeated.
- 0.8.1–0.8.3: BM25 entry, one agent view, asynchronous retention, Claude Code
  parity, entry latency (S08), isolated test runner and local installer (S18).
- 0.8.4: writes that finish (S20): one write on a copy of the larger store went
  from 497 s to about 11 s; queued capture; a publisher that takes late requests.
- 0.9.0: host hooks and the observer (S09, S10), session card (S11 at entry),
  preferences as records (S15), current-first entry with standing-preserving
  supersession and priors recorded beside plain order (S22), one agent contract,
  the review page (S07), the field-use measures for retention, corrections and
  entry use (S06), the advisor adapter and batch shadow (S14, partly), and the
  write-path hardening from the review. Full suite: 587 tests OK on the 0.9.0
  source; no known failures.
- An adversarial review of the first 0.9.0 change set (eight lenses, 60 confirmed
  findings) was applied before installation; the material changes are recorded as
  D-1.0-11 (rule 2), D-1.0-13 (priors), D-1.0-18 to D-1.0-21.
- 0.9.1: the owner's word as the only input of authority (`ekk decide`,
  acceptance with the owner's statement, acceptance from the review page,
  declared provenance, owner-wide preferences), documents as projections
  (`ekk project decisions`), the hourly observer run, the final report as the
  outcome, the session card through the entry's own selection; decisions
  D-1.0-22 to D-1.0-26 and a revised D-1.0-12, all recorded with `ekk decide` in
  the development realm. Two findings of an external review of the public
  0.9.0 code are closed here (D-1.0-22, D-1.0-23). Installed on 2026-10-02 with
  `tools/local_install.py` after the equivalence gate against 0.9.0 (17 real
  requests identical) and `warm`; the hourly launch agent is registered.
- The 1.0 target (`EKK-R-1.0`) is the governing direction since 2026-10-02:
  the owner accepted it in a chat session and the agent relayed the statement
  with `ekk accept --statement-file` (`via: host_chat`); the receipt holds the
  owner's words. The 0.5 direction is superseded, and the context `context:ekk`
  names the target as its basis (revision 4): while it still named the replaced
  0.5 record, entry in the realm was blocked with `declared context basis is not
  a current accepted commitment`, so a context's basis must follow its accepted
  successor. The delegated decisions D-1.0-01 to D-1.0-26 stay proposed; they
  are current knowledge selected by ranking, not governing reading.
- 0.9.1 published on 2026-10-02 as the public prerelease v0.9.1 (commit
  `9992890`), assets read back and verified.
- 0.10.0 (exact continuation, discovery through linked observations,
  declared-file retention, reading receipts) was installed locally on 2026-10-05
  and not published on its own ([status](../0.10/status.md)). 0.10.1 (explicit
  counted expiry, declared provenance, `accept --id --words`, one host identity)
  was activated on 2026-10-10 at 23:26:59 UTC ([status](../0.10.1/status.md)) and
  is prepared as the public prerelease v0.10.1, which carries both. The next step
  toward this target is [0.11](../0.11/status.md).

## Local delivery

- Runtime 0.9.0 was installed on 2026-10-02 from the 0.9.0 source with
  `tools/local_install.py` (full suite 587 tests OK); the previously installed
  runtime is its rollback (`tools/local_install.py rollback`). Before activation
  the candidate passed the read equivalence gate against the previous runtime on
  real requests: `fetch`, `read-source` and `doctor` identical on both stores;
  entry requests differ by design (agent view 0.3, additive manifest fields,
  governing first, priors). `warm` ran after activation: every store audited and
  indexed (the larger store 50 s audit, 209 s index; the smaller 20 s and 0.7 s).
- Hooks registered with `ekk observe install` for both hosts; the installer keeps
  a dated backup of each edited file. The registered `SessionStart` hook answered
  in 60 ms with the contract. Codex runs new hooks only after the owner trusts
  them (Q7).

## Owner actions

| ID | Action | Why |
| --- | --- | --- |
| Q7 | Trust the EKK hooks in each Codex profile (`/hooks` in the TUI, or "Trust all and continue" at start) | Codex runs a new hook only after the owner trusts it; "trust all" also trusts any other hook registered in that profile |
| Q8 | Once a week: `ekk observe review`, mark the page, `ekk observe apply-review --owner-marked-page FILE` (or `--relayed --words REPLY FILE` when an agent relays the owner's reply) | The page is the only source of owner verdicts; it measures the correction rule, the episode rule and the ranking priors, and it is where held results and preferences are kept |
| Q9 | After two weeks of hooks: rerun the field-use report against the September baseline | Retention after changes and repeated corrections are the primary measures; nothing in 0.9.0 is yet shown to help |

## Next

- Rerun the field-use report a week after installation, excluding the
  development and test-suite journal rows of 2026-10-01 and 2026-10-02 with
  `--journal-exclude` windows.
- Compare entry order with plain order on the owner's first relevance sample;
  amend D-1.0-13 if one order is clearly better.
- When owner labels exist, compare the advisor's shadow labels with them
  (`ekk observe advise` reports the agreement) before any use.
- Recall at a change of focus and delegation stay deferred until field use shows
  the need (D-1.0-14, D-1.0-16).
