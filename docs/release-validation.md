# Implementation evidence

The model-effectiveness study has not run. These results concern the local
implementation and synthetic installation checks only.

## Baseline checked before this publication pass

Runtime 0.4.0 at development revision `40e67473bfdc6cc9b4096fe361700a56a44da983`
passed 265 runtime tests, 18 original starter tests, and the historical replay.
The runtime suite took 375.523 seconds. A fresh wheel installation passed ten
common-envelope operation cases, including retries and key-conflict rejection;
ten bundled canonical schemas/pack resources matched their source bytes.

This is historical development evidence, not a public Git commit reference.
The clean release has its own history. Release documentation, packaging metadata,
and the compact context display were subsequently updated; final export checks
are recorded below. Private migration and operational reports are excluded.

## Publication candidate checks

On 2026-09-07 the frozen candidate passed **272 runtime tests** in
519.511 seconds with no failures or errors, **18 original starter tests**, and
the historical functional replay. All **73** files in the original starter
manifest matched their declared hashes.

A final CLI discovery correction followed that full run: current top-level help
and version output, current unbound entry on a fresh installation, and
command-first recovery routing. After this correction, **46 focused tests** passed
in 28.661 seconds, covering the new entrypoint, existing legacy CLI, historical
integration and registry compatibility, current CLI, and source-export boundary.
The complete 272-test suite was not repeated after this narrow routing change.

A fresh non-editable installation from the final code passed the full disposable
CLI quickstart, current version output, and dependency checks. It imported from
installed site-packages with Python 3.13.5. The driver checks exact-byte capture,
retry identity, scoped context, snapshot-pinned proposal/application, read-back,
and doctor. No inherited EKK profile or store is used.

After removing a machine-specific identifier from the export guard, its five
boundary tests passed again.

The source suites selected the frozen `src/` through `PYTHONPATH`; subprocesses
inherited that source selection. Test/build artifacts are excluded from the final
export. Current release documentation was finalized after the checks. Private
operational reports and development Git history are not shipped.

The SHA-256 of the sorted compact JSON map of the final runtime/test input paths
and their hashes is `5cce91d2287bb1a636df502509d82aaa39c0cf586ae7ed88778c3b9be5be3c23`. Reconstruct it from `export-manifest.json` by
selecting `src/`, `tests/`, `spec/`, `packs/`, `pyproject.toml`, `requirements.lock`,
and `examples/quickstart.py`; serialize with sorted keys and separators `(',', ':')`.
This identifies the final source covered by the baseline plus focused regression
checks; it does not claim a second complete suite run on these final bytes.

## Limits

Local tests do not establish model improvement, external source truth, or
production outcomes. The writer uses POSIX facilities; native Windows was not
validated. Local profiles are routing controls, not isolation from other processes
with access to the same disk. No hosted IAM or always-on conversation capture is
included. Negative empirical results remain possible.
