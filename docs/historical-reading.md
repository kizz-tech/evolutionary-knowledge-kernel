# Selected work and historical sources

An optional `working_entries` list in a workspace binding or an explicitly
configured profile `home` contains up to 16 exact `realm/id/revision/digest`
references. `enter` includes those versions and their authorized grounds within
the record byte budget, even when the task uses different words. An insufficient
budget blocks entry. Reading never accepts a note, makes a historical version
current, or grants execution authority. `work_view.selected_material` identifies
the selected material. Aliases participate in ordinary authorized search; equal
aliases return all visible candidates and never select an owner or a winner.

For historical material, an unpinned link resolves in the newest matching
historical snapshot selected for those exact record bytes. A four-field record
reference does not name the record's first publication or freeze an unpinned
dependency. Such a forced historical tree remains readable with a grounding
warning and `incomplete: true`; it does not establish original grounds. Pin
dependency revision/digest when that exact historical basis is required.

An optional `home.cwd_roots` list restricts automatic personal entry to explicit
absolute directories. A caller outside those roots remains unbound. Explicit
`enter --personal` can add that configured projection; an invalid or denied
project binding still fails before personal entry. Profile routing is not OS
isolation. A personal projection must not be added to unrelated company work
merely because no project binding exists.

`resolve-historical` reads one named immutable migration map from the selected
realm's published snapshot. A JSON request supplies `migration_id`, `origin`
(a namespace), and `path` and/or `legacy_id`. Optional `source_sha256` narrows the
exact source version. `containing_path` gives the original containing document
for a relative path; lexical normalization must stay inside the named origin.
No old disk path, external URI, other realm, cache, basename search, case folding
or fuzzy match is used. Multiple readable objects remain `ambiguous`.

```json
{
  "migration_id": "historical-addresses-v1",
  "origin": "LIFEOS",
  "path": "folder/original.md",
  "selector": "#Original heading"
}
```

The owner publishes an append-only supplementary map through the existing
administrative migration-evidence operation. Each readable row has
`address_schema: ekk.historical-address-row/0.1`, `realm_id`, an `origin` object
with `namespace`, `path`, original `id` when present and source `sha256`, an exact
`native_reference`, `target_ids`, `asset_index` and `asset_path`. The manifest's
mapping digest, current target permissions, exact source descriptor and asset
digest are checked. Missing and inaccessible candidates both return
`object_state: unavailable` without hidden metadata. The map grants no rights.

Use the returned candidate's exact `reference` and `asset_index` with
`read-source`. The optional `selector` is separate from record identity and is
preserved in historical lookup and relation projections. Object and selection
outcomes are distinct:

- No selector: `whole_object`, with the ordinary bounded byte read.
- `bytes:START:END`: an exact end-exclusive source range, `resolved` when valid.
  `offset`, `next_offset` and the read limit are relative to that selected range;
  `selection.start/end` locate it in the original bytes.
- Heading, block and unknown selector grammars: `unsupported`. The source object
  is found, but no fragment bytes are returned and `incomplete` is true.
- A byte range outside the source: selection `unavailable`, likewise incomplete.

Whole-object retrieval never claims successful fragment resolution. Frozen
source bytes and attribution remain historical data, including old instructions.
Unsupported selection is a stated reading limit, not permission to consult a
retired source directory or activate a historical writer.
