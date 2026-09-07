# EKK: target architecture and first implementation contract

Document version: 0.1. Date: 2026-09-07. Status: a design specification proposed to Maxim for implementation. This is not a report on an already operational EKK, a result of the LIFEOS migration, or evidence of superiority over other systems.

## 1. The solution as a whole

EKK consists of one open software project, independent owner stores, working project connections, and separate execution state. LIFEOS as the previous architecture is retired after the transfer has been verified; personal data becomes an ordinary private EKK instance, rather than a special subsystem of the new kernel.

Terms:

- **Realm**: an area of knowledge governance. It has a stable identifier, an owner, and authority rules. It is not necessarily one server or one Git repository.
- **Scope / context**: the subject area a record describes or in which a decision applies. The file format uses context records and the `scope` field.
- **Store**: physical storage. In the first implementation, the default is one Git repository per realm, with uniform access to source files.
- **Workspace binding**: a declaration of the knowledge and execution tools to which a working project is connected.
- **Pack**: a versioned set of methods, format extensions, templates, and checks. It is neither a copy of company data nor a separate engine.
- **Runtime**: the executing program and its state. The model connects as a replaceable executor; the specification itself does not depend on a model provider.

A normal installation:

```text
~/Workspaces/
  ekk/                         public software and research project
  personal-knowledge/          owner's private store
  kizz-knowledge/              knowledge of owned projects, separate from personal knowledge
  company-x-knowledge/         organization store, only where permitted
  givon/                       existing product code
  company-x-product/           existing corporate product
```

This is a working folder, not a shared Git repository. Repository separation is determined by permissions, ownership, and release cycles, not the number of note categories. A repository for every record type, domain, or research hypothesis is unnecessary. For owned projects intended to be shared with a team, a separate kizz realm is recommended from the outset. If access membership differs between products, a full clone of the shared kizz store is not distributed: the product receives a separate store/realm or an authorized projection. The organization template in this package applies both to kizz's own activities and to an external company.

## 2. What will be open

The open `ekk` repository contains the specification, reference engine, CLI, adapters, standard packs, synthetic examples, the public development history of EKK itself, reproducible research, and documentation.

It does not contain the personal knowledge base, client records, corporate traces, real support requests, secrets, internal system addresses, private migration maps, or an export of the entire old LIFEOS. The public repository starts clean: it is not a private repository whose current files were later deleted.

```text
ekk/
  README.md
  LICENSE                       added after confirming the license and rights
  CITATION.cff                  real authors; no invented DOI or release
  CONTRIBUTING.md
  SECURITY.md
  GOVERNANCE.md                 authority of public project maintainers
  AGENTS.md                     short agent entry point
  pyproject.toml                packaging of the working engine after implementation
  spec/
    contract.md                 normative semantics
    schemas/                    machine-checkable envelopes
  src/ekk/
    model/                      IDs, links, versions, valid transition rules
    application/                reading, proposals, acceptance, context, review
    ports/                      storage, authority, source, executor, clock
    adapters/                   Markdown/Git, SQLite, processes, future networks
    cli.py                      thin transport over application
  packs/
    base/
    research/
    software/
  adapters/                     integration instructions for agent clients
  knowledge/                    public realm of the EKK project itself
  research/
    studies/                    experiment protocols and fixed reports
  tests/                        conformance, recovery, isolation, integrations
  docs/                         guides, architecture, migration, publication
```

Initially, this is **one Python project**, not a collection of published libraries and microservices. Directories represent dependencies, not mandatory processes. `model` does not import Git, SQLite, LLM providers, or UI. `application` uses ports. The CLI, and later MCP/HTTP, call the same operations. An SDK or separate repository may be extracted when independent consumers and a release cycle emerge, not in advance.

Python is chosen for the reference implementation as a design decision: it combines file processing, experiments, and verification tools. The language of user products is unrelated to EKK's language. The CLI's JSON contract allows the engine to be called from another stack.

## 3. A universal realm on disk

```text
personal-knowledge/
  README.md
  AGENTS.md
  .gitignore
  .ekk/
    realm.yaml                  ID, defaults, storage roots
    governance.yaml             authority rules, not secrets
    packs.lock.yaml             selected pack versions and digests
  contexts/
    self.md
    work.md
    research.md
  records/
    <uuid>--short-title.md
  sources/
    <source-uuid>/
      original.txt
      original.pdf              only if storage is permitted
  governance/
    receipts/                   durable receipts for significant acceptances
  migrations/
    <migration-id>/
      manifest.yaml
      mapping.jsonl
      validation.md
  views/                        derived views, outside Git by default
```

An empty realm does not need every directory. A manifest and at least one context are required. The others appear as needed. `company-x-knowledge` has the same structure. It will have different context records, authority, and packs, but not a different core.

Folders such as `records/architecture` and `records/decisions` are optional. Physical grouping may be introduced for convenience: it must not change a record's ID or meaning. Avoiding semantic dependence on paths does not mean prohibiting folders.

`contexts/*.md` and `records/*.md` use a common envelope. A context differs through an additional block: purpose, significant concepts, explicit relationships, and links to current grounds. Membership in a parent context does not itself inherit authority or mandatory rules. Application of a shared rule is declared explicitly.

`governance.yaml` is a control document. Editing it does not become authorized merely because an agent can write YAML. In single-user local mode, trust rests on the owner of the process and files. In corporate mode, the control document and acceptances are protected by a trusted writer/CI and environment permissions.

## 4. Records and sources

A new record receives a UUID-based ID. An old stable LIFEOS ID is retained if it does not create ambiguity. Renaming a file does not change its ID. Splitting and merging records are reflected in the migration map and provenance. New links use IDs rather than paths.

Minimum fields: `schema`, `id`, `kind`, `title`, `scope`, `revision`, `created_at`, `created_by`. The realm, base classification, and retention rules are inherited from the manifest. Additional fields appear when needed, not for the sake of a complete form.

Recommended kinds: `context`, `note`, `source`, `observation`, `claim`, `question`, `decision`, `policy`, `action`, `outcome`. This is the vocabulary of the first implementation, not a philosophical proof of minimality. An unknown kind can be stored and displayed as a document; it must not automatically be given governance or executable meaning.

The Markdown body remains the main place for reasoning. The description of a single task may contain an observation and a local conclusion without splitting them into two files. A separate new record is needed when independent applicability, provenance, review, or subsequent reuse differs.

A source is represented by a `kind: source` record. It points to original bytes in `sources/` or to an external object with a version and, where possible, a digest. There is no need to duplicate source code, calendars, Figma, and the entire corporate database in Markdown. Those systems remain the owners of their facts; EKK stores links, interpretations, and decisions.

The original record and its interpretation are distinct. A summary does not replace an audio recording when continued retention of that recording is justified and permitted. Keeping all originals forever is not a rule: retention, deletion, and distribution restrictions take priority over audit convenience.

### Links and time

An ordinary navigation link may be unpinned. A link used as grounds for a significant decision must point to a specific version or digest and, when needed, a fragment. A `supports` assertion does not prove causality.

Storing `created_at` / `recorded_at` is mandatory for the corresponding event; `observed_at` and `valid_from` / `valid_until` are added where applicable. `null` means unknown, not the current date. Claiming that a particular agent actually saw material requires a manifest of its working context or tool reads. The time material entered the database alone is insufficient.

## 5. What counts as in force

The existence of a file does not mean a decision has been accepted. A field an agent wrote as `accepted` does not establish authority. Acceptance of a significant commitment is bound to the exact content, the accepting party's authority, and the state of the control rules.

An acceptance receipt contains: the record ID, the SHA-256 of its bytes, the time of acceptance, the identifier of a principal established through a trusted mechanism, the digest of the applied rules, the basis of authority, and information about replacement of the previous decision. It contains no secrets. In the initial trusted-local mode, this is the owner's journal, not cryptographic proof against the machine's owner.

Editing accepted content creates a new revision and requires new acceptance. A simplified procedure may be defined for typos, but an old receipt must not silently be transferred to a different digest.

A revision refines the same record. `supersedes` denotes a new decision replacing the previous one. Conflicts between decisions in force are not resolved by a "latest wins" rule. Without authorized conflict resolution, the result is a detected conflict and a restriction on the affected action.

Links to old versions are resolved through retained history and source manifests. Rewriting Git history for necessary data deletion may require additional relocation/removal markers. History does not promise immortality for prohibited data.

## 6. Knowledge, code, and processes do not have one global owner

`spec/contract.md` defines EKK's normative semantics. `knowledge/records` preserves why they were accepted and which alternatives were considered. These are different questions, not two versions of the specification.

`src/` defines the behavior actually implemented. Checks show observed conformance to the specification, but do not relabel intent as implementation.

`packs/` contains methods and reusable tools. An accepted pack is pinned by version and digest. A new upstream version does not automatically begin changing a private company's rules.

The research protocol in `research/studies/<id>/protocol.yaml` is the source of experiment configuration; the linked question/claim record in `knowledge` is the source of the hypothesis and its history. The final report is fixed as a research artifact, not a mutable overview page.

Product system code remains in its repositories. Product architecture knowledge resides in the owner's realm by default. A colocated realm at `product/knowledge` is allowed if knowledge, code, and authority really must change in one Git transaction. In that case, the central realm references it instead of containing a second managed copy. Each specific object is assigned one canonical record owner.

## 7. Connecting a product

```text
product-repo/
  AGENTS.md
  .ekk/
    workspace.yaml
  src/
  tests/
```

`workspace.yaml` contains a stable workspace ID, authorized realm aliases and context IDs, required packs, and references to existing verification commands. It contains no absolute path to a personal disk, tokens, or copy of all company rules.

A local registry resolves an alias to a path or endpoint. It is stored outside Git, separately for the active role. A corporate working profile must not have automatic access to the personal realm. An ambiguous binding stops the operation; EKK does not choose the first vault it finds.

`AGENTS.md` briefly explains how to resolve the binding, obtain constraints in force, find grounds, and propose changes. It does not repeat the entire knowledge base or require a fictional command before the CLI exists. During bootstrap, the agent reads the specified Markdown directly and checks changes with an actual local validator.

Existing tests, builds, and deployment do not move into EKK. It can invoke a registered tool in an authorized environment and retain a link to the result. Reading an unfamiliar source or installing a pack does not execute its commands.

## 8. Execution state

The application determines platform-native configuration, data, and cache directories. The following are logical names, not mandatory absolute macOS paths:

```text
CONFIG/ekk/
  profiles/
    personal.yaml
    company-x.yaml
DATA/ekk/<realm-id>/
  journals/                      unfinished changes and recovery
  receipts/                      receipts not yet published
  evidence/                      run artifacts needed for the result
  projections/                   authorized versioned snapshots
CACHE/ekk/<realm-id>/<grant-id>/
  index.sqlite
  bundles/
  search/
```

A cache can be rebuilt. An unfinished journal and the sole copy of evidence cannot be deleted as cache. Journals are completed or recovered; evidence undergoes retention management. Important receipts are published to the realm or another authorized durable evidence store.

Cache keys account for the realm, authorized projection, data snapshot, authority version, packs, and query. Revoking access blocks future delivery; bytes already received by a user cannot be promised to be revoked. A local index of corporate data is itself corporate data.

SQLite is used in the first version as a rebuildable index, not a second canonical author. Raw traces and large media are not committed automatically. Git alone is not an independent backup: recovery is tested from a separate copy.

## 9. Engine operations

The proposed CLI, not yet implemented in this package:

```text
ekk init          create an empty realm or workspace binding
ekk doctor        check structure and list unverified guarantees
ekk context       resolve applicable grounds for a task
ekk capture       register material or an observation
ekk propose       prepare a change against a specific snapshot
ekk apply         apply a change with CAS and confirmed authority
ekk review        find selected grounds for reconsideration
ekk export        assemble an explicit portable package for another owner
```

Migration and the research runner may be separate subcommands, but use the same write rules. There is no need to create a separate utility for every noun in the model.

Operations are available to the agent as JSON input/output over the same application use cases. A human can read Markdown without the CLI. A later server transport does not reinvent the semantics of these operations.

### Context

First, the active role, workspace, realm, and permitted projection are established. Then all declared mandatory constraints of the target context are loaded and their applicability is checked. Only then is the remaining relevant material ranked.

The result contains mandatory constraints, selected decisions, grounds, conflicts, unknowns, and a manifest. The manifest records snapshots, policy/pack digests, records used, possible incompleteness, and freshness. Snapshots from different realms are not presented as a single atomic transaction.

If mandatory constraints do not fit within the context budget, the system does not silently truncate them: it narrows the task scope, performs explicit staged reading, or reports a block. Semantic search and an LLM summary cannot establish completeness with respect to unknown constraints.

### Propose / apply

Agents prepare independent changesets against a fixed snapshot. One trusted writer integrates them into the realm. Changes to different records may be merged; a change to an object that has already changed requires revalidation. A change to the set of commitments in force also checks that authority and the base snapshot remain current.

For the file implementation, the writer prepares the change in a separate workspace, validates it, creates a Git commit, and switches the published ref only if the expected parent matches. Concurrent readers use the published snapshot. An ordinary folder is allowed in single-user mode, but receives no promise of atomic reads during arbitrary manual edits.

Artifacts outside Git require a journal of previous bytes, an idempotency key, execution stages, and verification after writing. Repeating an operation does not create duplicates. Rollback does not overwrite other parties' new changes: the bytes actually applied are compared first.

There is no fictional shared ACID transaction between a code repository and a knowledge realm. A change receipt is stored with separate confirmations: proposed, code change accepted, information updated, version released, result observed. Unfinished coordination remains visible and retryable.

## 10. Federation and confidentiality

Personal, corporate, and public knowledge bases do not have to merge into one store. Reference, authorized projection, versioned replica, import, and publication are allowed.

A replica retains the origin realm and source of authority; it does not become a new owner of a decision. Import/derivation creates a local record with provenance and local status. Even a public method does not become a mandatory corporate rule without acceptance within the relevant bounds.

Git synchronization is allowed among participants authorized to read the entire repository available to them and its history. If some employees must not see part of the material, this cannot be enforced with a YAML `audience` field, `.gitignore`, or sparse checkout. Separate physically accessible stores/projections or server-side delivery are required. This is a limitation of the current mode, not a need to move all corporate IAM into the prototype.

Derived summaries, embeddings, search models, and logs inherit the restrictions of the content used. Transfer to a personal or public realm requires a separate authorized export, not merely removal of the company name. The existence of a source and its ID may also be sensitive.

Provenance helps verify origin, but does not make a source true or guarantee statistical independence. Counting different root IDs is not an estimate of the probability of truth.

## 11. The practical work cycle

An employee's request is first connected to an existing product, a goal, and available capabilities. The agent must be able to choose configuring an existing tool instead of creating a new application. For a new internal tool, the owner, data, permissions, checks, and maintenance are defined. It does not enter production merely because its author is pleased with its appearance.

Next, context and the software pack are used, a bounded action is performed, and the result is checked using established tools. Significant results and surprises are retained. A full note/claim/decision/action/outcome set is not required for every edit. No new durable record is a normal result.

Design questions receive design methods, not a technical score. A user's preference is stored as a preference. Personal processes have their own outcome criteria. Sensitive personal meanings do not become the owner's canonical self-assessment merely because an agent inferred them.

## 12. Evolution and its limits

Review is triggered by significant refutation, an unmet expectation, a recurring independent failure, or a change in the goal, applicability period, or model capabilities. Periodic checks provide a safeguard for already selected subjects of attention, not mandatory rereading of the entire corpus.

Two thresholds are distinct: grounds for spending attention on diagnosis, and grounds for changing the system. Three complaints do not constitute a refactoring command. A change is compared with doing nothing, refining knowledge, improving a tool, and running a small experiment. Future demand, cost, effects on other work, reversibility, and verification quality are considered.

The expectation for a significant decision is formulated before the result; it is later linked to an observation, including a negative or uncertain one. A deferred decision has a reason and a condition for reconsideration. A record's age alone does not imply falsehood.

A recurring lesson may become a rule, SDK, template, or check. But increasing the number of rules is not the goal. A check should protect a current product invariant, not merely lock in an incidental code shape. When the architecture or model changes, unnecessary instructions and tools are removed through the same verifiable process.

Review metadata contains executable triggers only where a detector is registered. The phrase "when the situation changes" remains a human-readable condition; it is not presented as an already implemented scheduler.

## 13. Self-improvement of EKK itself

`ekk/knowledge` describes the public EKK project and its development. The first version is therefore used to develop the next. Before a full runtime exists, the cycle operates through Markdown, Git, and read-only checking, without requiring the system to be finished before it may be used.

An engine or method change has a proposal, an exact base version, a predicted effect, a check, and an acceptance decision. An experimental branch may change its own code, but not the trusted configuration of the baseline evaluator or the permissions under which it will be accepted. A new evaluator can also be researched, but as a separate change and through comparison with the old one.

The external evaluation boundary may belong to the owner, CI, or another restricted process. This does not require human approval of every step. It prohibits a single experiment from silently rewriting the objective, the measurement mechanism, and the result.

Agents do not overwrite the running runtime binary in the middle of their own run. A new build is tested separately and applied in the next selected run. Engine, format, and pack versions are distinct. Unknown mandatory semantics must not be silently interpreted by an old engine.

## 14. Research and public materials

The following are published openly: the specification, reproducible fixtures, code, exact experimental methodology, permitted result artifacts, negative results, limitations, and change history. Private examples are replaced with synthetic ones or published with separate permission and honest labeling.

The main testable claim: a persistent environment may improve a fixed model's performance over a sequence of changes by accumulating and applying experience. This is a hypothesis, not an established fact for EKK.

Comparisons: ordinary documentation; memory with retrieval; records of grounds and review; a full cycle that changes tools/checks. The budget includes not only solving user tasks, but also maintaining the knowledge base, reviews, experiments, and failed interventions. Model and tool versions are recorded; limits on the reproducibility of remote models are stated explicitly.

Evaluation includes result quality, regressions, repetitions of known errors, unnecessary interventions, full-cycle cost, and human involvement. Subsequent tasks are not declared evidence of learning merely because they turned out to be easier. Comparable branches and sequences, repeated runs, and predeclared criteria are used. Held-out tasks and protected checks do not enter mutable memory before the corresponding measurement is complete.

An architecture article and demonstration may be published first with an explicit prototype status. Empirical claims are added after experiments. Do not claim scientific priority based solely on previous assistant answers. Related work is checked anew against primary sources.

Apache-2.0 is recommended for author-owned code, specification, and examples in the public project; third-party data has its own terms. This is a choice to confirm before release, not completed company licensing. Before opening the project, define the boundary between the shared project and commissioned work, and agree on permitted contributions and corporate case studies. `CITATION.cff` records real authors; DOIs, grants, benchmarks, and paper status are not invented.

## 15. LIFEOS migration

Migration transfers meaning and verified useful artifacts, rather than preserving the previous architecture under new names.

**Inventory.** The agent establishes the actual Git roots, nested repositories, dirty and untracked files, sources, attachments, links, agent profiles, scripts, scheduled jobs, and external owners. The available LIFEOS projection indicates separate LIFEOS and Work roots, but this must be verified on the machine. The application has no direct access here to the new, partially implemented version.

**Snapshot.** Git history and the actual bytes of uncommitted work, necessary external objects, and configuration are preserved. Restoration is tested in a separate location. Until then, there is no destructive deletion of the source vault.

**Routing.** For each source unit, a destination realm and action are recorded: transfer, retain as an external source, archive, restrict/exclude, or send for review. Uncertainty is not replaced with a confident guess. Data is not published automatically.

**Mapping.** The migration ledger contains origin ID/path/revision/hash, target IDs, transformation, reason, and validation result. Original sources are not paraphrased instead of preserved; decisions in force are not accepted anew in the agent's voice. Old system policies move to historical/proposed unless the user has chosen them as rules in force for the new EKK. Valuable utilities may be rewritten as adapters rather than copied into the core.

**Pilot.** One bounded context is transferred and a real task is performed. Knowledge, a historical-state question, conflict, provenance, context boundaries, and return to the source are checked. Valid YAML does not count as semantic success.

**Cutover.** Each scope switches to one active writer. Old routes, profiles, cron, and automatic publications for the migrated context are disabled or become read-only redirects. There is no prolonged bidirectional writing. The migration team may work in waves without preserving the old architecture in the final system.

**Retire.** After coverage, real tasks, and restoration have been verified, the old vault becomes a read-only archive with a limited retention period/policy; it may later be deleted separately. Rollback after new work uses current changesets and reverse transformations, not blind replacement of the entire knowledge base with an old snapshot.

## 16. Implementation order and completion criteria

1. **Reconciliation with work already started.** The agent reads the actual repository, compares the implementation with this specification, and reuses compatible parts. It does not create a second engine merely because it received a new document.
2. **A readable foundation.** Manifest, record envelope, scopes, IDs, source pinning, acceptance histories, and export. Complete when a realm can be read without a model, collisions/broken links can be detected, and versions can be restored.
3. **Safe writing.** Propose/apply, snapshots, CAS, idempotency, recovery. Complete after tests of concurrent changes and a crash in the middle of an operation. Until then, migration operates in a copy/branch rather than as an uncontrolled overwrite.
4. **The first end-to-end cycle.** Context → real task → significant outcome → revisitation. Working search may initially be lexical. Complete when an agent uses a constraint in force and does not treat source text as an instruction.
5. **Migration of one context, then LIFEOS.** Complete based on mapping coverage, queries, and real tasks, not the number of files moved.
6. **Connecting a corporate pilot.** A separate realm, existing product, limited team, and authorized sources. Complete with correct isolation and repeatable useful results.
7. **Evolutionary mode and research.** Introduce review budgets, expectation checks, experiments in removing old rules, and full cost accounting. Complete with reproducible comparative data, including negative results.
8. **Public release.** Clean repository history, rights and licenses, tests, examples, a guide, reproducible experience, and honest limitations. A server and complex UI are not prerequisites for the first release.

## 17. How the system grows without changing its meaning

Local mode: files/Git + SQLite index + one writer. Team mode with uniform access: Git proposals + one integrator/CI + published snapshots. Corporate mode with differing permissions: a server-side writer and permission-filtered projections; files are not distributed to everyone. Large-scale mode: when measured need arises, the canonical record store moves to transactional storage, while Markdown remains the portable import/export and editorial representation.

Changing the backend involves an explicit migration: checking IDs, significant revisions, sources, authority, acceptances, queries, restore, and cutover. The old and new backends do not become independent canonical writers of the same object. Connecting HTTP instead of the CLI does not itself change canonical storage.

The specification's lifespan does not prohibit schema changes. A new field may be optional. New governance semantics require a version and a reader-capability check. Pack, engine, and format have separate versions; there is no forced mass migration for every engine release.

## 18. What should not be built now

There is no need for a global data lake of all owners, a universal business workflow, a graph database by default, a swarm of permanent agents, a SaaS dashboard, a separate repository for each pack, a custom calendar and task tracker replacing those already used, corporate IAM inside Markdown, automatic execution of others' instructions, or an immutable copy of every intermediate line of reasoning.

What is needed is a working vertical slice with preserved meaning and real write control. The ability to change these details without losing history or authority is the intended resilience, rather than a definitively predicted list of future files.

## 19. Sources and limits of evidence

Decisions about EKK repository structure, commands, and rules are proposals of this specification. The following primary sources support individual engineering properties, but do not prove the value of the whole system:

- [S1] W3C PROV-DM: provenance, entities, activities, agents, and an extensible domain-independent model. `https://www.w3.org/TR/prov-dm/`
- [S2] Git sparse-checkout: controlling working-tree contents, not an access boundary. `https://git-scm.com/docs/git-sparse-checkout.html`
- [S3] OpenAI, AGENTS.md instructions: an integration point for a specific agent, not a replacement for an independent EKK contract. `https://developers.openai.com/codex/guides/agents-md/`
- [S4] NIST ABAC: authority depends on the subject, object, operation, and request conditions. `https://csrc.nist.gov/Projects/attribute-based-access-control`
- [S5] Darwin Gödel Machine, primary paper: evaluation of self-modified agents on external tasks. Not evidence of EKK's effectiveness. `https://arxiv.org/abs/2505.22954`
- [S6] GitHub, CITATION.cff: describing how to cite a software project. `https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-citation-files`
- [S7] Apache License 2.0, official text. `https://www.apache.org/licenses/LICENSE-2.0`
- [S8] GitHub, removing sensitive data: deleting the current file does not remove history or others' copies. `https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository`

The available LIFEOS projection `00-system/architecture/Current State.md`, dated 2026-09-05, was used only to identify migration risks: multiple Git roots, external owners of facts, existing profiles/routes, and unverified restoration. It is not a disk inventory or an audit of the new implementation.
