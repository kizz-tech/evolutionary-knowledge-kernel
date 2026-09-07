# Starter source and runtime evidence

The architecture starter archive is now supplied. Its 74 extracted files are
preserved unchanged under `examples/starter/ekk-blueprint/`, including hidden
manifests, three synthetic realms, project binding, four schemas, original read-only
validator and its 18 test cases. These are source artifacts, not agent instructions
for this repository and not deployed company stores.

The canonical `spec/contract.md`, four `spec/schemas/*.json`, supplied architecture,
interfaces, implementation, migration and release-evidence documents, three packs,
and the adapter guide also preserve the corresponding starter bytes. Current root
contribution, governance, security and citation files are release metadata maintained
separately; their exact original versions remain in the nested starter. The starter's design-time claims about missing
runtime or publication status describe that supplied artifact, not a fresh runtime
audit. Current implementation evidence belongs in separate runtime reports.

Provisional assets written before the archive arrived were preserved in a private
planning archive. Additional provisional runtime-extension schemas are not part of this release. Authored templates and the `sequence-learning` study are supplements;
`001-environment-learning` is the exact supplied study, marked `not_run`.

Run original tests from repository root, in a separate invocation from runtime tests:

```sh
.venv/bin/python -m unittest discover -s examples/starter/ekk-blueprint/ekk/tests -p test_files.py -v
.venv/bin/python examples/starter/ekk-blueprint/ekk/tools/validate.py examples/starter/ekk-blueprint/ekk/knowledge
```

Dependencies are recorded unchanged in the starter's `ekk/tools/requirements.txt`.
The tests use their own fixture copy and validator; they do not establish safe
runtime apply, corporate isolation, real migration or empirical improvement.
