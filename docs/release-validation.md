# EKK 0.7 release validation

On 2026-09-09 the polished English release passed **431 runtime tests**
in **643.656 seconds of wall time across four independent fixture
processes**, using the non-editable wheel installed into a fresh Python 3.13.5
environment. Actual test-start callbacks record every discovered test ID exactly
once. All **304 exported inputs**, including the export manifest, were frozen
before the run and their hashes were unchanged at completion.

The development checkout also passed its required single-process command,
`.venv/bin/python -m unittest discover -s tests -v`:
**430 tests** in **1611.967 seconds**. The English edition adds its public-language
and translation-provenance test. Runtime, schema and test sources remained
unchanged during these complete runs. The earlier 377-test candidate is superseded
by this polished, fully inventoried distribution.

## Distribution and bounded workflows

- All **43 installed Python modules** and **10 schema/pack resources** match
  the reviewed English source. The wheel contains no additional active modules.
  Version metadata is `0.7.0`; every dependency matches `requirements.lock`, and
  `pip check` passes.
- The original starter's **18 behavioral tests** and fixture validator, the active
  research protocol's **6 contract tests**, and **4 historical replay checks** pass.
- The installed CLI quickstart passes capture, exact source preservation, retry,
  proposal, application, bound entry and doctor. The two-participant method-transfer
  demonstration passes **12 assertions** in fresh installed-runtime processes.
- The pure action-readiness example passes **9 scenarios**. The installed coding
  example passes **9 scenarios**, including stale evidence, a changed Git commit,
  actual fixture-test failure and repair, and a separately observed local effect.
  It uses the shipped disposable-checkout report producer and also exercises a
  named action with compact output. Four real fixture validations have exit codes
  `0, 0, 1, 0`; the intentional failure is required scenario evidence.
- Focused contracts cover governing context despite unrelated optional overflow,
  all-or-none required dependency closure, exact grounds and scope denial, presets
  that cannot weaken owner requirements, concise report diagnostics, target/input
  changes, descriptor-relative reads, and the report producer's uncertainty paths.
- English starter and historical manifests, relative documentation links,
  per-file translation provenance and the editorial output hashes are checked.
  Export review requires every current test to be explicitly included or excluded
  with a concrete reason; unreviewed tests block preparation.

These checks establish the named deterministic implementation and installation
contracts. They do not establish model improvement, human understanding,
comparative productivity or a production outcome. The empirical comparison remains
`designed_not_run`.

## Upgrade, recovery and removal

Two independent disposable installations were upgraded with this exact wheel:
public English **0.5.0** and local original-pack **0.6.0**. Each began with a realm,
three exact pack pins, preserved binary source bytes and a bound profile.

Both upgrades preserved existing tracked realm bytes, Git publication revision,
realm identity and profile bytes during reads. Exact record/source readback,
bound entry, retention, identical retry, continuation, an accepted hold and its
resolution, and private operation diagnostics passed.

Each fixture's owner backup was restored while its original realm was offline.
The restored inventory and Git revision match the backed-up fixture; the active
route was not repointed. With original-pack 0.6 data, the default English provider
rejects the old lock, while the preserved exact original provider succeeds.
Restore with the wrong provider fails before creating final destinations. No pack
lock is rewritten to make a provider match.

Uninstall preserved the fixture realm and profile. Reinstalling the previous wheel
passed doctor and context reads of the post-upgrade fixture. This is bounded
rollback evidence for these fixture records, not a claim that all future 0.7 data
is understood by older runtimes. No active personal, company or project store was
restored, migrated or repointed. See [upgrading](upgrading.md).

## Exact inputs and finalization

The frozen exported-input map SHA-256 is
`a43acd476c4ee7e816e6b3409d1ebbb7cd19e1909d8de8a2eab428ec827205e0`.
It hashes compact sorted JSON with separators `(',', ':')`, mapping each selected
relative file path to its SHA-256. This report and trailing-whitespace cleanup in
the release notes are finalized after testing. Final verification permits only
those two documentation edits and their generated export/translation manifests;
every runtime, test, schema, fixture and other input remains byte-identical.
The wheel itself is unchanged.

Validated wheel SHA-256:
`b380fd33762f1c9fcae58db73711e34ce12b78ad13a3e2ca9dbb38bd2042ebf8`.

Verified upgrade baselines:

- English 0.5.0: `c327c30a241f5a2b1a023718332fd4fadd36ead2197136bfa122e0bafe92aa80`.
- Original-pack 0.6.0: `3b9de94b2246146645dee6eeffcbf94dcf81f0860d43d81b7bc71b1fa4d080d6`.

`SHA256SUMS` identifies the final wheel and source archive. The source archive
contains exactly the reviewed export inventory. The GitHub release tag and asset
digests record publication separately from local validation. Original-language
sources remain preserved outside the public export, with exact translation
provenance. See [source provenance](runtime-starter-provenance.md) and the
[release preparation procedure](releasing.md).

## Scope and support limits

Record format remains `ekk.record/0.1`. Coding assessment reads a selected committed
Git object and configured fallible reports. It does not assess uncommitted changes,
authenticate the producer, execute the action or observe its outcome. Required
context that is blocked or incomplete cannot yield readiness. A known failed
condition remains visible even when incomplete context makes the overall result
indeterminate. See [coding readiness](coding-readiness.md).

The explicit host report producer is not an OS sandbox. Native Windows has not
been validated. Profiles route access but do not isolate processes sharing a
filesystem. The export excludes active knowledge, personal/company profiles,
runtime state and private development Git history.
