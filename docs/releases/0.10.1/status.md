---
release: EKK-R-0.10.1
target_version: "0.10.1"
phase: delivered
updated: "2026-10-11"
implementation: complete
technical_verification: passed
local_delivery: installed_local
public_preparation: export_prepared
public_publication: in_progress
benefit: not_claimed
---

# Current increment state

Planned on 2026-10-10 as the first step of the [0.11 design](../0.11/design.md)
(D-0.11-01) and implemented on 2026-10-10 and 2026-10-11 in the order of the
[plan](tasks.md), under the [implementation decisions](implementation.md). The
[release notes](../../release-notes-0.10.1.md) describe the change.

## Verification

| Acceptance | Result |
| --- | --- |
| 1. Full isolated compatibility suite | Passed on the final tree: 740 tests in 58 jobs. It includes the migration of a 0.10.0 observer database, inserts by a frozen copy of the 0.10.0 store module into the migrated schema, a frozen copy of the 0.10.0 review-page parser, expiry tombstones and text-free rows, refusals without a declaration, and the Claude Code session variable. |
| 2. Loader fingerprint and store verifier | Unchanged from installed 0.10.0, computed on a wheel built from this tree and installed like a release, so activation needs no index rebuild or audit. The wheel holds the same files as 0.10.0's plus the four new modules. |
| 3. Read equivalence against 0.10.0 | Passed on the final tree. All 17 recorded read requests (full and brief entry, fetch, read-source and doctor on two real stores) gave identical output under both runtimes, with exit code 0 and the stores unchanged. This held for the development tree and again for the wheel installed like a release. The card with full IDs is composed by the observer and shown by the session hook, outside these requests. |
| 4. Next explicit expiry after 2026-11-01, no uncounted deletion | Passed on the owner's observer right after activation: `next_expiry` 2026-12-01, the oldest held result's 60-day expiry, and `episodes_deleted_uncounted` 0. Before that, a clock-driven test showed the same values. |

An adversarial review of the whole change found no blocking defect. Its minor
findings were fixed before the final run, and the decisions they changed are
recorded in [implementation.md](implementation.md).

## Delivery

Activated on 2026-10-10 at 23:26:59 UTC, on the owner's word, a week before the
planned 2026-10-17. Moving the date shortens only the descriptive snapshot window
of 0.10.0 (0.11 plan, P01), which now ends at this activation.

- **Build.** The release was built with `tools/local_install.py build` from the
  development commit that holds this tree. Its Python modules are byte-identical
  to the wheel on which reads were compared, and the loader fingerprint and store
  verifier, computed on the release itself, equal 0.10.0's. No warm-up was needed.
- **Hosts.** Every host hook of both hosts and the hourly observer run call the
  stable launcher, so the switch reached all of them at once.
- **Session check.** In a live Claude Code session, the resolver named the host
  `claude-code` and returned that session's own ID from `CLAUDE_CODE_SESSION_ID`.
- **Rollback.** The rollback target is 0.10.0. The installer refuses that
  rollback while the observer holds rows that 0.10.0 would delete without a
  count, unless `--accept-observer-loss` is given. The first such rows appear
  around 2026-11-01, when the oldest episodes pass 30 days.

Still open:

1. Applying the owner's answer to the review of 2026-10-10 with `observe
   apply-review --relayed --words` (0.11 plan, P03) waits for that answer.
2. The private gateway still embeds 0.8.0. It moves to `ekk/host_api.py` with
   G01 in the 0.11 plan.

Mechanism checks establish compatibility, not benefit in later work.
