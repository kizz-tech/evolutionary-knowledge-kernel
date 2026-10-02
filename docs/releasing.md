# Preparing an English release

Product scope, tasks, decisions and delivery state live in a
[working release package](releases/README.md). This page owns artifact preparation
and its existing JSON contract; creating a release spec does not build, install
or publish a package. New package documents enter an export only after explicit
inventory review.

Prepare from the development checkout's explicit `ekk.reference_export.FILES`
allowlist into a new, separate output directory. Never push development history
or include active knowledge, profiles, local reports or runtime state. Preparation
has no installation, publication or adoption authority.

`tools/prepare_release.py` accepts one versioned JSON plan:

```sh
python3 tools/prepare_release.py /path/to/reviewed-plan.json
```

All relative input and output paths resolve against the plan's directory. The
output must not exist and must be outside the source and prior snapshot trees.
Input files and output paths cannot traverse symlinks. Use the source environment
with its declared dependencies when synthetic source assets need re-pinning.

The plan has exactly these fields:

```json
{
  "schema": "ekk.release-preparation-plan/1",
  "version": "0.7.0",
  "source": "development-source",
  "output": "prepared-english",
  "prior_raw": {
    "root": "previous-original-export",
    "receipt": {"path": "previous-original-receipt.json", "sha256": "REVIEWED_HASH"}
  },
  "prior_english": {
    "root": "previous-english-export",
    "receipt": {"path": "previous-english-receipt.json", "sha256": "REVIEWED_HASH"}
  },
  "path_mappings": {"docs/architecture.ru.md": "docs/architecture.md"},
  "extra_files": {
    "tests/test_public_english.py": {"path": "reviewed-english-test.py", "sha256": "REVIEWED_HASH"}
  },
  "translations": {},
  "replacements": [],
  "synthetic_assets": [],
  "manifests": {
    "examples/starter/ekk-blueprint/MANIFEST.sha256.json": "map",
    "archive/runtime-0.4/MANIFEST.sha256.json": "rows"
  }
}
```

This illustrates the schema; a runnable plan must enumerate **every** reviewed
`.ru.md` mapping in the current allowlist. The tool accepts only those exact
English path conversions. Extra files are restricted to the reviewed public
English test and the generated translation manifest. The resulting
`release-edition.json` lists these mappings and extras explicitly. The exporter
reads that fixed declaration through `inventory(repository)` and remains byte
identical to its original source; preparation does not patch Python allowlists.
Checks that read exported paths should use `inventory(root)`, not `FILES`, because
`FILES` always names the original source inventory.

Every existing `tests/**/test_*.py` must be in the selected inventory or have a
nonempty, concrete reason in `REVIEWED_TEST_EXCLUSIONS` in the exporter source.
Discovery only blocks an incomplete review; it never adds files to the export.
Review new runtime modules and the public source boundary before preparing.

The tool verifies every prior snapshot byte against its hash-pinned export
receipt, then checks translation provenance against both snapshots. It reuses
prior English bytes only when the current original is byte-identical to its
verified prior original. A changed English file remains current. Changed
non-English prose requires a reviewed translation, for example:

```json
{"docs/architecture.ru.md": {
  "original_sha256": "EXACT_CURRENT_ORIGINAL_HASH",
  "input": {"path": "translations/architecture.md", "sha256": "REVIEWED_ENGLISH_HASH"}
}}
```

Each translation or late documentation snapshot is an explicit input with both
an original hash and a hash of its replacement. No remembered intermediate
candidate or file naming convention selects it. Python Cyrillic string literals
may become escapes only when the complete AST is identical; comments require
translation. The Cyrillic check detects the known source-language boundary, not
all possible languages. Human review still establishes English quality.

Literal prose and edition changes use explicit entries with exact match counts:

```json
{"path": "README.md", "old": "exact starter provenance",
 "new": "starter translation provenance", "count": 1}
```

List only changes needed for the selected bytes. A mismatch fails preparation.
Use these reviewed entries for package edition versions, references to renamed
documents, provenance language and the public test's inventory call. Do not
change the exporter source. The tool never edits a live realm or rewrites a
runtime lock to match a provider. Existing English pack versions and lock pins
are reused with the verified snapshots; changed pack inputs require explicit
edition decisions and replacements in the plan.

To update a synthetic starter source digest, list its exact `record` path and
`realm` directory in `synthetic_assets`. Both must be under
`examples/starter/ekk-blueprint/`. Both fixed starter and historical manifests
are refreshed against their existing entry inventories. No new manifest entries
are discovered. Preserve the original snapshots outside the public export.

The new output contains `originals/`, `source-export/`, the exact `plan.json` and
`receipt.json`. The receipt records pinned inputs, original and translated hashes
for every selected source file, translation methods, the export inventory and
reviewed test exclusions. It means **prepared for review**, not validated or
published. Private paths remain in the local plan/receipt, outside source-export.
Run the complete current tests, starter tests, research checks and distribution
checks against the frozen export before publication. Preserve their exact input
hashes and results separately. Any later documentation finalization must be an
explicitly selected snapshot in a new preparation plan and be checked again.
