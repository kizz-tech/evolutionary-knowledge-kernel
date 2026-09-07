# English edition and preserved sources

Version 0.5.0 publishes English documentation, method packs, synthetic fixtures
and validator messages. These are reviewed translations of the earlier supplied
materials, not byte-identical originals and not evidence that historical design
claims have become implemented. Current behavior is described in final-architecture.md.

The exact untranslated starter remains available in the immutable
[v0.4.0 source tree](https://github.com/kizz-tech/evolutionary-knowledge-kernel/tree/v0.4.0/examples/starter/ekk-blueprint)
and the owner's preserved source archive. `translation-manifest.json` maps each
translated file to its original path and SHA-256. The current starter and
historical runtime manifests describe this English edition's bytes. The four
canonical schemas retain their original bytes. No actual personal or company
store is included or translated.

The examples retain synthetic identifiers and demonstrate structure only.
Translated source assets have recalculated SHA-256 values in their source records.
No acceptance is inherited from translation. Pack prose has the distinct version
`0.1.0-design.en`, so old exact pins cannot silently refer to different bytes.
Existing stores must keep their original matching pack provider or explicitly
review and update their pack lock through owner-authorized configuration;
installing a new wheel does not authorize that update.

Run the English starter validator and its original 18 behavioral cases:

```sh
python -m unittest discover -s examples/starter/ekk-blueprint/ekk/tests -p test_files.py -v
python examples/starter/ekk-blueprint/ekk/tools/validate.py examples/starter/ekk-blueprint/ekk/knowledge
```

Historical plans and source assertions remain historical even when translated.
The model-effectiveness study has not run. See release-validation.md for actual
runtime, localization, installation and publication-candidate checks.
