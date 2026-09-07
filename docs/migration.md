# LIFEOS migration contract

The goal is to move knowledge, sources, and useful tools into EKK, not to preserve
the former System/Work/Research mechanisms as mandatory layers of the new architecture.

## Before writing

Establish actual paths, Git roots, and dirty and untracked files. Check nested Git
roots, external sources, links, agent profile configuration, automated writers, and
scheduled jobs. A previous response or read-only projection does not replace a
machine inventory.

Make an independent snapshot and restore it to a separate directory. A Git HEAD
snapshot without uncommitted/untracked bytes is insufficient. Do not delete raw
sources after extraction.

## Migration package

Located in the private destination realm:

```text
migrations/<id>/
  manifest.yaml
  mapping.jsonl
  validation.md
```

Large backups live in separate authorized backup storage. Git receives only
permitted manifests and references, not secrets, credentials, or a copy of all media.

An example ledger line, not a claim about an existing file:

```json
{"origin":{"root":"legacy-root-id","path":"example.md","id":"legacy:example","sha256":"<actual sha256>"},"action":"migrate","targets":["legacy:example"],"reason":"preserve identity and meaning","validation":"pending"}
```

Actions: migrate, retain_external, archive, restricted_exclusion, approved_delete,
needs_review. Every original remains accounted for. approved_delete requires separate
confirmation, not an automatic decision by the migrator. Split/merge operations
preserve mappings for all original IDs.

## Semantic classification

The owner's personal statements do not become agent conclusions. Sources do not
become accepted decisions. Old `accepted` status is preserved as a historical fact
of the previous system; not every old system prohibition automatically becomes
a new EKK rule.

Code, actual deployments, external tasks, and calendars remain with their owners.
Their Markdown description is not execution or external synchronization.

Suitable packs are selected from old methods. Old routers, compilers, automatic
publication, and prohibitions are not carried over merely because "they existed."
A useful mechanism is moved to the new contract only after its purpose is checked.

## Checks

Structural: preservation of IDs, absence of collisions, availability of local links,
source/digest correspondence, ledger coverage, absence of raw private data in a
public target, and disabling the previous writer after cutover.

Semantic: significant constraints, grounds for decisions, current/historical status,
effective date/knowledge date, preference/agent conclusion, authorized scope,
contradictions, unavailable sources, and links to code and outcomes. Prepare
representative questions from the actual corpus and verify answers against primary
materials.

Operational: a real task using migrated context, a repeated operation, recovery,
a concurrent change, and an explicit absence of a full guarantee wherever it has
not been verified.

## Cutover and rollback

One scope has one active writer. During migration, scopes may be switched in
sequence; prolonged two-way writing by the old and new systems is prohibited.
Old entrypoints receive a read-only redirect or are disabled, including background jobs.

If new work appears after cutover, rollback does not mean destroying it with an old
backup. A reverse changeset or export of new changes is required. The old snapshot
is used for restoration with version checks and subsequent reconciliation.

The final report separately identifies: copied, structurally_validated,
semantically_checked, cut_over, legacy_read_only, restore_verified, and retired.
They are not collapsed into a single "done."
