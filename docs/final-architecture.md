# Personal entry, shared continuity, revisable methods

Runtime 0.5 implements the owner-selected direction: a person starts from an
intention; shared work remains available to successors; useful methods can be
preserved, transferred and reconsidered. The existing knowledge kernel is the
foundation, not the product's main interaction.

## Boundaries

`WorkspaceService` composes independently authorized personal and shared context
projections. The existing profile and workspace resolver owns routing. Entry and
resume do not write knowledge, infer a personal profile from behavior, or create
a task database. Personal context inside a bound project requires `--personal`.
An explicitly configured profile home supports personal entry outside a project;
an unresolved or denied project binding never falls back to it.

`RealmService` owns records, exact sources, revisions, acceptance, current context,
CAS writes and recovery. It retains `ekk.record/0.1`. Accepted shared commitments,
results and continuation references remain project-owned. Git and task trackers
continue to own code and task state. EKK does not copy an entire participant's
history to make a project continuable.

`MethodService` composes canonical method records with host-installed execution.
Its repository adapter represents a candidate as an inert note plus an immutable
artifact source, an evaluation as an exact source, admission/retirement as local
decisions and receipts, and adverse observations as outcomes. There is no second
method database. A private proposal journal provides exact retries.

`CapabilityRuntime` remains the activation boundary. A run reconstructs current
local acceptance, pinned grounds, artifact identity, adapter registration,
applicability, host permission and quarantine state. The host registry supplies
callbacks; a source cannot supply a Python import, shell command, URL or token.
The shipped adapter only prepares handoff artifacts and makes no external effect.
Other systems remain responsible for their execution and access enforcement.

## Lifecycle

1. A significant experience may justify a method candidate. Zero new methods is
   valid. Preserve the artifact, applicable work/environment/model, privileges,
   limitations, grounds, rollback and reconsideration conditions.
2. An independently controlled registered case evaluates the exact artifact.
   Store the receipt and result, including failure. Do not infer general benefit.
3. The local owner accepts an admission decision grounded in a passing local
   evaluation. This makes a method available; it does not execute it.
4. Every use repeats current activation checks. A fresh process reconstructs
   eligibility from canonical records and host evidence rather than importing an
   old in-memory activation permit.
5. A source owner may export the exact current candidate and artifact under
   explicit existing export grants. The receiver pins the bundle digest and
   captures it as inert source. Origin acceptance is not imported. Receiver
   evaluation and acceptance create independent local authority.
6. Re-evaluation can retain an adverse outcome and create a review candidate.
   Review does not infer causality or silently rewrite a commitment. Host
   quarantine blocks future use. Canonical retirement supersedes local admission
   while preserving history. A replacement increments the method record revision
   and requires its own evaluation and acceptance.

## Evidence boundaries

A local acceptance receipt proves the recorded operation against the configured
trusted-local governance. It is not cryptographic proof against the OS owner.
An imported digest proves agreement on bytes, not the remote issuer's authority.
The receiving host must obtain the package through an authorized channel.

The local executor keeps evaluation receipts and quarantine outside knowledge.
Restoring knowledge alone never recreates a missing execution receipt or bypasses
quarantine. The same OS user remains trusted; this is not hostile multiuser
isolation. Current source read permission and host admission are checked again
before use. Uncontrolled prior copies cannot be erased by this mechanism.

The method demo uses deterministic callbacks, fresh processes and synthetic
principals. It demonstrates preservation, useful artifact transfer, adverse
verification, withdrawal, replacement and historical reconstruction. A model or
human benefit requires the separate frozen comparative study.

## Migration choices

The selected design reuses the deep kernel and capability runtime. It rejects
adapting the unfinished universal work/mandate/approval engine: that prototype
solved a larger administrative problem before the method-transfer claim was
shown. Its exact files and known failures are retained in the private migration
archive; it is absent from the active package.

Legacy `Kernel`, `RealmStore`, federation, integration and old CLI modules and
their tests live in an explicit historical archive. The current CLI cannot route
to them. Original starter and supplied source bytes remain preserved in v0.4.0 and the
owner archive. This release contains a traced English edition. No
realm IDs, personal/company ownership, current binding or accepted historical
record is silently relabelled by the code migration.

Two independent engineering reviews supported this boundary: clean-boundary
architecture and evolutionary pragmatism. Their main tension was how much durable
activation state was needed. The chosen implementation persists execution evidence
and quarantine but derives method availability from the existing canonical
records. Unknown downstream legacy consumers remain a compatibility limit;
historical replay is explicit rather than an active fallback.
