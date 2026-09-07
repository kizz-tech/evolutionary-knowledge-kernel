# Historical runtime 0.4

Historical source and legacy-only tests from the pre-migration working
snapshot, with English display strings and design-pack prose in this edition.
Exact untranslated originals remain in v0.4.0; see the root translation manifest. This directory is excluded from the installed Python package. It is
never selected by current CLI/profile routing. The supplied starter remains
separately unchanged under examples/starter.

Run historical semantic replay from the repository with `python research/replay.py`.
To reproduce legacy tests explicitly: `PYTHONPATH=archive/runtime-0.4/src python -m
unittest discover -s archive/runtime-0.4/tests -v` (one shell line). These historical
APIs do not grant permission to write retired real stores. Use disposable fixtures.
The obsolete working-environment prototype is preserved only in the private local
migration archive; it was never completed or shipped.
