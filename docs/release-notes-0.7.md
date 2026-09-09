# EKK 0.7 — Belief Runtime preview

This release connects preserved knowledge to a bounded assessment of the next
action. Record format `ekk.record/0.1`, realm identity and owning-system execution
authority are retained.

- `ekk assess --cwd PROJECT --action NAME --compact` combines one bound authorized context,
  current Git commit identity and configured report bytes. It distinguishes met
  prerequisites, failed prerequisites, missing observations and indeterminate state.
- Named actions declare checks and exact grounds in the workspace binding. The
  action projection retains all governing commitments and their dependency closure
  without unrelated optional reading. Compact results expose per-check reasons
  and the next evidence step; the full JSON request remains supported.
- `tools/check_report.py` explicitly runs a supplied argument vector in a disposable
  checkout of the exact commit, validates tracked inputs before and after, and
  writes an atomic configured report. It is a host operation, never called by assess.
- Release preparation now uses a versioned, hash-pinned plan and an explicit
  complete test inventory. Original sources and translation provenance are retained.
- A blocked or incomplete context, incomplete requirements, wrong commit, expired
  or future report, or observed change during collection cannot yield readiness.
  Reports remain fallible declarations; exact hashes do not authenticate CI or
  turn a command's success into an observed product outcome.
- The pure experimental Python projection retains exact historical inputs. The
  new adapter reads fixed local Git metadata and owner-configured reports; it
  executes no test, action or retrieved instruction.
- A disposable installed-CLI workflow uses a real Git repository, an actual
  fixture-test failure and repair, and a separately observed local effect.
- Explicit host pack-provider selection preserves existing exact original-pack
  locks when upgrading to the English distribution; mismatches fail validation.
- The included 0.6 daily-reliability work adds exact outcome retention/readback,
  retry-safe additive retention, bounded private diagnostics, owner backup/restore,
  explicit challenges and current repository evidence.

The Python assessment API and report-based coding workflow are experimental.
Automatic sensor selection, working-tree assessments, external test-producer
authentication and capability execution integration are outside this release.
The empirical comparison remains `designed_not_run`.

Start with [coding readiness](coding-readiness.md). See [validation and upgrade
limits](release-validation.md) and [daily reliability](daily-reliability.md).
