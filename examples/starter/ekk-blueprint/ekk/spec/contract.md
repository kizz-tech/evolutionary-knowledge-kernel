# EKK 0.1 file profile contract

Status: proposed format. The schemas below validate structure, but not all semantic
invariants.

## Identity

A realm has a stable ID. A record has a stable ID independent of its path. UUIDs are
recommended for new IDs; existing stable IDs are allowed without renaming. Duplicate
IDs within a realm are prohibited. An inter-realm address consists of the origin
realm and record ID; a local alias is not a global identity. A replica preserves
its origin.

## Envelope

Markdown starts with YAML frontmatter, followed by a substantive body. Required
fields are schema, id, kind, title, scope, revision, created_at, and created_by.
The `created_by` value is attribution, not proof of authentication. The realm and
default classification are in the manifest.

A context is a kind=context record with `context.purpose`. Its scope may refer to
itself. A source is a kind=source record with `source.assets` or an external URI.
Policies and methods are not executed from arbitrary text. An unknown kind may be
preserved, but must not be automatically interpreted as authority or an executor.

The states of claims, actions, and decisions are not combined into a universal
`done` field. Storage does not imply acceptance, truth, execution, deployment, or
an outcome. Current acceptance is determined by a receipt and governing policy,
not by an accepted field.

## References

`relations` contains rel, target, and, when needed, realm, revision, digest, and
selector. A local relation resolves within the current realm. An external relation
has an explicit origin realm and does not grant read permission. Lack of knowledge
about an external object is not permission to expand the search.

The minimum understood relations are about, derived_from, supports, contradicts,
supersedes, implements, evaluates, and depends_on. Semantic similarity is a search
hint. Support is not proof; temporal sequence is not causation. Grounding references
for significant acceptance are pinned to a version/digest or marked as unverified.
Root sources may be dependent even when they have different IDs.

## Time and review

created_at reflects record creation. observed_at, recorded_at, valid_from, and
valid_until are used only with their corresponding meanings. Unknown times are
not filled in from the migration date. Being known to the system does not prove
that a particular agent has read something.

review.due_at is the date chosen for review, not an automatic revocation date.
review.when contains conditions; without a registered detector, this is text for
analysis, not completed automation.

## Sources

Local assets are within the authorized sources-root; relative paths must not
escape the root or pass through a symlink. A SHA-256 digest refers to the source
bytes. A source change requires a new version/new source, not an unnoticed
replacement. Large or external objects may use a URI, revision/digest, and
availability status. There is no obligation to retain a source forever. Deletion
and withdrawal from distribution are explicitly reflected in provenance and in
the ability to verify later.

## Acceptance and writing

A receipt binds the accepted revision to the SHA-256 of its bytes and the governing
policy digest. Its actor is established by the trusted writer, not by the proposal
text itself. Receipt schema validation does not prove that the actor actually signed
or performed the action.

Integration uses a base snapshot, compare-and-swap, idempotency, and recovery.
Manually changing accepted bytes does not preserve their old acceptance. In the
file profile, one integrator updates the shared published snapshot; parallel agents
work with proposals. Merging text does not resolve a semantic conflict.

## Access

Realm scope is neither audience nor write authority. Application depends on the
principal, operation, target object, and context. A cache and derived text do not
lower classification. YAML, Git ignore, and sparse checkout must not be treated as
protection from a reader of the full Git clone.

## Compatibility

Format, engine, and pack versions are separate. Unknown fields are preserved
through a round trip. An unknown mandatory capability blocks a consequential
operation. The format may evolve through a verifiable migration, not hidden
normalization of the corpus. Schemas do not mean that the core already implements
a safe multi-user runtime.
